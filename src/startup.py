#Holds functions for setting up the crawler

#imports
import os
import argparse
import requests
import sqlite3
import csv
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()

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
    parser.add_argument("-u", "--noupload",
                        action="store_true",
                        help = "Don't upload the crawl data to the connected R2 bucket")
    parser.add_argument("--resume",
                        action="store_true",
                        help="Resume an interrupted crawl using its saved Tranco snapshot.")
    parser.add_argument("--max-domains",
                        type=int,
                        default=100,
                        help="Maximum domains to process; use 0 for the full list.")

    #parse cli args
    args = parser.parse_args()

    if (args.parse or args.output or args.resume) and not args.crawlid:
        raise ValueError(
            "A crawl ID is required when using --parse, --output, or --resume."
        )

    if args.resume and (args.parse or args.output):
        raise ValueError("--resume cannot be combined with --parse or --output.")

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

def iter_tranco_domains(tranco_file, max_domains=None):
    """Yield Tranco rows without loading the complete list into memory."""
    with open(tranco_file, "r", encoding="utf-8", newline="") as source:
        reader = csv.reader(source)
        for row_number, row in enumerate(reader, start=1):
            if len(row) < 2:
                continue
            if max_domains is not None and row_number > max_domains:
                break
            yield row_number, row[1].strip()

def iter_pending_tranco_domains(tranco_file, completed, max_domains=None):
    for rank, domain in iter_tranco_domains(tranco_file, max_domains):
        if rank not in completed:
            yield rank, domain

#Create db file for domains if it doesnt exist already
def create_domain_database(master_domain_db_path):
    conn = sqlite3.connect(master_domain_db_path)
    cur = conn.cursor()

    #Table to store domain name info
    cur.execute("""
    CREATE TABLE IF NOT EXISTS master_domain_names (
        master_domain_id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain_name TEXT NOT NULL UNIQUE
        )
        """)

    cur.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_master_domain_names_domain
    ON master_domain_names(domain_name)
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
        finished TEXT,
        status TEXT DEFAULT 'created',
        last_rank INTEGER,
        completed_domains INTEGER DEFAULT 0,
        checkpointed_at TEXT
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
        completed INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (crawl_id) REFERENCES crawl(crawl_id),
        FOREIGN KEY (domain_id) REFERENCES domains(domain_id)
    )
    """)

    for table, column, definition in (
        ("crawl", "status", "TEXT DEFAULT 'created'"),
        ("crawl", "last_rank", "INTEGER"),
        ("crawl", "completed_domains", "INTEGER DEFAULT 0"),
        ("crawl", "checkpointed_at", "TEXT"),
        ("fetches", "completed", "INTEGER NOT NULL DEFAULT 0"),
    ):
        columns = {row[1] for row in cur.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    #commit and return
    conn.commit()
    cur.close()
    print(f"Created crawl database at: {crawl_db_path}")
    return conn

def start_crawl(conn, crawl_id):
    conn.execute(
        "INSERT OR IGNORE INTO crawl(crawl_id, started, status) VALUES (?, datetime('now'), 'created')",
        (crawl_id,)
    )
    conn.execute(
        "UPDATE crawl SET status='running', finished=NULL WHERE crawl_id=?",
        (crawl_id,)
    )
    conn.commit()

def finish_crawl(conn, crawl_id):
    conn.execute(
        "UPDATE crawl SET finished=datetime('now'), status='complete' WHERE crawl_id=?",
        (crawl_id,)
    )
    conn.commit()

def checkpoint_crawl(conn, crawl_id, rank):
    conn.execute(
        """UPDATE crawl SET last_rank=?, completed_domains=completed_domains + 1,
        checkpointed_at=datetime('now') WHERE crawl_id=?""",
        (rank, crawl_id)
    )
    conn.commit()

def completed_ranks(conn, crawl_id):
    return {
        rank for (rank,) in conn.execute(
            "SELECT tranco_rank FROM fetches WHERE crawl_id=? AND completed=1",
            (crawl_id,)
        )
    }

def discard_incomplete_fetches(conn, parsed_conn, crawl_id):
    fetch_ids = [
        fetch_id for (fetch_id,) in conn.execute(
            "SELECT fetch_id FROM fetches WHERE crawl_id=? AND completed=0",
            (crawl_id,)
        )
    ]
    for fetch_id in fetch_ids:
        for table, column in (
            ("meta_tags", "fetch_id"),
            ("raw_lines", "fetch_id"),
            ("files", "fetch_id"),
        ):
            parsed_conn.execute(
                f"DELETE FROM {table} WHERE {column}=?",
                (fetch_id,)
            )
        parsed_conn.execute(
            "DELETE FROM user_agents WHERE group_id IN "
            "(SELECT group_id FROM groups WHERE fetch_id=?)",
            (fetch_id,)
        )
        parsed_conn.execute(
            "DELETE FROM directives WHERE group_id IN "
            "(SELECT group_id FROM groups WHERE fetch_id=?)",
            (fetch_id,)
        )
        parsed_conn.execute("DELETE FROM groups WHERE fetch_id=?", (fetch_id,))
    parsed_conn.commit()
    conn.execute(
        "DELETE FROM fetches WHERE crawl_id=? AND completed=0",
        (crawl_id,)
    )
    conn.commit()
    return len(fetch_ids)

#Function to update the main domain name db file before running
def prime_main_domain_db(master_conn, df):
    rows = ((domain_rank, domain) for domain_rank, domain in df)
    cur = master_conn.cursor()
    cur.executemany(
        "INSERT OR IGNORE INTO master_domain_names(domain_name) VALUES (?)",
        ((domain,) for _, domain in rows)
    )
    master_conn.commit()
    cur.close()