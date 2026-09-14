#Holds functions related to generating output from the crawled data

#imports
import csv
import json
from pathlib import Path
import sqlite3


def write_query_csv(connection, query, output_path):
    cursor = connection.execute(query)
    with open(output_path, "w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow([column[0] for column in cursor.description])
        while rows := cursor.fetchmany(10000):
            writer.writerows(rows)


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

    #Stream each result directly to csv instead of loading it in pandas
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

    print("Generating robots.txt file data")
    robots_query = """
        SELECT
        fetches.domain_id,
        fetches.fetch_id,
        domains.master_domain_id,
        master_domains.master_domain_names.domain_name,
        parsed_data.files.parse_errors,
        parsed_data.groups.group_id,
        parsed_data.user_agents.user_agent,
        parsed_data.directives.directive_id,
        parsed_data.directives.directive,
        parsed_data.directives.value,
        parsed_data.directives.classification
        FROM fetches
        LEFT JOIN domains ON fetches.domain_id = domains.domain_id
        LEFT JOIN parsed_data.files ON fetches.fetch_id = parsed_data.files.fetch_id
        LEFT JOIN parsed_data.groups ON fetches.fetch_id = parsed_data.groups.fetch_id
        LEFT JOIN parsed_data.user_agents ON parsed_data.groups.group_id = parsed_data.user_agents.group_id
        LEFT JOIN parsed_data.directives ON parsed_data.groups.group_id = parsed_data.directives.group_id
        LEFT JOIN master_domains.master_domain_names ON
            domains.master_domain_id = master_domains.master_domain_names.master_domain_id
        ORDER BY fetches.fetch_id, parsed_data.groups.group_number,
            parsed_data.user_agents.line_number,
            parsed_data.directives.line_number
    """
    write_query_csv(conn, robots_query, output_dir / robots_df_filename)

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

    print("Generating meta tag data")
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
            "index_truncated",
            "meta_tags_truncated",
            "meta_tag_name",
            "meta_tag_content",
            "meta_tag_ordinal",
            "is_robots_tag",
            "robots_rules",
            "robots_malformed",
            "robots_warning",
            "robots_unknown_tokens",
            "robots_raw",
        ])
        for (
            fetch_id,
            domain_id,
            master_domain_id,
            domain_name,
            index_truncated,
            meta_tags_truncated,
            meta_tags_json,
        ) in conn.execute(meta_rows_query):
            try:
                meta_tags = json.loads(meta_tags_json)
            except (TypeError, ValueError):
                continue
            if not isinstance(meta_tags, list):
                continue
            for ordinal, tag in enumerate(meta_tags, start=1):
                if not isinstance(tag, dict):
                    continue
                writer.writerow([
                    fetch_id,
                    domain_id,
                    master_domain_id,
                    domain_name,
                    index_truncated,
                    meta_tags_truncated,
                    tag.get("name"),
                    tag.get("content"),
                    ordinal,
                    tag.get("is_robots_tag", False),
                    json.dumps(tag.get("robots_rules", [])),
                    tag.get("robots_malformed", False),
                    tag.get("robots_warning"),
                    json.dumps(tag.get("robots_unknown_tokens", [])),
                    tag.get("robots_raw"),
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
