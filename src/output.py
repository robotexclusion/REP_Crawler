#Holds functions related to generating useable output from the crawled data

#imports
import pandas as pd
from pathlib import Path
import sqlite3

#function to create and output readable dataframes from the crawl
def generate_crawl_dataframes(
        crawl_db_path,
        master_domain_db_path, 
        parsed_db_path,
        crawl_id,
        crawl_dir,
        output_dir
        ):
    
    #filename vars
    crawl_df_filename = f"{crawl_id}_crawl_data"
    robots_df_filename = f"{crawl_id}_robots.txt_data"
    meta_df_filename = f"{crawl_id}_meta_tags_data"

    #attach databases
    conn = sqlite3.connect(crawl_db_path)
    cur = conn.cursor()
    cur.execute(f"ATTACH DATABASE '{master_domain_db_path}' AS master_domains")
    cur.execute(f"ATTACH DATABASE '{parsed_db_path}' AS parsed_data")

    print("Generating output data")
    #generate crawl dataframe
    print("Generating domain data")
    crawl_df = pd.read_sql_query(
        """
        SELECT * from fetches
        LEFT JOIN domains ON
        fetches.domain_id = domains.domain_id
        LEFT JOIN master_domains.master_domain_names ON
        domains.master_domain_id = master_domain_names.master_domain_id
        """,
        conn
    )

    #generate robots.txt dataframe
    print("Generating robots.txt file data")
    robots_df = pd.read_sql_query(
        """
        Select fetches.domain_id from fetches
        LEFT JOIN domains ON
        fetches.domain_id = domains.domain_id
        LEFT JOIN master_domains.master_domain_names ON
        domains.master_domain_id = master_domain_names.master_domain_id
        LEFT JOIN parsed_data.files ON
        fetches.fetch_id = files.fetch_id
        LEFT JOIN parsed_data.groups ON
        fetches.fetch_id = groups.fetch_id
        LEFT JOIN parsed_data.user_agents ON
        groups.group_id = user_agents.group_id
        LEFT JOIN parsed_data.directives ON
        groups.group_id = directives.group_id
        """,
        conn
    )

    #generate meta tags dataframe
    print("Generating meta tag data")
    meta_df = pd.read_sql_query(
        """
        Select fetches.domain_id FROM fetches
        LEFT JOIN domains ON
        fetches.domain_id = domains.domain_id
        LEFT JOIN master_domains.master_domain_names ON
        domains.master_domain_id = master_domain_names.master_domain_id
        LEFT JOIN parsed_data.meta_tags ON
        fetches.fetch_id = meta_tags.fetch_id
        """,
        conn
    )
    cur.close()

    #save to csv files in crawl directory
    print(f"Saving output data for crawl '{crawl_id}'")
    crawl_df.to_csv(output_dir / crawl_df_filename, index=False)
    robots_df.to_csv(output_dir / robots_df_filename, index=False)
    meta_df.to_csv(output_dir / meta_df_filename, index=False)
    print(f"Output data saved for crawl '{crawl_id}' in '{output_dir}'")

    return

def main_output_func(
        args,
        master_domain_db_path,
        parsed_db_path,
        crawl_dir,
        crawl_id,
        crawl_db_path,
        output_dir
    ):
    #autorun
    if args.autorun:
        print("Building output.")
        generate_crawl_dataframes(crawl_db_path, master_domain_db_path, parsed_db_path, crawl_id, crawl_dir, output_dir)
        print("Output complete.")
    elif input("Output results to crawl directory? (y/n): ").lower == 'y':
        print("Building output.")
        generate_crawl_dataframes(crawl_db_path, master_domain_db_path, parsed_db_path, crawl_id, crawl_dir, output_dir)
        print("Output complete.'")
    else:
        print("Output aborted.")
