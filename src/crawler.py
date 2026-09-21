#Holds functions for running the crawler

#imports
import aiohttp
import asyncio
import re
import time
import json
import os
from datetime import datetime
from tqdm.asyncio import tqdm_asyncio
from bs4 import BeautifulSoup
from src.parse import StreamingRobotParser
from src.startup import checkpoint_crawl

#global vars
MAX_ROBOTS_BYTES = int(os.environ.get("REP_MAX_ROBOTS_BYTES", 8 * 1024 * 1024))
MAX_HTML_BYTES = int(os.environ.get("REP_MAX_HTML_BYTES", 2 * 1024 * 1024))
MAX_META_TAGS = int(os.environ.get("REP_MAX_META_TAGS", 200))
MAX_META_TAG_VALUE_BYTES = int(os.environ.get("REP_MAX_META_TAG_VALUE_BYTES", 8192))
MAX_META_TOTAL_BYTES = int(os.environ.get("REP_MAX_META_TOTAL_BYTES", 8192))
ROBOTS_DIRECTIVE_PATTERN = re.compile(
    rb"(?im)^[ \t]*(?:user-agent|allow|disallow|sitemap|crawl-delay|host|clean-param)[ \t]*:"
)

#sometimes the website responds to a robots.txt query, but redirects to an unrelated page
def redirect_check(response_url, chunk):
    if ROBOTS_DIRECTIVE_PATTERN.search(chunk):
        return True
    if response_url.path.lower().endswith("/robots.txt"):
        return all(
            not line.strip() or line.lstrip().startswith(b"#")
            for line in chunk.splitlines()
        )
    return False


#function to truncate meta values
def truncate_meta_values(value, limit):
    if value is None:
        return None
    text = str(value)
    if len(text.encode("utf-8")) <= limit:
        return text
    trimmed = text.encode("utf-8")[: limit - 3].decode("utf-8", errors="ignore")
    return trimmed + "..."


#function to parse meta tag rules
def parse_meta_value(value):
    raw = (value or "").strip()
    if not raw:
        return {
            "raw": "",
            "rules": [],
            "malformed": True,
            "warning": "Empty robots meta tag.",
            "unknown_tokens": [],
            "conflicting_rules": []
        }

    rule_parts = raw.split(",")
    rule_tokens = [token.strip().lower() for token in rule_parts if token.strip()]
    known_rules = {
        "index", "noindex", "follow", "nofollow"
    }

    malformed = (
        not rule_tokens
        or any(not token for token in rule_parts)
        or (len(rule_tokens) > 1 and "," not in raw)
        or any(re.search(r"\s", token) for token in rule_tokens)
    )
    unknown_tokens = [token for token in rule_tokens if token not in known_rules]
    conflicting_rules = []
    if "index" in rule_tokens and "noindex" in rule_tokens:
        conflicting_rules.append("index/noindex")
    if "follow" in rule_tokens and "nofollow" in rule_tokens:
        conflicting_rules.append("follow/nofollow")

    return {
        "raw": raw,
        "rules": rule_tokens,
        "malformed": malformed,
        "warning": (
            "Malformed robots meta-tag formatting detected."
            if malformed else (
                "Conflicting robots meta-tag rules detected."
                if conflicting_rules else None
            )
        ),
        "unknown_tokens": unknown_tokens,
        "conflicting_rules": conflicting_rules
    }

#function to grab domain IDs for the crawl
def get_domain_id(conn, master_conn, domain):
    master_cur = master_conn.cursor()
    cur = conn.cursor()
    #grab the master id key
    master_cur.execute(
        "SELECT master_domain_id FROM master_domain_names WHERE domain_name=?",
        (domain,)
    )
    master_domain_id = master_cur.fetchone()[0]

    cur.execute(
        "SELECT domain_id FROM domains WHERE master_domain_id=?",
        (master_domain_id,)
    )
    existing_domain = cur.fetchone()
    if existing_domain is not None:
        master_cur.close()
        cur.close()
        return existing_domain[0]

    #drop the master domain id into local domain table to get a local domain id
    cur.execute(
        "INSERT OR IGNORE INTO domains(master_domain_id) VALUES (?)",
        (master_domain_id,)
    )
    conn.commit()

    cur.execute(
        "SELECT domain_id FROM domains WHERE master_domain_id=?",
        (master_domain_id,)
    )

    domain_id = cur.fetchone()[0]
    master_cur.close()
    cur.close()
    return domain_id

#function to check what the content type of the domain is
def get_content_type(response):
    index_content_type = response.headers.get("Content-Type", "").lower()

    return index_content_type

#function to check if the domain we contacted is html, and if so check if it has meta robots tags
async def check_meta_tags(response):
    html_bytes = await response.content.read(MAX_HTML_BYTES + 1)
    index_truncated = len(html_bytes) > MAX_HTML_BYTES
    if index_truncated:
        html_bytes = html_bytes[:MAX_HTML_BYTES]
    html = html_bytes.decode(response.charset or "utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")

    meta_tags_search = soup.find_all("meta")
    if not meta_tags_search:
        return [], index_truncated, index_truncated

    meta_tags = []
    meta_tags_truncated = index_truncated
    retained_bytes = 0
    for ordinal, tag in enumerate(meta_tags_search, start=1):
        if len(meta_tags) >= MAX_META_TAGS:
            meta_tags_truncated = True
            break

        name = (tag.get("name") or "").strip()
        content = tag.get("content")
        if content is None:
            content = ""
        original_content = content
        content = truncate_meta_values(content, MAX_META_TAG_VALUE_BYTES)
        if content != original_content:
            meta_tags_truncated = True

        record = {
            "ordinal": ordinal,
            "name": name,
            "content": content,
            "is_robots_tag": name.lower() == "robots"
        }

        if name.lower() == "robots":
            parsed = parse_meta_value(content)
            record["robots_rules"] = parsed["rules"]
            record["robots_malformed"] = parsed["malformed"]
            record["robots_warning"] = parsed["warning"]
            record["robots_unknown_tokens"] = parsed["unknown_tokens"]
            record["robots_conflicting_rules"] = parsed["conflicting_rules"]
            record["robots_raw"] = parsed["raw"]

        record_bytes = len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
        if retained_bytes + record_bytes > MAX_META_TOTAL_BYTES:
            meta_tags_truncated = True
            break
        meta_tags.append(record)
        retained_bytes += record_bytes

    return meta_tags, index_truncated, meta_tags_truncated

#connect to domain for robots.txt with error handling
async def fetch_robot(session, domain, on_robot_chunk=None):
    protocols = ["https", "http"]
    last_exception = None
    index_content_type = None
    meta_tags = None
    index_truncated = None
    meta_tags_truncated = None
    index_response_status = None
    index_last_exception = None
    index_error = None
    index_exception = None

    #check index first, if html grab the meta tags
    #check https and http connections
    for protocol in protocols:
        url = f"{protocol}://{domain}"
        try:
            async with session.get(
                url,
                allow_redirects=True
            ) as response:
                #Server answered
                index_response_status = response.status
                index_content_type = get_content_type(response)
                if response.status == 200:
                    #Has index
                    #if html, check for meta tags
                    if "text/html" in index_content_type:
                        (
                            meta_tags,
                            index_truncated,
                            meta_tags_truncated,
                        ) = await check_meta_tags(response)
                    else:
                        index_truncated = False
                        meta_tags_truncated = False
                    break

        # HTTPS failed, try HTTP
        except (
            aiohttp.ClientConnectorCertificateError,
            aiohttp.ClientConnectorSSLError,
            aiohttp.ClientConnectorError,
            asyncio.TimeoutError,
        ) as e:
            index_error = str(e)
            continue

        except Exception as e:
            index_exception = str(e)
            break

    #check for robots.txt subdomain
    #check https and http connections
    for protocol in protocols:
        url = f"{protocol}://{domain}/robots.txt"
        start = time.time()
        try:
            async with session.get(
                url,
                allow_redirects=True
            ) as response:
                elapsed = (time.time() - start) * 1000

                #Server answered
                if response.status == 200:
                    #Has robots.txt
                    received_bytes = 0
                    truncated = False
                    robots_probe = bytearray()
                    robots_validated = False
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        if not robots_validated:
                            robots_probe.extend(chunk)
                            if redirect_check(response.url, robots_probe):
                                robots_validated = True
                                chunk = bytes(robots_probe)
                            elif len(robots_probe) < 64 * 1024:
                                continue
                            else:
                                return {
                                    "status_code": response.status,
                                    "result": "NOT_ROBOTS",
                                    "has_robots": 0,
                                    "protocol": protocol,
                                    "index_content_type": index_content_type,
                                    "index_truncated": index_truncated,
                                    "content": None,
                                    "time": elapsed,
                                    "exception": (
                                        "robots.txt response at "
                                        f"{response.url} did not contain a "
                                        "recognized robots directive"
                                    ),
                                    "meta_tags": meta_tags,
                                    "meta_tags_truncated": meta_tags_truncated,
                                    "index_response_status": index_response_status,
                                    "index_last_exception": index_last_exception,
                                    "index_error": index_error,
                                    "index_exception": index_exception
                                }
                        remaining = MAX_ROBOTS_BYTES - received_bytes
                        if remaining <= 0:
                            truncated = True
                            break
                        accepted = chunk[:remaining]
                        if on_robot_chunk and accepted:
                            await on_robot_chunk(accepted)
                        received_bytes += len(accepted)
                        if len(accepted) < len(chunk):
                            truncated = True
                            break
                    if not robots_validated:
                        if not redirect_check(
                            response.url, robots_probe
                        ):
                            return {
                                "status_code": response.status,
                                "result": "NOT_ROBOTS",
                                "has_robots": 0,
                                "protocol": protocol,
                                "index_content_type": index_content_type,
                                "index_truncated": index_truncated,
                                "content": None,
                                "time": elapsed,
                                "exception": (
                                    "robots.txt response at "
                                    f"{response.url} did not contain a "
                                    "recognized robots directive"
                                ),
                                "meta_tags": meta_tags,
                                "meta_tags_truncated": meta_tags_truncated,
                                "index_response_status": index_response_status,
                                "index_last_exception": index_last_exception,
                                "index_error": index_error,
                                "index_exception": index_exception
                            }
                    return {
                        "status_code": 200,
                        "result": "ROBOTS_TOO_LARGE" if truncated else "SUCCESS",
                        "has_robots": 1,
                        "protocol": protocol,
                        "index_content_type": index_content_type,
                        "index_truncated": index_truncated,
                        "content": None,
                        "time": elapsed,
                        "exception": (
                            f"robots.txt exceeds {MAX_ROBOTS_BYTES} bytes"
                            if truncated else None
                        ),
                        "robot_bytes": received_bytes,
                        "robots_truncated": truncated,
                        "meta_tags": meta_tags,
                        "meta_tags_truncated": meta_tags_truncated,
                        "index_response_status": index_response_status,
                        "index_last_exception": index_last_exception,
                        "index_error": index_error,
                        "index_exception": index_exception
                    }

                last_result = {
                    "status_code": response.status,
                    "result": f"HTTP_{response.status}",
                    "has_robots": 0,
                    "protocol": protocol,
                    "index_content_type": index_content_type,
                    "index_truncated": index_truncated,
                    "content": None,
                    "time": elapsed,
                    "exception": None,
                    "meta_tags": meta_tags,
                    "meta_tags_truncated": meta_tags_truncated,
                    "index_response_status": index_response_status,
                    "index_last_exception": index_last_exception,
                    "index_error": index_error,
                    "index_exception": index_exception
                }
                continue

        # HTTPS failed, try HTTP
        except (
            aiohttp.ClientConnectorCertificateError,
            aiohttp.ClientConnectorSSLError,
            aiohttp.ClientConnectorError,
            asyncio.TimeoutError,
        ) as e:
            last_exception = e
            continue

        # Unexpected exception
        except Exception as e:
            return {
                "status_code": None,
                "result": type(e).__name__,
                "has_robots": None,
                "protocol": protocol,
                "index_content_type": index_content_type,
                "index_truncated": index_truncated,
                "content": None,
                "time": None,
                "exception": str(e),
                "meta_tags": meta_tags,
                "meta_tags_truncated": meta_tags_truncated,
                "index_response_status": index_response_status,
                "index_last_exception": index_last_exception,
                "index_error": index_error,
                "index_exception": index_exception
            }

    if "last_result" in locals():
        return last_result

    # HTTPS and HTTP both failed
    failure_exception = None
    if last_exception is not None:
        failure_exception = str(last_exception).strip() or type(last_exception).__name__
    return {
        "status_code": None,
        "result": (
            "CONNECTION_TIMEOUT"
            if isinstance(last_exception, asyncio.TimeoutError)
            else "CONNECTION_FAILED"
        ),
        "has_robots": None,
        "protocol": None,
        "index_content_type": index_content_type,
        "index_truncated": index_truncated,
        "content": None,
        "time": None,
        "exception": failure_exception,
        "robot_bytes": 0,
        "robots_truncated": False,
        "meta_tags": meta_tags,
        "meta_tags_truncated": meta_tags_truncated,
        "index_response_status": index_response_status,
        "index_last_exception": index_last_exception,
        "index_error": index_error,
        "index_exception": index_exception
    }

#function for storing data for individual domains during crawl
async def process_domain(
    session, row, conn, master_conn, parsed_conn, crawl_id, db_lock
):
    domain = row.domain
    rank = row.Index
    async with db_lock:
        domain_id = get_domain_id(conn, master_conn, domain)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO fetches(crawl_id, domain_id, tranco_rank, timestamp, completed)
            VALUES (?, ?, ?, ?, 0)
        """, (crawl_id, domain_id, rank, datetime.now().isoformat()))
        fetch_id = cur.lastrowid
        conn.commit()
        cur.close()

    robot_parser = None

    #function to stream the robots.txt content to the parse
    async def consume_robot_chunk(chunk):
        nonlocal robot_parser
        async with db_lock:
            if robot_parser is None:
                robot_parser = StreamingRobotParser(fetch_id, parsed_conn)
            robot_parser.feed(chunk)

    result = await fetch_robot(session, domain, consume_robot_chunk)

    async with db_lock:
        cur = conn.cursor()
        cur.execute("""
            UPDATE fetches SET
                status_code = ?,
                result = ?,
                has_robots = ?,
                protocol = ?,
                index_content_type = ?,
                index_truncated = ?,
                response_time_ms = ?,
                exception = ?,
                index_response_status = ?,
                index_last_exception = ?,
                index_error = ?,
                index_exception = ?,
                meta_tags = ?,
                meta_tags_truncated = ?
            WHERE fetch_id = ?
        """, (
            result.get("status_code"),
            result.get("result"),
            result.get("has_robots"),
            result.get("protocol"),
            result.get("index_content_type"),
            result.get("index_truncated"),
            result.get("time"),
            result.get("exception"),
            result.get("index_response_status"),
            result.get("index_last_exception"),
            result.get("index_error"),
            result.get("index_exception"),
            json.dumps(result.get("meta_tags")) if result.get("meta_tags") else None,
            result.get("meta_tags_truncated"),
            fetch_id
        ))

        if robot_parser is not None:
            robot_truncated = (
                result.get("robots_truncated", False)
                or result.get("result") != "SUCCESS"
            )
            raw_hash, policy_hash, byte_count, _ = robot_parser.finish(
                robot_truncated
            )
            cur.execute("""
                UPDATE fetches
                SET
                    sha256 = ?,
                    bytes = ?,
                    policy_hash = ?,
                    truncated = ?,
                    completed = 1
                WHERE fetch_id = ?
            """, (
                raw_hash,
                byte_count,
                policy_hash,
                int(robot_truncated),
                fetch_id
            ))
        else:
            cur.execute(
                "UPDATE fetches SET completed=1 WHERE fetch_id=?",
                (fetch_id,)
            )

        conn.commit()
        cur.close()
        checkpoint_crawl(conn, crawl_id, rank)

#function for connections and running the crawler
async def run_crawl(
    df, USER_AGENT, TIMEOUT, CONCURRENCY, LIMIT_PER_HOST,
    conn, master_conn, parsed_conn, crawl_id
):
    timeout = aiohttp.ClientTimeout(
        total=TIMEOUT
    )

    #put limits on concurrency and connections
    connector = aiohttp.TCPConnector(
        limit = CONCURRENCY,
        limit_per_host = LIMIT_PER_HOST,
    )


    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers={
            "User-Agent":USER_AGENT
        }

    #now connect to each one
    ) as session:
        db_lock = asyncio.Lock()
        batch = []
        batch_size = max(1500, 1)
        for row in df:
            batch.append(process_domain(
                session, row, conn, master_conn, parsed_conn,
                crawl_id, db_lock
            ))
            if len(batch) >= batch_size:
                await tqdm_asyncio.gather(*batch)
                batch.clear()
        if batch:
            await tqdm_asyncio.gather(*batch)

#function to run main crawl
async def main_crawl_func(
        args,
        domains_df,
        USER_AGENT,
        TIMEOUT,
        CONCURRENCY,
        LIMIT_PER_HOST,
        conn,
        master_conn,
        parsed_conn,
        crawl_id,
        ):
    if args.autorun:
        print("Crawling domains.")
        print("This may take a while...")
        await run_crawl(domains_df,
                        USER_AGENT, 
                        TIMEOUT, 
                        CONCURRENCY, 
                        LIMIT_PER_HOST, 
                        conn, 
                        master_conn, 
                        parsed_conn,
                        crawl_id
                        )
        print("Crawl complete.")
    #manual execution
    elif input("Execute crawl? (y/n): ").lower() == 'y':
        print("Crawling domains.")
        print("This may take a while...")
        await run_crawl(domains_df,
                        USER_AGENT, 
                        TIMEOUT, 
                        CONCURRENCY, 
                        LIMIT_PER_HOST, 
                        conn, 
                        master_conn, 
                        parsed_conn,
                        crawl_id
                        )
        print("Crawl complete.")
    else:
        print("Crawl aborted.")
        return