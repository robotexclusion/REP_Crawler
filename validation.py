"""Generate reproducible samples for manual and cross-crawl validation."""

import argparse
import csv
import random
import sqlite3
from pathlib import Path

SAMPLE_COLUMNS = [
    "domain_name", "https_homepage_url", "https_robots_url",
    "http_homepage_url", "http_robots_url", "crawl_id", "tranco_rank",
    "timestamp", "protocol", "status_code", "result", "content_type",
    "response_time_ms", "bytes", "sha256", "policy_hash", "truncated",
    "completed", "parse_errors", "lines", "comments", "blank_lines",
    "user_agents", "directives", "diagnostics", "meta_tags",
]


def setup_arg_parser():
    parser = argparse.ArgumentParser(
        prog="REP Crawler Validation",
        description=(
            "Generate reproducible samples for browser verification and "
            "cross-crawl comparison."
        ),
        usage="python validation.py [options]",
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "-s", "--single", metavar="CRAWL_ID",
        help="Generate a validation sample for one crawl.",
    )
    selection.add_argument(
        "-m", "--multiple", nargs="+", metavar="CRAWL_ID",
        help="Generate aligned samples for two or more crawls.",
    )
    parser.add_argument(
        "-v", "--seedvalue", type=int,
        help="Seed for reproducible sampling. A random seed is used by default.",
    )
    parser.add_argument(
        "-n", "--numsamples", type=int, default=100,
        help="Number of domains to sample per run. Defaults to 100.",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=Path.cwd() / "data",
        help="Root data directory. Defaults to ./data.",
    )
    return parser.parse_args()


def _validate_sample_size(num_samples):
    if num_samples < 1:
        raise ValueError("--numsamples must be at least 1.")


def _parse_crawl_ids(values):
    crawl_ids = []
    for value in values:
        crawl_ids.extend(part.strip() for part in value.split(","))
    crawl_ids = [crawl_id for crawl_id in crawl_ids if crawl_id]
    if len(crawl_ids) < 2:
        raise ValueError("--multiple requires at least two crawl IDs.")
    if len(set(crawl_ids)) != len(crawl_ids):
        raise ValueError("--multiple cannot contain duplicate crawl IDs.")
    return crawl_ids


def _crawl_paths(base_dir, crawl_id):
    crawl_dir = Path(base_dir) / crawl_id
    paths = {
        "directory": crawl_dir,
        "crawl_db": crawl_dir / "metadata.sqlite",
        "parsed_db": crawl_dir / "parsed.sqlite",
    }
    missing = [
        path for path in paths.values()
        if path != crawl_dir and not path.is_file()
    ]
    if not crawl_dir.is_dir() or missing:
        missing_text = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(
            f"Crawl {crawl_id} is missing required data: "
            f"{missing_text or crawl_dir}"
        )
    return paths


def _connect_crawl(base_dir, crawl_id):
    paths = _crawl_paths(base_dir, crawl_id)
    connection = sqlite3.connect(paths["crawl_db"])
    connection.row_factory = sqlite3.Row
    connection.execute(
        "ATTACH DATABASE ? AS master_domains",
        (str(Path(base_dir) / "domains.sqlite"),),
    )
    connection.execute(
        "ATTACH DATABASE ? AS parsed_data",
        (str(paths["parsed_db"]),),
    )
    return connection, paths["directory"]


def _sample_indices(row_count, num_samples, seed_value):
    sample_size = min(num_samples, row_count)
    if sample_size == 0:
        return []
    return sorted(random.Random(seed_value).sample(range(row_count), sample_size))


def _create_sample_table(connection, domains):
    connection.execute(
        "CREATE TEMP TABLE validation_sample "
        "(sample_index INTEGER PRIMARY KEY, domain_name TEXT UNIQUE NOT NULL)"
    )
    connection.executemany(
        "INSERT INTO validation_sample(sample_index, domain_name) VALUES (?, ?)",
        enumerate(domains),
    )


def _available_domains(connection):
    return [
        row[0]
        for row in connection.execute(
            """
            SELECT master_domains.master_domain_names.domain_name
            FROM fetches
            JOIN domains ON fetches.domain_id = domains.domain_id
            JOIN master_domains.master_domain_names ON
                domains.master_domain_id = master_domain_names.master_domain_id
            WHERE fetches.completed = 1
            GROUP BY master_domains.master_domain_names.domain_name
            ORDER BY master_domains.master_domain_names.domain_name
            """
        )
    ]


def _common_domains(base_dir, crawl_ids):
    first_connection, _ = _connect_crawl(base_dir, crawl_ids[0])
    aliases = []
    try:
        for index, crawl_id in enumerate(crawl_ids[1:], start=1):
            alias = f"crawl_{index}"
            aliases.append(alias)
            paths = _crawl_paths(base_dir, crawl_id)
            first_connection.execute(
                f"ATTACH DATABASE ? AS {alias}",
                (str(paths["crawl_db"]),),
            )

        query = """
            SELECT master_domains.master_domain_names.domain_name
            FROM master_domains.master_domain_names
            JOIN domains AS first_domains ON
                first_domains.master_domain_id = master_domain_names.master_domain_id
            JOIN fetches AS first_fetches ON
                first_fetches.domain_id = first_domains.domain_id
                AND first_fetches.completed = 1
        """
        for alias in aliases:
            query += f"""
                JOIN {alias}.domains AS domains_{alias} ON
                    domains_{alias}.master_domain_id = master_domain_names.master_domain_id
                JOIN {alias}.fetches AS fetches_{alias} ON
                    fetches_{alias}.domain_id = domains_{alias}.domain_id
                    AND fetches_{alias}.completed = 1
            """
        query += (
            " GROUP BY master_domains.master_domain_names.domain_name "
            "ORDER BY master_domains.master_domain_names.domain_name"
        )
        return [row[0] for row in first_connection.execute(query)]
    finally:
        first_connection.close()


def _fetch_sample_rows(connection):
    query = """
        SELECT
            sample.sample_index,
            master_domains.master_domain_names.domain_name,
            fetches.crawl_id,
            fetches.tranco_rank,
            fetches.timestamp,
            fetches.protocol,
            fetches.status_code,
            fetches.result,
            fetches.content_type,
            fetches.response_time_ms,
            fetches.bytes,
            fetches.sha256,
            fetches.policy_hash,
            fetches.truncated,
            fetches.completed,
            parsed_data.files.parse_errors,
            parsed_data.files.lines,
            parsed_data.files.comments,
            parsed_data.files.blank_lines,
            (
                SELECT group_concat(user_agents.user_agent, ' | ')
                FROM parsed_data.groups
                JOIN parsed_data.user_agents USING (group_id)
                WHERE parsed_data.groups.fetch_id = fetches.fetch_id
            ) AS user_agents,
            (
                SELECT group_concat(
                    directives.directive || ': ' || directives.value,
                    ' | '
                )
                FROM parsed_data.groups
                JOIN parsed_data.directives USING (group_id)
                WHERE parsed_data.groups.fetch_id = fetches.fetch_id
            ) AS directives,
            (
                SELECT group_concat(
                    diagnostics.diagnostic_code || ': ' || diagnostics.message,
                    ' | '
                )
                FROM parsed_data.diagnostics
                WHERE parsed_data.diagnostics.fetch_id = fetches.fetch_id
            ) AS diagnostics,
            fetches.meta_tags
        FROM validation_sample AS sample
        JOIN master_domains.master_domain_names ON
            master_domains.master_domain_names.domain_name = sample.domain_name
        JOIN domains ON
            domains.master_domain_id = master_domain_names.master_domain_id
        JOIN fetches ON fetches.domain_id = domains.domain_id
            AND fetches.completed = 1
        LEFT JOIN parsed_data.files ON
            parsed_data.files.fetch_id = fetches.fetch_id
        ORDER BY sample.sample_index
    """
    rows = []
    for row in connection.execute(query):
        item = dict(row)
        item["https_homepage_url"] = f"https://{item['domain_name']}"
        item["https_robots_url"] = f"https://{item['domain_name']}/robots.txt"
        item["http_homepage_url"] = f"http://{item['domain_name']}"
        item["http_robots_url"] = f"http://{item['domain_name']}/robots.txt"
        rows.append(item)
    return rows


def _write_sample(rows, output_path):
    with output_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output, fieldnames=SAMPLE_COLUMNS, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


def _sample_crawl(base_dir, crawl_id, domains, output_name):
    connection, crawl_dir = _connect_crawl(base_dir, crawl_id)
    try:
        _create_sample_table(connection, domains)
        rows = _fetch_sample_rows(connection)
        output_path = crawl_dir / output_name
        _write_sample(rows, output_path)
        return rows, output_path
    finally:
        connection.close()


def single_crawl_validation(seed_value, num_samples, base_dir, crawl_id):
    connection, _ = _connect_crawl(base_dir, crawl_id)
    try:
        available = _available_domains(connection)
    finally:
        connection.close()

    indices = _sample_indices(len(available), num_samples, seed_value)
    domains = [available[index] for index in indices]
    rows, output_path = _sample_crawl(
        base_dir, crawl_id, domains, f"validation_sample_{crawl_id}.csv"
    )
    print(f"Saved {len(rows)} domains to {output_path}")
    return output_path


def _write_comparison(rows_by_crawl, domains, output_path):
    fields = ["domain_name", "https_homepage_url", "https_robots_url"]
    for crawl_id in rows_by_crawl:
        fields.extend([
            f"{crawl_id}_result", f"{crawl_id}_status_code",
            f"{crawl_id}_protocol", f"{crawl_id}_sha256",
            f"{crawl_id}_policy_hash", f"{crawl_id}_bytes",
            f"{crawl_id}_parse_errors", f"{crawl_id}_diagnostics",
            f"{crawl_id}_meta_tags",
        ])

    indexed = {
        crawl_id: {row["domain_name"]: row for row in rows}
        for crawl_id, rows in rows_by_crawl.items()
    }
    with output_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for domain in domains:
            first = next(indexed[crawl_id][domain] for crawl_id in rows_by_crawl)
            record = {
                "domain_name": domain,
                "https_homepage_url": first["https_homepage_url"],
                "https_robots_url": first["https_robots_url"],
            }
            for crawl_id, crawl_rows in indexed.items():
                row = crawl_rows[domain]
                prefix = f"{crawl_id}_"
                for field in fields:
                    if field.startswith(prefix):
                        record[field] = row.get(field.removeprefix(prefix))
            writer.writerow(record)


def multiple_crawl_validation(seed_value, num_samples, base_dir, crawl_ids):
    domains = _common_domains(base_dir, crawl_ids)
    indices = _sample_indices(len(domains), num_samples, seed_value)
    selected_domains = [domains[index] for index in indices]
    rows_by_crawl = {}

    for crawl_id in crawl_ids:
        rows, output_path = _sample_crawl(
            base_dir,
            crawl_id,
            selected_domains,
            f"validation_sample_{crawl_id}.csv",
        )
        rows_by_crawl[crawl_id] = rows
        print(f"Saved {len(rows)} domains to {output_path}")

    comparison_path = Path(base_dir) / (
        "validation_comparison_" + "_".join(crawl_ids) + ".csv"
    )
    _write_comparison(rows_by_crawl, selected_domains, comparison_path)
    print(f"Saved cross-crawl comparison to {comparison_path}")
    return comparison_path


def main():
    args = setup_arg_parser()
    _validate_sample_size(args.numsamples)
    seed_value = (
        args.seedvalue
        if args.seedvalue is not None
        else random.SystemRandom().randrange(1_000_000)
    )
    print(f"Random seed value: {seed_value}")
    print(f"Number of samples: {args.numsamples}")

    if args.single:
        single_crawl_validation(
            seed_value, args.numsamples, args.data_dir, args.single
        )
    else:
        crawl_ids = _parse_crawl_ids(args.multiple)
        multiple_crawl_validation(
            seed_value, args.numsamples, args.data_dir, crawl_ids
        )


if __name__ == "__main__":
    main()
