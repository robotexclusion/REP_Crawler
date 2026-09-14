#Holds functions related to parsing the gathered data

import codecs
import hashlib
import re
import sqlite3

#global rules for parsing directives
#RFC 9309 directly permits allow and disallow, but infers others, these are common
RFC9309_RULES = {"allow", "disallow"}
EXTENSION_DIRECTIVES = {"sitemap", "crawl-delay", "host", "clean-param"}
PRODUCT_TOKEN_PATTERN = re.compile(r"^(?:\*|[-A-Za-z_]+)$")

#function to create parser database
def create_parser_database(parsed_db_path):
    connection = sqlite3.connect(parsed_db_path)
    connection.executescript("""

        CREATE TABLE IF NOT EXISTS files (
            fetch_id INTEGER PRIMARY KEY,
            sha256 TEXT,
            policy_hash TEXT,
            lines INTEGER,
            comments INTEGER,
            blank_lines INTEGER,
            parse_errors INTEGER,
            truncated INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS groups (
            group_id INTEGER PRIMARY KEY AUTOINCREMENT,
            fetch_id INTEGER NOT NULL,
            group_number INTEGER NOT NULL
        );
        
        CREATE TABLE IF NOT EXISTS user_agents (
            group_id INTEGER NOT NULL,
            line_number INTEGER NOT NULL,
            user_agent TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS directives (
            directive_id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            line_number INTEGER NOT NULL,
            directive TEXT NOT NULL,
            value TEXT NOT NULL,
            classification TEXT NOT NULL,
            raw TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS diagnostics (
            diagnostic_id INTEGER PRIMARY KEY AUTOINCREMENT,
            fetch_id INTEGER NOT NULL,
            line_number INTEGER,
            diagnostic_code TEXT NOT NULL,
            severity TEXT NOT NULL,
            raw TEXT,
            directive TEXT,
            value TEXT,
            message TEXT NOT NULL
        );
    """)
    try:
        connection.execute(
            "ALTER TABLE user_agents ADD COLUMN line_number INTEGER"
        )
    except sqlite3.OperationalError as error:
        if "duplicate column name" not in str(error):
            raise
    connection.execute(
        """
        UPDATE user_agents
        SET line_number = (
            SELECT MIN(diagnostics.line_number)
            FROM groups
            JOIN diagnostics ON diagnostics.fetch_id = groups.fetch_id
            WHERE groups.group_id = user_agents.group_id
                AND trim(lower(diagnostics.raw)) =
                    'user-agent: ' || trim(lower(user_agents.user_agent))
        )
        WHERE line_number IS NULL
        """
    )
    connection.commit()
    return connection

#function to normalize directives
def normalize_directive(value):
    return value.strip().lower()

#check the attached directive and determine if it is valid
def classify_directive(directive):
    if directive == "user-agent":
        return "USRAGT"
    if directive in RFC9309_RULES:
        return "RFC9309"
    if directive in EXTENSION_DIRECTIVES:
        return "EXTENSION"
    return "UNKNOWN"

#Class for streaming the robots.txt file without downloading
class StreamingRobotParser:

    #function to initialize parser
    def __init__(self, fetch_id, parsed_conn):
        self.fetch_id = fetch_id
        self.connection = parsed_conn
        self.cursor = parsed_conn.cursor()
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.raw_hasher = hashlib.sha256()
        self.policy_parts = []
        self.buffer = ""
        self.byte_count = 0
        self.line_count = 0
        self.comments = 0
        self.blank_lines = 0
        self.errors = 0
        self.group_number = 0
        self.current_group = None
        self.group_has_directive = False
        self.clear_previous_rows()

    #function to clear previous rows
    def clear_previous_rows(self):
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
        self.cursor.execute("DELETE FROM diagnostics WHERE fetch_id=?", (self.fetch_id,))
        self.cursor.execute("DELETE FROM files WHERE fetch_id=?", (self.fetch_id,))

    #function to record issues with robots lines
    def diagnostic(self, code, severity, raw, directive, value, message):
        self.errors += 1
        self.cursor.execute(
            """INSERT INTO diagnostics(
                fetch_id, line_number, diagnostic_code, severity, raw,
                directive, value, message
            ) VALUES (?,?,?,?,?,?,?,?)""",
            (
                self.fetch_id, self.line_count, code, severity, raw,
                directive, value, message
            )
        )

    #function to feed parser chunks, loading large files would cause RAM issues
    def feed(self, chunk):
        self.byte_count += len(chunk)
        self.raw_hasher.update(chunk)
        decoded = self.decoder.decode(chunk)
        for _ in range(decoded.count("\ufffd")):
            self.diagnostic(
                "INVALID_UTF8", "error", None, None, None,
                "Response contained invalid UTF-8 bytes."
            )
        self.buffer += decoded
        lines = self.buffer.split("\n")
        self.buffer = lines.pop()
        for line in lines:
            self.parse_line(line.rstrip("\r"))
        self.connection.commit()

    #function to parse lines, check for issues and do they meet RFC 9309 code
    def parse_line(self, raw):
        self.line_count += 1
        stripped = raw.strip()
        if not stripped:
            self.blank_lines += 1
            return
        if stripped.startswith("#"):
            self.comments += 1
            return
        if ":" not in stripped:
            self.diagnostic(
                "MISSING_COLON", "error", raw, None, None,
                "Non-comment line does not contain a directive separator."
            )
            return

        key, value = stripped.split(":", 1)
        directive = normalize_directive(key)
        value = value.split("#", 1)[0].strip()
        if any(
            ord(character) < 0x20 or ord(character) == 0x7F
            for character in raw
            if character not in "\t"
        ):
            self.diagnostic(
                "CONTROL_CHARACTER", "error", raw, directive, value,
                "Line contains a control character outside the permitted whitespace."
            )
        if not directive:
            self.diagnostic(
                "EMPTY_DIRECTIVE", "error", raw, directive, value,
                "Directive name is empty."
            )
            return
        if directive == "user-agent" and not value:
            self.diagnostic(
                "EMPTY_USER_AGENT", "error", raw, directive, value,
                "User-agent directive has no value."
            )
            return
        if directive == "user-agent":
            if not PRODUCT_TOKEN_PATTERN.fullmatch(value):
                self.diagnostic(
                    "INVALID_PRODUCT_TOKEN", "error", raw, directive, value,
                    "User-agent value is not a valid RFC 9309 product token."
                )
            if self.current_group is None or self.group_has_directive:
                self.group_number += 1
                self.cursor.execute(
                    "INSERT INTO groups(fetch_id, group_number) VALUES (?,?)",
                    (self.fetch_id, self.group_number)
                )
                self.current_group = self.cursor.lastrowid
                self.group_has_directive = False
            self.cursor.execute(
                "INSERT INTO user_agents(group_id, line_number, user_agent) "
                "VALUES (?,?,?)",
                (self.current_group, self.line_count, value)
            )
            self.policy_parts.append(
                f"G{self.group_number}|UA|{value.strip().lower()}"
            )
            return
        classification = classify_directive(directive)
        if self.current_group is None:
            self.diagnostic(
                "DIRECTIVE_BEFORE_GROUP", "warning", raw, directive, value,
                "Directive cannot be stored in a group before a User-agent directive."
            )
            return

        if classification == "UNKNOWN":
            self.diagnostic(
                "UNKNOWN_DIRECTIVE", "warning", raw, directive, value,
                "Directive is not in the recognized REP directive set."
            )
        if directive in RFC9309_RULES and value and not value.startswith("/"):
            self.diagnostic(
                "INVALID_PATH_PATTERN", "error", raw, directive, value,
                "RFC 9309 Allow and Disallow values must be empty or begin with '/'."
            )
        self.cursor.execute(
            """INSERT INTO directives(
                group_id, line_number, directive, value, classification, raw
            ) VALUES (?,?,?,?,?,?)""",
            (
                self.current_group, self.line_count, directive, value,
                classification, raw
            )
        )
        self.policy_parts.append(
            f"G{self.group_number}|D|{directive}|{value.strip()}"
        )
        self.group_has_directive = directive in RFC9309_RULES

    #finalize parsing, file related issues
    def finish(self, truncated=False):
        tail = self.decoder.decode(b"", final=True)
        if tail.count("\ufffd"):
            self.diagnostic(
                "INVALID_UTF8", "error", None, None, None,
                "Response ended with invalid UTF-8 bytes."
            )
        self.buffer += tail
        if self.buffer:
            self.parse_line(self.buffer.rstrip("\r"))
        if truncated:
            self.diagnostic(
                "TRUNCATED_RESPONSE", "error", None, None, None,
                "Response exceeded the configured safety limit."
            )
        raw_hash = self.raw_hasher.hexdigest()
        policy_hash = hashlib.sha256(
            "\n".join(self.policy_parts).encode("utf-8")
        ).hexdigest()
        self.cursor.execute(
            """INSERT OR REPLACE INTO files(
                fetch_id, sha256, policy_hash, lines, comments, blank_lines,
                parse_errors, truncated
            ) VALUES (?,?,?,?,?,?,?,?)""",
            (
                self.fetch_id, raw_hash, policy_hash, self.line_count,
                self.comments, self.blank_lines, self.errors, int(truncated)
            )
        )
        self.connection.commit()
        self.cursor.close()
        return raw_hash, policy_hash, self.byte_count, self.errors
