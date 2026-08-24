#REP CRAWLER

#imports
import os
import sqlite3
import asyncio
import pandas as pd
from src.crawler import *
from src.startup import *
from src.parse import *
from src.output import *
from pathlib import Path
from datetime import datetime

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
    MAX_DOMAINS = 100

    #skip options from args
    if args.parse:
        skip_crawl = True
    if args.output:
        skip_crawl = True
        skip_parse = True

    print("Starting REP Crawler...")
    if args.autorun:
        print("Autorun enabled")
    print(f"User Agent: {USER_AGENT}")
    print(f"Concurrency: {CONCURRENCY}")
    print(f"Limit per host: {LIMIT_PER_HOST}")
    print(f"Timeout: {TIMEOUT} seconds")
    print(f"Max domains to crawl: {MAX_DOMAINS if MAX_DOMAINS else 'Unlimited'}")

    #Generate a unique crawl ID
    print("Generating crawl ID...")
    crawl_id = datetime.now().strftime("%Y%m%d%H%M")

    #Set vars for unique crawl path and sub-directories
    print(f"Setting up directories for crawl ID: {crawl_id}")
    current_dir = Path.cwd()
    base_dir = current_dir / "data"
    crawl_dir = base_dir / crawl_id
    robots_dir = crawl_dir / "robots"
    meta_dir = crawl_dir / "meta"
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
    robots_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    #Get TRANCO
    print("Downloading latest Tranco list...")
    TRANCO_FILE = download_latest_tranco_list(crawl_dir)

    #check if master database exists, if not create it
    print(f"Checking for master domain database at: {master_domain_db_path}")
    if not os.path.exists(master_domain_db_path):
        print(f"Master domain database not found at: {master_domain_db_path}. Creating...")
        create_domain_database(master_domain_db_path)
    else:
        print("Master domain database located.")
    master_conn = sqlite3.connect(master_domain_db_path)

    #create crawl db file
    print(f"Creating crawl database at: {crawl_db_path}")
    conn = create_crawl_database(crawl_db_path)

    #read the tranco list file and make a dataframe of the index and domain names
    domains_df = pd.read_csv(TRANCO_FILE, header=None)
    domains_df.columns = ['Index','domain']

    #if a limit was passed to MAX_DOMAINS, limit the number of domains crawled
    if MAX_DOMAINS:
        domains_df = domains_df.head(MAX_DOMAINS)

    #update main db file with names from the list
    print("Updating master domain database with new domains...")
    prime_main_domain_db(master_conn, domains_df)

    print("Ready")

    # Execute the web crawl
    if not args.skip_crawl:
        main_crawl_func(
            args,
            domains_df,
            USER_AGENT,
            TIMEOUT,
            CONCURRENCY,
            LIMIT_PER_HOST,
            conn,
            master_conn,
            crawl_id,
            robots_dir,
            crawl_dir
            )

    #parse the collected data, alinging and checking rules etc
    #autorun
    if args.autorun:
        print("Parsing data.")
        #Create the parsing db file
        parsed_conn = create_parser_database(parsed_db_path)

        #Create df of parsed files from the crawl db
        files_df = fetch_files_for_parsing(conn, master_domain_db_path)

        # create new dataframes for parsing, drop nas in filename and meta
        filtered_files = files_df.dropna(subset=['filename'])
        filtered_meta = files_df.dropna(subset=['meta_tags'])

        #send the dataframe through the parsing process
        parse_crawl_files(filtered_files, crawl_dir, parsed_conn)
        parse_crawl_meta_tags(filtered_meta, parsed_conn)

        print("Parsing complete.")

    #manual execution
    elif input("Execute parse? (y/n): ").lower() == 'y':
        print("Parsing data.")
        #Create the parsing db file
        parsed_conn = create_parser_database(parsed_db_path)

        #Create df of parsed files from the crawl db
        files_df = fetch_files_for_parsing(conn, master_domain_db_path)

        # create new dataframes for parsing, drop nas in filename and meta
        filtered_files = files_df.dropna(subset=['filename'])
        filtered_meta = files_df.dropna(subset=['meta_tags'])

        #send the dataframe through the parsing process
        parse_crawl_files(filtered_files, crawl_dir, parsed_conn)
        parse_crawl_meta_tags(filtered_meta, parsed_conn)

        print("Parsing complete.")
    else: 
        print("Parsing aborted.")
        return

    # Output the parsed data to dataframes
    #autorun
    if args.autorun:
        print("Building output.")
        generate_crawl_dataframes(conn, master_domain_db_path, parsed_db_path, crawl_id, crawl_dir)
        print("Output complete.")
    elif input("Output results to crawl directory? (y/n): ").lower == 'y':
        print("Building output.")
        generate_crawl_dataframes(conn, master_domain_db_path, parsed_db_path, crawl_id, crawl_dir)
        print("Output complete.'")
    else:
        print("Output aborted.")

    print("Process complete. Exiting...")
    return

#run the main function
if __name__ == "__main__":
    asyncio.run(main()) 