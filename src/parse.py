#Holds functions for parsing the crawled data

#imports
import sqlite3
import json
import codecs
import hashlib
import pandas as pd
from tqdm.auto import tqdm
from bs4 import BeautifulSoup

#function to create the parsing db file for after crawl
def create_parser_database(parsed_db_path):
    parsed_conn = sqlite3.connect(parsed_db_path)
    cur = parsed_conn.cursor()

    cur.execute("""
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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        group_id INTEGER PRIMARY KEY AUTOINCREMENT,
        fetch_id INTEGER,
        group_number INTEGER,
        FOREIGN KEY (fetch_id) REFERENCES fetches(fetch_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_agents (
        group_id INTEGER,
        user_agent TEXT,
        FOREIGN KEY (group_id) REFERENCES groups(group_id)
    )
    """)

    cur.execute("""
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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS raw_lines (
        fetch_id INTEGER,
        line_number INTEGER,
        text TEXT,
        FOREIGN KEY (fetch_id) REFERENCES fetches(fetch_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS meta_tags (
        meta_tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
        fetch_id INTEGER,
        meta_tag_name TEXT,
        meta_tag_content TEXT,
        FOREIGN KEY (fetch_id) REFERENCES fetches(fetch_id)
    )
    """)

    parsed_conn.commit()
    cur.close()
    print(f"Created parsed database at: {parsed_db_path}")
    return parsed_conn

#function to fetch files form the crawl_db to return a datafram for parsing
def fetch_files_for_parsing(crawl_db_path, master_domain_db_path):
    conn = sqlite3.connect(crawl_db_path)
    cur = conn.cursor()
    cur.execute(f"ATTACH DATABASE '{master_domain_db_path}' AS master_domains")
    cur.execute("""
    SELECT *
    FROM fetches
    LEFT JOIN domains ON fetches.domain_id = domains.domain_id
    LEFT JOIN master_domains.master_domain_names ON 
    domains.master_domain_id = master_domain_names.master_domain_id
    """)
    files_df = pd.DataFrame(cur.fetchall(), columns=[description[0] for description in cur.description])
    cur.execute("DETACH DATABASE master_domains")
    cur.close()
    return files_df

#function to clean the directive line
def normalize_directive(value):
    return value.strip().lower()

#function to chekc the directive against the standard list to see if it might be malformed or unusual
def classify_directive(directive, standard_directives):
    if directive == "user-agent":
        return "USRAGT"
    if directive in standard_directives:
        return "STD"
    return "UNK"

class StreamingRobotParser:
    """Parse robots.txt incrementally while retaining diagnostic lines."""

    def __init__(self, fetch_id, parsed_conn):
        self.fetch_id = fetch_id
        self.connection = parsed_conn
        self.cursor = parsed_conn.cursor()
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.hasher = hashlib.sha256()
        self.buffer = ""
        self.byte_count = 0
        self.line_count = 0
        self.comments = 0
        self.blank_lines = 0
        self.errors = 0
        self.group_number = 0
        self.current_group = None
        self.group_has_directive = False
        self.standard_directives = {
            "user-agent", "disallow", "allow", "sitemap",
            "crawl-delay", "host", "clean-param"
        }
        self._clear_previous_rows()

    def _clear_previous_rows(self):
        self.cursor.execute(
            "DELETE FROM user_agents WHERE group_id IN "
            "(SELECT group_id FROM groups WHERE fetch_id=?)",
            (self.fetch_id,)
        )
        self.cursor.execute(
            "DELETE FROM directives WHERE group_id IN "
            "(SELECT group_id FROM groups WHERE fetch_id=?)",
            (self.fetch_id,)
        )
        self.cursor.execute("DELETE FROM groups WHERE fetch_id=?", (self.fetch_id,))
        self.cursor.execute("DELETE FROM raw_lines WHERE fetch_id=?", (self.fetch_id,))
        self.cursor.execute(
            "INSERT OR REPLACE INTO files "
            "(fetch_id, filename, sha256, lines, comments, blank_lines, parse_errors) "
            "VALUES (?, NULL, NULL, 0, 0, 0, 0)",
            (self.fetch_id,)
        )

    def feed(self, chunk):
        self.byte_count += len(chunk)
        self.hasher.update(chunk)
        decoded = self.decoder.decode(chunk)
        self.errors += decoded.count("\ufffd")
        self.buffer += decoded
        lines = self.buffer.split("\n")
        self.buffer = lines.pop()
        for line in lines:
            self._parse_line(line.rstrip("\r"))

    def _parse_line(self, raw):
        self.line_count += 1
        self.cursor.execute(
            "INSERT INTO raw_lines(fetch_id, line_number, text) VALUES (?,?,?)",
            (self.fetch_id, self.line_count, raw)
        )
        stripped = raw.strip()
        if not stripped:
            self.blank_lines += 1
            return
        if stripped.startswith("#"):
            self.comments += 1
            return
        if ":" not in stripped:
            self.errors += 1
            return
        key, value = stripped.split(":", 1)
        directive = normalize_directive(key)
        value = value.split("#", 1)[0].strip()
        if not directive or (directive == "user-agent" and not value):
            self.errors += 1
            return
        if directive == "user-agent":
            if self.current_group is None or self.group_has_directive:
                self.group_number += 1
                self.cursor.execute(
                    "INSERT INTO groups(fetch_id, group_number) VALUES (?,?)",
                    (self.fetch_id, self.group_number)
                )
                self.current_group = self.cursor.lastrowid
                self.group_has_directive = False
            self.cursor.execute(
                "INSERT INTO user_agents(group_id, user_agent) VALUES (?,?)",
                (self.current_group, value)
            )
            return
        if self.current_group is None:
            self.errors += 1
            return
        self.cursor.execute(
            """INSERT INTO directives(
                group_id, line_number, directive, value, classification, raw
            ) VALUES (?,?,?,?,?,?)""",
            (
                self.current_group,
                self.line_count,
                directive,
                value,
                classify_directive(directive, self.standard_directives),
                raw
            )
        )
        self.group_has_directive = True

    def finish(self, truncated=False):
        tail = self.decoder.decode(b"", final=True)
        self.errors += tail.count("\ufffd")
        self.buffer += tail
        if self.buffer:
            self._parse_line(self.buffer.rstrip("\r"))
            self.buffer = ""
        if truncated:
            self.errors += 1
        self.cursor.execute(
            """UPDATE files SET sha256=?, lines=?, comments=?, blank_lines=?, parse_errors=?
            WHERE fetch_id=?""",
            (
                self.hasher.hexdigest(),
                self.line_count,
                self.comments,
                self.blank_lines,
                self.errors,
                self.fetch_id
            )
        )
        self.connection.commit()
        self.cursor.close()
        return self.hasher.hexdigest(), self.byte_count

#function to go through the saved robots file and split it out
def parse_robot_content(
    fetch_id,
    content,
    sha256,
    parsed_conn
):
    parser = StreamingRobotParser(fetch_id, parsed_conn)
    parser.feed(content.encode("utf-8"))
    return parser.finish()

    # Legacy implementation retained below for reference by old databases.
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

    lines = content.splitlines(keepends=True)

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
        None,
        sha256,
        len(lines),
        0,
        0,
        0
    ))

    cur.execute("""
        DELETE FROM user_agents
        WHERE group_id IN (SELECT group_id FROM groups WHERE fetch_id=?)
    """, (fetch_id,))
    cur.execute("""
        DELETE FROM directives
        WHERE group_id IN (SELECT group_id FROM groups WHERE fetch_id=?)
    """, (fetch_id,))
    cur.execute("DELETE FROM groups WHERE fetch_id=?", (fetch_id,))
    cur.execute("DELETE FROM raw_lines WHERE fetch_id=?", (fetch_id,))

    # Strip lines for parsing while retaining originals for reference.
    group_has_directive = False
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
        value = value.split("#", 1)[0].strip()

        # New group
        if directive == "user-agent":
            if current_group is None or group_has_directive:
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
                group_has_directive = False
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
            group_has_directive = True

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

def parse_robot_file(fetch_id, filename, sha256, crawl_dir, parsed_conn):
    path = crawl_dir / filename
    parser = StreamingRobotParser(fetch_id, parsed_conn)
    with open(path, "r", encoding="utf-8", errors="ignore") as source:
        for chunk in iter(lambda: source.read(64 * 1024), ""):
            parser.feed(chunk.encode("utf-8"))
    return parser.finish()

#go through each row and see if they have a robots, if so parse it and add to the parsed db
def parse_crawl_files(df, crawl_dir, parsed_conn):
    for row in tqdm(
        df.itertuples(),
        total=len(df)
    ):
        parse_robot_file(
            row.fetch_id,
            row.filename,
            row.sha256,
            crawl_dir,
            parsed_conn
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
    parsed_conn.commit()
    cur.close()

def main_parse_func(
        args,
        parsed_db_path,
        master_domain_db_path,
        crawl_dir,
        crawl_db_path
    ):
    #autorun
    if args.autorun:
            print("Parsing data.")
            #Create the parsing db file
            parsed_conn = create_parser_database(parsed_db_path)
    
            #Create df of parsed files from the crawl db
            files_df = fetch_files_for_parsing(crawl_db_path, master_domain_db_path)
    
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
        files_df = fetch_files_for_parsing(crawl_db_path, master_domain_db_path)

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