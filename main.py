#REP CRAWLER

#imports
import os
import sqlite3
import aiohttp
import asyncio
import hashlib
import time
import json
import re
import requests
import pandas as pd
import numpy as np
from src.crawler import *
from src.startup import *
from src.parse import *
from pathlib import Path
from datetime import datetime
from tqdm.asyncio import tqdm_asyncio
from tqdm.auto import tqdm
from bs4 import BeautifulSoup

#main function
async def main():

    #set vars
    USER_AGENT = "REP_Research_Crawler"
    #Concurrency and timeout options to not overload ISP
    CONCURRENCY = 750
    LIMIT_PER_HOST = 1
    TIMEOUT = 15
    # optional test size, set to None for unlimited/full list
    MAX_DOMAINS = 100
    #Generate a unique crawl ID
    crawl_id = datetime.now().strftime("%Y%m%d%H%M")
    #Set vars for unique crawl path and sub-directories
    base_dir = Path("/data")
    crawl_dir = base_dir / crawl_id
    robots_dir = crawl_dir / "robots"
    meta_dir = crawl_dir / "meta"
    output_dir = crawl_dir / "output"
    #Paths for the db files, one for raw and another for parsed, 
    #as well as a path var for the main domains db
    master_domain_db_path = "domains.sqlite"
    crawl_db_path = crawl_dir / "metadata.sqlite"
    parsed_db_path = crawl_dir / "parsed.sqlite"


    #Make folders to for sub directories if they don't exist
    crawl_dir.mkdir(parents=True, exist_ok=True)
    robots_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)


    tranco_email = os.environ.get("tranco_email")
    tranco_api_token = os.environ.get("tranco_api_token")
    tranco_api_base = "https://tranco-list.eu/api"




    #Get TRANCO
    TRANCO_FILE = download_latest_tranco_list()

    #check if master database exists, if not create it
    if not os.path.exists(master_domain_db_path):
        print(f"Master domain database not found at: {master_domain_db_path}. Creating...")
        create_domain_database(master_domain_db_path)
    master_conn = sqlite3.connect(master_domain_db_path)
    master_cur = master_conn.cursor()

    #create crawl db file
    conn = create_crawl_database(crawl_db_path)
    cur = conn.cursor()

    # Attach the master domain database to the crawl connection
    cur.execute(f"ATTACH DATABASE '{master_domain_db_path}' AS master_domains")

    #read the tranco list file and make a dataframe of the index and domain names
    domains_df = pd.read_csv(TRANCO_FILE, header=None)
    domains_df.columns = ['Index','domain']

    #if a limit was passed to MAX_DOMAINS, limit the number of domains crawled
    if MAX_DOMAINS:
        domains_df = domains_df.head(MAX_DOMAINS)

    #update main db file with names from the list
    prime_main_domain_db(master_conn, domains_df)

    print("Ready")
    input("Execute crawl? (y/n): ")
    if input().lower() == 'y':
        await run_crawl(domains_df)
    else:
        print("Crawl aborted.")
        return

    print("Execute parse? (y/n): ")
    if input().lower() == 'y':
        #Create the parsing db file
        parsed_conn = create_parser_database(parsed_db_path)
        parsed_cur = parsed_conn.cursor()

        #create new dataframes for parsing, drop nas in filename and meta
        filtered_files = fetches_df.dropna(subset=['filename'])
        filtered_meta = fetches_df.dropna(subset=['meta_tags'])

        #send the dataframe through the parsing process
        #parse_crawl_files(filtered_files)
        #parse_crawl_meta_tags(filtered_meta)
    else: 
        print("Parse aborted.")
        return

#run the main function
if __name__ == "__main__":
    asyncio.run(main()) 