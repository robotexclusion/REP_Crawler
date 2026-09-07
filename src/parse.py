"""Streaming REP parsing and internal staging tables."""

import codecs
import hashlib
import sqlite3

STANDARD_DIRECTIVES = {
    "user-agent", "allow", "disallow", "sitemap", "crawl-delay",
    "host", "clean-param"
}


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
    connection.commit()
    return connection


def normalize_directive(value):
    return value.strip().lower()


def classify_directive(directive):
    if directive == "user-agent":
        return "USRAGT"
    if directive in STANDARD_DIRECTIVES:
        return "STD"
    return "UNK"


class StreamingRobotParser:
    """Parse robots.txt chunks without retaining the response body."""

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
        self.cursor.execute("DELETE FROM diagnostics WHERE fetch_id=?", (self.fetch_id,))
        self.cursor.execute("DELETE FROM files WHERE fetch_id=?", (self.fetch_id,))

    def _diagnostic(self, code, severity, raw, directive, value, message):
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

    def feed(self, chunk):
        self.byte_count += len(chunk)
        self.raw_hasher.update(chunk)
        decoded = self.decoder.decode(chunk)
        for _ in range(decoded.count("\ufffd")):
            self._diagnostic(
                "INVALID_UTF8", "error", None, None, None,
                "Response contained invalid UTF-8 bytes."
            )
        self.buffer += decoded
        lines = self.buffer.split("\n")
        self.buffer = lines.pop()
        for line in lines:
            self._parse_line(line.rstrip("\r"))
        self.connection.commit()

    def _parse_line(self, raw):
        self.line_count += 1
        stripped = raw.strip()
        if not stripped:
            self.blank_lines += 1
            return
        if stripped.startswith("#"):
            self.comments += 1
            return
        if ":" not in stripped:
            self._diagnostic(
                "MISSING_COLON", "error", raw, None, None,
                "Non-comment line does not contain a directive separator."
            )
            return

        key, value = stripped.split(":", 1)
        directive = normalize_directive(key)
        value = value.split("#", 1)[0].strip()
        if not directive:
            self._diagnostic(
                "EMPTY_DIRECTIVE", "error", raw, directive, value,
                "Directive name is empty."
            )
            return
        if directive == "user-agent" and not value:
            self._diagnostic(
                "EMPTY_USER_AGENT", "error", raw, directive, value,
                "User-agent directive has no value."
            )
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
            self.policy_parts.append(
                f"G{self.group_number}|UA|{value.strip().lower()}"
            )
            return
        if self.current_group is None:
            self._diagnostic(
                "DIRECTIVE_BEFORE_GROUP", "error", raw, directive, value,
                "Directive appears before a User-agent directive."
            )
            return

        classification = classify_directive(directive)
        if classification == "UNK":
            self._diagnostic(
                "UNKNOWN_DIRECTIVE", "warning", raw, directive, value,
                "Directive is not in the recognized REP directive set."
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
        self.group_has_directive = True

    def finish(self, truncated=False):
        tail = self.decoder.decode(b"", final=True)
        if tail.count("\ufffd"):
            self._diagnostic(
                "INVALID_UTF8", "error", None, None, None,
                "Response ended with invalid UTF-8 bytes."
            )
        self.buffer += tail
        if self.buffer:
            self._parse_line(self.buffer.rstrip("\r"))
        if truncated:
            self._diagnostic(
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
