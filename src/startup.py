#Holds functions for setting up the crawler

#imports
import os
import argparse
import requests
import sqlite3

#function for setting up parsing arguments
def setup_arg_parser():
    parser = argparse.ArgumentParser(
        prog = "REP_Crawler", 
        description = "Crawls domains on the TRANCO list for Robots Exclusion Protocol indicators.",
        usage = "python main.py [options]"
        )

    #arg list and options
    parser.add_argument("-a", "--autorun",
                        action = "store_true",
                        help = "Run the full main script without input."
                        )
    parser.add_argument("-p", "--parse",
                        action = "store_true",
                        help = "Skip to the parsing step for a provided crawl id."
                        )
    parser.add_argument("-o", "--output",
                        action = "store_true",
                        help = "Skip to the output step for a provided crawl id")
    parser.add_argument("-c", "--crawlid",
                        type = str,
                        help = "crawl_id to use when skipping crawl step")

    #parse cli args
    args = parser.parse_args()

    if (args.parse or args.output) and not args.crawlid:
        raise ValueError(
            "A crawl ID is required when using --parse or --output."
        )

    return args

#function for getting the latest Tranco list
def get_latest_tranco_list():

    tranco_email = os.environ.get("TRANCO_EMAIL")
    tranco_api_token = os.environ.get("TRANCO_API_TOKEN")
    tranco_api_base = "https://tranco-list.eu/api"

    response = requests.get(
        f"{tranco_api_base}/lists/date/latest",
        auth=(tranco_email, tranco_api_token),
        timeout=30
    )
    response.raise_for_status()
    data = response.json()
    #throw an error if not available
    if not data.get("available"):
        raise RuntimeError(
            f"Tranco list {data.get('list_id')} "
            "is not currently available."
        )
    return data

#grab the latest Tranco list, download and save in the crawl dir
def download_latest_tranco_list(crawl_dir):
    tranco_info = get_latest_tranco_list()
    tranco_list_id = tranco_info["list_id"]
    tranco_download_url = tranco_info["download"]
    tranco_file_name = "tranco_list_" + tranco_info["created_on"] + ".csv"
    tranco_file = crawl_dir / tranco_file_name

    response = requests.get(
        tranco_download_url,
        timeout=120
    )
    response.raise_for_status()

    with open(tranco_file, "wb") as f:
        f.write(response.content)


    print(f"Saved Tranco list to: {tranco_file}")
    return tranco_file

#Create db file for domains if it doesnt exist already
def create_domain_database(master_domain_db_path):
    conn = sqlite3.connect(master_domain_db_path)
    cur = conn.cursor()

    #Table to store domain name info
    cur.execute("""
    CREATE TABLE IF NOT EXISTS master_domain_names (
        master_domain_id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain_name TEXT
        )
        """)

    #commit and return
    conn.commit()
    cur.close()
    print(f"Created master domain database at: {master_domain_db_path}")
    return conn

#Create the db file for the crawl
def create_crawl_database(crawl_db_path):
    conn = sqlite3.connect(crawl_db_path)
    cur = conn.cursor()

    #Table to store metadata for the crawl
    cur.execute("""
    CREATE TABLE IF NOT EXISTS crawl (
        crawl_id TEXT PRIMARY KEY,
        started TEXT,
        finished TEXT
    )
    """)

    #table to create keys and store domain names
    cur.execute("""
    CREATE TABLE IF NOT EXISTS domains (
        domain_id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_domain_id INTEGER,
        FOREIGN KEY (master_domain_id) REFERENCES master_domain_names(master_domain_id)
    )
    """)

    #table to store information related to each information fetch
    cur.execute("""
    CREATE TABLE IF NOT EXISTS fetches (
        fetch_id INTEGER PRIMARY KEY AUTOINCREMENT,
        crawl_id TEXT,
        domain_id INTEGER,
        tranco_rank INTEGER,
        timestamp TEXT,
        status_code INTEGER,
        result TEXT,
        protocol TEXT,
        response_time_ms REAL,
        filename TEXT,
        bytes INTEGER,
        sha256 TEXT,
        exception TEXT,
        content_type TEXT,
        meta_tags TEXT,
        meta_tags_response_status TEXT,
        meta_tags_last_exception TEXT,
        meta_tags_error TEXT,
        meta_tags_exception TEXT,
        FOREIGN KEY (crawl_id) REFERENCES crawl(crawl_id),
        FOREIGN KEY (domain_id) REFERENCES domains(domain_id)
    )
    """)

    #commit and return
    conn.commit()
    cur.close()
    print(f"Created crawl database at: {crawl_db_path}")
    return conn

#Function to update the main domain name db file before running
def prime_main_domain_db(master_conn, df):
    for row in df.itertuples():
        domain = row.domain
        cur = master_conn.cursor()
        cur.execute("INSERT OR REPLACE INTO master_domain_names(domain_name) VALUES (?)",
            (domain,)
        )
        master_conn.commit()
        cur.close()
    print(f"Primed master domain database with {len(df)} domains.")