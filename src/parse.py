#Holds functions for parsing the crawled data

#imports
import sqlite3
import json
from tqdm.auto import tqdm
from bs4 import BeautifulSoup

#function to create the parsing db file for after crawl
def create_parser_database(parsed_db_path):
    parsed_conn = sqlite3.connect(parsed_db_path)
    parsed_cur = parsed_conn.cursor()

    parsed_cur.execute("""
    CREATE TABLE IF NOT EXISTS files (
        fetch_id INTEGER PRIMARY KEY,
        filename TEXT,
        sha256 TEXT,
        lines INTEGER,
        comments INTEGER,
        blank_lines INTEGER,
        parse_errors INTEGER,
        FOREIGN KEY (fetch_id) REFERENCES fetches(fetch_id)
    )
    """)

    parsed_cur.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        group_id INTEGER PRIMARY KEY AUTOINCREMENT,
        fetch_id INTEGER,
        group_number INTEGER,
        FOREIGN KEY (fetch_id) REFERENCES fetches(fetch_id)
    )
    """)

    parsed_cur.execute("""
    CREATE TABLE IF NOT EXISTS user_agents (
        group_id INTEGER,
        user_agent TEXT,
        FOREIGN KEY (group_id) REFERENCES groups(group_id)
    )
    """)

    parsed_cur.execute("""
    CREATE TABLE IF NOT EXISTS directives (
        directive_id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER,
        line_number INTEGER,
        directive TEXT,
        value TEXT,
        classification TEXT,
        raw TEXT,
        FOREIGN KEY (group_id) REFERENCES groups(group_id)
    )
    """)

    parsed_cur.execute("""
    CREATE TABLE IF NOT EXISTS raw_lines (
        fetch_id INTEGER,
        line_number INTEGER,
        text TEXT,
        FOREIGN KEY (fetch_id) REFERENCES fetches(fetch_id)
    )
    """)

    parsed_cur.execute("""
    CREATE TABLE IF NOT EXISTS meta_tags (
        meta_tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
        fetch_id INTEGER,
        meta_tag_name TEXT,
        meta_tag_content TEXT,
        FOREIGN KEY (fetch_id) REFERENCES fetches(fetch_id)
    )
    """)

    parsed_conn.commit()
    print(f"Created parsed database at: {parsed_db_path}")
    return parsed_conn

#function to clean the directive line
def normalize_directive(value):
    return value.strip().lower()

#function to chekc the directive against the standard list to see if it might be malformed or unusual
def classify_directive(directive, standard_directives):
    if directive == "user-agent":
        return "USER_AGENT"
    if directive in standard_directives:
        return "STANDARD"
    return "UNKNOWN"

#function to go through the saved robots file and split it out
def parse_robot_file(
    fetch_id,
    filename,
    sha256,
    crawl_dir,
    parsed_conn
):
    cur = parsed_conn.cursor()
    #var for standard dirctives, to see if something is unusual in the files
    standard_directives = {
        "user-agent",
        "disallow",
        "allow",
        "sitemap",
        "crawl-delay",
        "host",
        "clean-param"
    }

    #grab the file
    path = crawl_dir / filename

    #read length of file
    with open(
        path,
        "r",
        encoding="utf-8",
        errors="ignore"
    ) as f:
        lines = f.readlines()

    #open a record in files for this files and insert metadata and file length
    group_number = 0
    current_group = None
    comments = 0
    blank = 0
    errors = 0

    cur.execute("""
    INSERT OR REPLACE INTO files
    VALUES (?,?,?,?,?,?,?)
    """,
    (
        fetch_id,
        filename,
        sha256,
        len(lines),
        0,
        0,
        0
    ))

    #strip the lines for parsing, but keep originals if needed for reference
    for index, line in enumerate(lines, start=1):
        raw = line.rstrip("\n")
        cur.execute("""
        INSERT INTO raw_lines
        VALUES (?,?,?)
        """,
        (
            fetch_id,
            index,
            raw
        ))
        stripped = raw.strip()
        if not stripped:
            blank += 1
            continue
        if stripped.startswith("#"):
            comments += 1
            continue

        # Parse directive
        if ":" not in stripped:
            errors += 1
            continue
        key, value = stripped.split(
            ":",
            1
        )
        directive = normalize_directive(key)
        value = value.strip()



        # New group
        if directive == "user-agent":
            if current_group is None:
                group_number += 1
                cur.execute("""
                INSERT INTO groups(
                    fetch_id,
                    group_number
                )
                VALUES (?,?)
                """,
                (
                    fetch_id,
                    group_number
                ))

                current_group = cur.lastrowid
            cur.execute("""
            INSERT INTO user_agents
            VALUES (?,?)
            """,
            (
                current_group,
                value
            ))
        else:
            if current_group is None:
                errors += 1
                continue
            cur.execute("""
            INSERT INTO directives(
                group_id,
                line_number,
                directive,
                value,
                classification,
                raw
            )
            VALUES (?,?,?,?,?,?)
            """,
            (
                current_group,
                index,
                directive,
                value,
                classify_directive(directive, standard_directives),
                raw
            ))



    #Done going through file, update the metadata in files
    cur.execute("""
    UPDATE files
    SET
        comments=?,
        blank_lines=?,
        parse_errors=?
    WHERE fetch_id=?
    """,
    (
        comments,
        blank,
        errors,
        fetch_id
    ))
    parsed_conn.commit()
    cur.close()

#go through each row and see if they have a robots, if so parse it and add to the parsed db
def parse_crawl_files(df):
    for row in tqdm(
        df.itertuples(),
        total=len(df)
    ):
        parse_robot_file(
            row.fetch_id,
            row.filename,
            row.sha256
        )

#function to go through the meta tags and then add them into the parsed set
def parse_crawl_meta_tags(df, parsed_conn):
    cur = parsed_conn.cursor()
    for row in tqdm(
        df.itertuples(),
        total=len(df)
    ):
        meta_tags = json.loads(row.meta_tags)
        for meta_tag in meta_tags:
            cur.execute("""
            INSERT INTO meta_tags(
                fetch_id,
                meta_tag_name,
                meta_tag_content
            )
            VALUES (?,?,?)
            """,
            (
                row.fetch_id,
                meta_tag.get("name"),
                meta_tag.get("content")
            ))
    cur.close()
