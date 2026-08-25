#script to generate random samples from crawled and parsed data for manual validaiton

#imports
import numpy as np
import sqlite3
import pandas as pd
from pathlib import Path
import argparse

#set up args
def setup_arg_parser():
    parser = argparse.ArgumentParser(
        prog = "REP_Crawler Validation",
        description = "Generates repeatable samples of data from the REP_Crawler for validation",
        usage = "python validation.py [options]"
    )

    #arg list and options
    parser.add_argument("-s", "--single",
                        help = "Generate validation for a single crawl")
    parser.add_argument("-m", "--multiple",
                        help = "Generate validation for multiple crawls")
    parser.add_argument("-v", "--seedvalue",
                        help = "Pass a seed value if needed for random sampling (Default: New seed each validation)")
    parser.add_argument("-n", "--numsamples",
                        help = "Pass a limit if needed for random sampling (Default: 100)")

#main
def main():
    args = setup_arg_parser()

    print("REP Crawler Validation")

    #vars for sampling, change to replicate a random sample
    seed_value = args.seedvalue() if args.seedvalue() else np.random.randint(0, 1000000)
    num_samples = args.numsumples() if args.numsamples() else 100
    np.random.seed(seed_value)

    print(f"Random seed value: {seed_value}")
    print(f"Number of samples: {num_samples}")

    current_dir = Path.cwd()
    base_dir = current_dir / "data"

    num_crawls = 2 if args.multiple else 1

    crawl_ids = args.multiple if args.multiple else args.single


    match num_crawls:
        case 1:
            single_crawl_validation(seed_value, num_samples, base_dir, crawl_ids)
        case 2:
            multiple_crawl_validation(seed_value, num_samples, base_dir, crawl_ids)
        case _:
            print("Invalid option selected. Exiting.")
    return
    
def multiple_crawl_validation(seed_value, num_samples, base_dir, crawl_ids):

    #grab crawl ids for validation
    crawl_ids = [crawl_id.strip() for crawl_id in crawl_ids.split(",")]

    for crawl_id in crawl_ids:
        crawl_dir = base_dir / crawl_id
        crawl_db_path = crawl_dir / "metadata.sqlite"
        parsed_db_path = crawl_dir / "parsed.sqlite"

        print(f"Gathering samples from crawl database for crawl ID: {crawl_id}")
        crawl_db_df = pd.read_sql_query("SELECT * FROM fetches", sqlite3.connect(crawl_db_path))

        print(f"Gathering samples from parsed database for crawl ID: {crawl_id}")
        parsed_db_df = pd.read_sql_query("SELECT * FROM files", sqlite3.connect(parsed_db_path))

        print(f"Generating random samples for crawl ID: {crawl_id}")
        crawl_sample = crawl_db_df.sample(n=num_samples, random_state=seed_value)
        parsed_sample = parsed_db_df.sample(n=num_samples, random_state=seed_value)

        print(f"Saving samples to CSV files for crawl ID: {crawl_id}")
        crawl_sample_file_name = f"crawl_sample_{crawl_id}.csv"
        parsed_sample_file_name = f"parsed_sample_{crawl_id}.csv"
        crawl_sample.to_csv(crawl_dir / crawl_sample_file_name, index=False)
        parsed_sample.to_csv(crawl_dir / parsed_sample_file_name, index=False)

        print(f"Samples saved to: {crawl_dir / crawl_sample_file_name} and {crawl_dir / parsed_sample_file_name}")

def single_crawl_validation(seed_value, num_samples, base_dir, crawl_id):

    crawl_dir = base_dir / crawl_id
    crawl_db_path = crawl_dir / "metadata.sqlite"
    parsed_db_path = crawl_dir / "parsed.sqlite"

    print("Gathering samples from crawl database")
    crawl_db_df = pd.read_sql_query("SELECT * FROM fetches", sqlite3.connect(crawl_db_path))

    print("Gathering samples from parsed database")
    parsed_db_df = pd.read_sql_query("SELECT * FROM files", sqlite3.connect(parsed_db_path))

    print("Generating random samples")
    crawl_sample = crawl_db_df.sample(n=num_samples, random_state=seed_value)
    parsed_sample = parsed_db_df.sample(n=num_samples, random_state=seed_value)

    print("Saving samples to CSV files")
    crawl_sample_file_name = f"crawl_sample_{crawl_id}.csv"
    parsed_sample_file_name = f"parsed_sample_{crawl_id}.csv"
    crawl_sample.to_csv(crawl_dir / crawl_sample_file_name, index=False)
    parsed_sample.to_csv(crawl_dir / parsed_sample_file_name, index=False)

    print(f"Samples saved to: {crawl_dir / crawl_sample_file_name} and {crawl_dir / parsed_sample_file_name}")

if __name__ == "__main__":
    main()