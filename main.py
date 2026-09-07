#REP CRAWLER

#imports
import os
import sqlite3
import asyncio
from src.crawler import main_crawl_func
from src.startup import (
    completed_ranks,
    create_crawl_database,
    create_domain_database,
    discard_incomplete_fetches,
    download_latest_tranco_list,
    finish_crawl,
    iter_pending_tranco_domains,
    iter_tranco_domains,
    prime_main_domain_db,
    setup_arg_parser,
    start_crawl,
)
from src.parse import create_parser_database
from src.output import dump_master_domains_csv, main_output_func
from src.r2 import upload_crawl
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace

#main function
async def main():
    #parse args
    args = setup_arg_parser()

    #set vars
    USER_AGENT = "REP_Research_Crawler"
    #Concurrency and timeout options to not overload ISP
    CONCURRENCY = 600
    LIMIT_PER_HOST = 1
    TIMEOUT = 15
    # optional test size, set to None for unlimited/full list
    MAX_DOMAINS = args.max_domains or None

    #skip options from args
    skip_crawl = False
    no_upload = False

    if args.resume:
        crawl_id = args.crawlid
    elif args.output:
        skip_crawl = True
        crawl_id = args.crawlid

    if args.noupload:
        no_upload = True
    
    print("Starting REP Crawler...")
    if args.autorun:
        print("Autorun enabled")
    print(f"User Agent: {USER_AGENT}")
    print(f"Concurrency: {CONCURRENCY}")
    print(f"Limit per host: {LIMIT_PER_HOST}")
    print(f"Timeout: {TIMEOUT} seconds")
    print(f"Max domains to crawl: {MAX_DOMAINS if MAX_DOMAINS else 'Unlimited'}")

    #Generate a unique crawl ID
    if not skip_crawl:
        print("Generating crawl ID...")
        crawl_id = datetime.now().strftime("%Y%m%d%H%M")

    #Set vars for unique crawl path and sub-directories
    print(f"Setting up directories for crawl ID: {crawl_id}")
    current_dir = Path.cwd()
    base_dir = current_dir / "data"
    crawl_dir = base_dir / crawl_id
    output_dir = crawl_dir / "output"

    #Paths for the db files, one for raw and another for parsed, 
    #as well as a path var for the main domains db
    master_domain_db_path = base_dir /"domains.sqlite"
    crawl_db_path = crawl_dir / "metadata.sqlite"
    parsed_db_path = crawl_dir / "parsed.sqlite"

    #Make folders to for sub directories if they don't exist
    print("Creating directory structure...")
    base_dir.mkdir(parents=True, exist_ok=True)
    crawl_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not skip_crawl and not args.resume:
        #Get TRANCO
        print("Downloading latest Tranco list...")
        TRANCO_FILE = download_latest_tranco_list(crawl_dir)
    elif args.resume:
        snapshots = sorted(crawl_dir.glob("tranco_list_*.csv"))
        if not snapshots:
            raise FileNotFoundError(
                f"No saved Tranco snapshot found in {crawl_dir}"
            )
        TRANCO_FILE = snapshots[-1]

    #check if master database exists, if not create it
    print(f"Checking for master domain database at: {master_domain_db_path}")
    if not os.path.exists(master_domain_db_path):
        print(f"Master domain database not found at: {master_domain_db_path}. Creating...")
        create_domain_database(master_domain_db_path)
    else:
        print("Master domain database located.")
    master_conn = sqlite3.connect(master_domain_db_path)
    conn = None

    if not skip_crawl:
        #create crawl db file
        print(f"Creating crawl database at: {crawl_db_path}")
        conn = create_crawl_database(crawl_db_path)
        start_crawl(conn, crawl_id)

        #update main db file with names from the list
        print("Updating master domain database with new domains...")
        if not args.resume:
            prime_main_domain_db(
                master_conn,
                iter_tranco_domains(TRANCO_FILE, MAX_DOMAINS)
            )

    parsed_conn = create_parser_database(parsed_db_path)
    if args.resume:
        discarded = discard_incomplete_fetches(conn, parsed_conn, crawl_id)
        if discarded:
            print(f"Discarded {discarded} incomplete fetch checkpoints.")

    print("Ready")

    # Execute the web crawl
    if not skip_crawl:
        completed = completed_ranks(conn, crawl_id)
        await main_crawl_func(
            args,
            (
                SimpleNamespace(Index=rank, domain=domain)
                for rank, domain in iter_pending_tranco_domains(
                    TRANCO_FILE, completed, MAX_DOMAINS
                )
            ),
            USER_AGENT,
            TIMEOUT,
            CONCURRENCY,
            LIMIT_PER_HOST,
            conn,
            master_conn,
            parsed_conn,
            crawl_id
            )
        finish_crawl(conn, crawl_id)
        conn.close()
        conn = None

    master_conn.close()
    master_conn = None
    parsed_conn.close()
    parsed_conn = None

    # Output the parsed data to dataframes
    main_output_func(
        args,
        master_domain_db_path,
        parsed_db_path,
        crawl_id,
        crawl_db_path,
        output_dir
    )

    master_domains_csv_path = base_dir / "master_domains.csv"
    dump_master_domains_csv(master_domain_db_path, master_domains_csv_path)

    #pack up the data and export
    if not no_upload:
        upload_crawl(crawl_id, base_dir)


    print("Process complete. Exiting...")
    return

#run the main function
def cli():
    asyncio.run(main())


if __name__ == "__main__":
    cli()