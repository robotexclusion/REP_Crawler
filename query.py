#Contains functions to execute SQLite queries on gathered data

#imports
import sqlite3
import pandas as pd
from pathlib import Path

def main():
    #pathing vars
    current_dir = Path.cwd()
    base_dir = current_dir / "data"
    master_domain_db_path = base_dir /"domains.sqlite"

    #sql query to get all domains from the master domain database
    print(f"Connecting to master domain database at: {master_domain_db_path}")
    print("Fetching all domains from master domain database...")
    master_conn = sqlite3.connect(master_domain_db_path)
    master_cur = master_conn.cursor()
    master_cur.execute("SELECT * FROM domains")
    master_domains = pd.DataFrame(master_cur.fetchall(), columns=[description[0] for description in master_cur.description])

    print("Displaying top 10 results...")
    print(master_domains.head(10))

    print("save to file? (y/n)")
    choice = input().lower()
    if choice == "y":
        master_domains.to_csv("master_domains.csv", index=False)
        print("Results saved to master_domains.csv")

    print("Process complete. Exiting...")

if __name__ == "__main__":
    main()