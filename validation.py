#script to generate random samples from crawled and parsed data for manual validaiton

#imports
import numpy as np
import sqlite3
import pandas as pd
from pathlib import Path

#main
def main():
    #vars for sampling, change to replicate a random sample
    seed_value = np.random.randint(0, 1000000)
    num_samples = 100
    np.random.seed(seed_value)

    current_dir = Path.cwd()
    base_dir = current_dir / "data"

    print("REP Crawler Validation")
    print("Type of validation to perform (1 = single crawl, 2 = multiple crawls): ")
    validation_type = input().strip()
    match validation_type:
        case "1":
            single_crawl_validation(seed_value, num_samples, base_dir)
        case "2":
            multiple_crawl_validation(seed_value, num_samples, base_dir)
        case _:
            print("Invalid option selected. Exiting.")
    return
    
def multiple_crawl_validation(seed_value, num_samples, base_dir):
    print(f"Random seed value: {seed_value}")
    print(f"Number of samples: {num_samples}")

    #grab crawl ids for validation
    print("Crawl IDs to validate (comma-separated list of numeric identifiers of the crawl directories): ")
    crawl_ids_input = input().strip()
    crawl_ids = [crawl_id.strip() for crawl_id in crawl_ids_input.split(",")]

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

def single_crawl_validation(seed_value, num_samples, base_dir):
    print(f"Random seed value: {seed_value}")
    print(f"Number of samples: {num_samples}")

    #grab crawl id for validation
    print("Crawl ID to validate (numeric identifier of the crawl directory): ")
    crawl_id = input().strip()
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