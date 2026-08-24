#Holds functions related to generating useable output from the crawled data

#imports
import sqlite3
import pandas as pd
from pathlib import Path

#function to create and output readable dataaframs from the crawl
def generate_crawl_dataframes(
        conn, 
        master_domain_db_path, 
        parsed_db_path,
        crawl_id,
        crawl_dir
        ):
    
    #filename vars
    crawl_df_filename = f"'{crawl_id}'_crawl_data"
    robots_df_filename = f"'{crawl_id}'_robots.txt_data"
    meta_df_filename = f"'{crawl_id}'_meta_tags_data"

    #attach databases
    cur = conn.cursor()
    cur.execute(f"ATTACH DATABASE '{master_domain_db_path}' AS master_domains")
    cur.execute(f"ATTACH DATABASE '{parsed_db_path}' AS parsed_data")

    print("Generating output data")
    #generate crawl dataframe
    print("Generating domain data")
    crawl_df = pd.read_sql_query(
        """
        SELECT * from fetches,
        master_domain_names.domain_name
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
        Select * from files
        """,
        conn
    )

    #generate meta tags dataframe
    print("Generating meta tag data")
    meta_df = pd.read_sql_query(
        """
        Select * from meta_tags
        """,
        conn
    )
    cur.close()

    #save to csv files in crawl directory
    print(f"Saving output data for crawl '{crawl_id}'")
    crawl_df.to_csv(crawl_dir / crawl_df_filename, index=False)
    robots_df.to_csv(crawl_dir / robots_df_filename, index=False)
    meta_df.to_csv(crawl_dir / meta_df_filename, index=False)
    print(f"Output data saved for crawl '{crawl_id}' in '{crawl_dir}'")

    return
