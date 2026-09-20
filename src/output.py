#Holds functions related to generating output from the crawled data

#imports
import csv
import json
from pathlib import Path
import sqlite3

#datum are huge, need to stream instead of loading into memory
def write_query_csv(connection, query, output_path):
    cursor = connection.execute(query)
    with open(output_path, "w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow([column[0] for column in cursor.description])
        while rows := cursor.fetchmany(10000):
            writer.writerows(rows)

#grab the master domain names
def dump_master_domains_csv(master_domain_db_path, output_path):
    conn = sqlite3.connect(master_domain_db_path)
    query = """
        SELECT master_domain_id, domain_name
        FROM master_domain_names
        ORDER BY master_domain_id
    """
    write_query_csv(conn, query, output_path)
    conn.close()
    return output_path


#function to create and output readable csv files from the crawl
def generate_crawl_dataframes(
        crawl_db_path,
        master_domain_db_path,
        parsed_db_path,
        crawl_id,
        output_dir
        ):

    #filename vars
    crawl_df_filename = f"{crawl_id}_crawl_data.csv"
    robots_df_filename = f"{crawl_id}_robotstxt_data.csv"
    meta_df_filename = f"{crawl_id}_meta_tags_data.csv"
    diagnostics_df_filename = f"{crawl_id}_diagnostics_data.csv"

    #attach databases
    conn = sqlite3.connect(crawl_db_path)
    cur = conn.cursor()
    cur.execute(f"ATTACH DATABASE '{master_domain_db_path}' AS master_domains")
    cur.execute(f"ATTACH DATABASE '{parsed_db_path}' AS parsed_data")

    #ready
    print("Generating output data")

    #generate query tables and stream to csv
    #main domain/crawl data csv
    print("Generating domain data")
    crawl_query = """
        SELECT
        fetches.fetch_id,
        fetches.crawl_id,
        fetches.domain_id,
        domains.master_domain_id,
        master_domains.master_domain_names.domain_name,
        fetches.tranco_rank,
        fetches.timestamp,
        fetches.status_code,
        fetches.result,
        fetches.protocol,
        fetches.response_time_ms,
        fetches.bytes,
        fetches.exception,
        fetches.index_content_type,
        fetches.index_truncated,
        fetches.has_robots,
        fetches.index_response_status,
        fetches.index_last_exception,
        fetches.index_error,
        fetches.index_exception,
        fetches.meta_tags_truncated,
        fetches.truncated,
        fetches.completed
        FROM fetches
        LEFT JOIN domains ON fetches.domain_id = domains.domain_id
        LEFT JOIN master_domains.master_domain_names ON
            domains.master_domain_id = master_domains.master_domain_names.master_domain_id
        ORDER BY fetches.fetch_id
    """
    write_query_csv(conn, crawl_query, output_dir / crawl_df_filename)

    #robots summary data
    print("Generating robots.txt summary data")
    robots_query = """
        SELECT
            'user_agent' AS record_type,
            user_agents.user_agent AS name,
            'USRAGT' AS classification,
            COUNT(*) AS occurrences,
            COUNT(DISTINCT groups.fetch_id) AS fetches
        FROM parsed_data.user_agents AS user_agents
        JOIN parsed_data.groups AS groups ON groups.group_id = user_agents.group_id
        GROUP BY user_agents.user_agent
        UNION ALL
        SELECT
            'directive' AS record_type,
            directives.directive AS name,
            directives.classification,
            COUNT(*) AS occurrences,
            COUNT(DISTINCT groups.fetch_id) AS fetches
        FROM parsed_data.directives AS directives
        JOIN parsed_data.groups AS groups ON groups.group_id = directives.group_id
        GROUP BY directives.directive, directives.classification
        ORDER BY record_type, classification, name
    """
    write_query_csv(conn, robots_query, output_dir / robots_df_filename)

    #robots issues/diagnostic data
    print("Generating robots.txt diagnostics data")
    diagnostics_query = """
        SELECT
        diagnostics.fetch_id,
        fetches.domain_id,
        domains.master_domain_id,
        master_domains.master_domain_names.domain_name,
        diagnostics.diagnostic_id,
        diagnostics.line_number,
        diagnostics.diagnostic_code,
        diagnostics.severity,
        diagnostics.raw,
        diagnostics.directive,
        diagnostics.value,
        diagnostics.message
        FROM parsed_data.diagnostics AS diagnostics
        JOIN fetches ON fetches.fetch_id = diagnostics.fetch_id
        LEFT JOIN domains ON fetches.domain_id = domains.domain_id
        LEFT JOIN master_domains.master_domain_names ON
            domains.master_domain_id = master_domains.master_domain_names.master_domain_id
        ORDER BY diagnostics.fetch_id, diagnostics.line_number,
            diagnostics.diagnostic_id
    """
    write_query_csv(conn, diagnostics_query, output_dir / diagnostics_df_filename)

    #meta tag summary data
    print("Generating meta tag summary data")
    meta_rows_query = """
        SELECT
        fetches.fetch_id,
        fetches.domain_id,
        domains.master_domain_id,
        master_domains.master_domain_names.domain_name,
        fetches.index_truncated,
        fetches.meta_tags_truncated,
        fetches.meta_tags
        FROM fetches
        LEFT JOIN domains ON fetches.domain_id = domains.domain_id
        LEFT JOIN master_domains.master_domain_names ON
            domains.master_domain_id = master_domains.master_domain_names.master_domain_id
        ORDER BY fetches.fetch_id
    """
    with open(output_dir / meta_df_filename, "w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow([
            "fetch_id",
            "domain_id",
            "master_domain_id",
            "domain_name",
            "robots_rule",
            "rule_occurrences",
            "robots_tag_count",
            "malformed_tag_count",
            "conflicting_tag_count",
            "unknown_rule_count",
            "meta_tags_truncated",
        ])
        for (
            fetch_id,
            domain_id,
            master_domain_id,
            domain_name,
            _index_truncated,
            meta_tags_truncated,
            meta_tags_json,
        ) in conn.execute(meta_rows_query):
            try:
                meta_tags = json.loads(meta_tags_json)
            except (TypeError, ValueError):
                continue
            if not isinstance(meta_tags, list):
                continue
            robots_tags = [
                tag for tag in meta_tags
                if isinstance(tag, dict) and tag.get("is_robots_tag", False)
            ]
            if not robots_tags:
                continue
            rule_counts = {}
            malformed_tag_count = sum(
                bool(tag.get("robots_malformed", False)) for tag in robots_tags
            )
            conflicting_tag_count = sum(
                bool(tag.get("robots_conflicting_rules")) for tag in robots_tags
            )
            unknown_rule_count = sum(
                len(tag.get("robots_unknown_tokens", [])) for tag in robots_tags
            )
            for tag in robots_tags:
                rules = tag.get("robots_rules") or ["(none)"]
                for rule in rules:
                    rule_counts[rule] = rule_counts.get(rule, 0) + 1
            for rule, occurrences in sorted(rule_counts.items()):
                writer.writerow([
                    fetch_id,
                    domain_id,
                    master_domain_id,
                    domain_name,
                    rule,
                    occurrences,
                    len(robots_tags),
                    malformed_tag_count,
                    conflicting_tag_count,
                    unknown_rule_count,
                    meta_tags_truncated,
                ])
    cur.close()
    conn.close()

    print(f"Saving output data for crawl '{crawl_id}'")
    print(f"Output data saved for crawl '{crawl_id}' in '{output_dir}'")
    return

#main output logic
def main_output_func(
        args,
        master_domain_db_path,
        parsed_db_path,
        crawl_id,
        crawl_db_path,
        output_dir
    ):
    #autorun
    if args.autorun:
        print("Building output.")
        generate_crawl_dataframes(crawl_db_path, master_domain_db_path, parsed_db_path, crawl_id, output_dir)
        print("Output complete.")
    elif input("Output results to crawl directory? (y/n): ").lower() == 'y':
        print("Building output.")
        generate_crawl_dataframes(crawl_db_path, master_domain_db_path, parsed_db_path, crawl_id, output_dir)
        print("Output complete.'")
    else:
        print("Output aborted.")
