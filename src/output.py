#Holds functions related to generating useable output from the crawled data

#imports
import sqlite3
import pandas as pd
from pathlib import Path

#function to create and output readable dataaframs from the crawl
def generate_crawl_dataframes(conn, master_domain_db_path, parsed_db_path):
    cur = conn.cursor()

    #attach databases
    cur.execute(f"ATTACH DATABASE '{master_domain_db_path}' AS master_domains")
    cur.execute(f"ATTACH DATABASE '{parsed_db_path}' AS parsed_data")

    #generate crawl dataframe
    


    #generate robots.txt dataframe


    #generate meta tags dataframe


    #save to csv files in crawl directory