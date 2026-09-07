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

MAX_ROBOTS_BYTES = int(os.environ.get("REP_MAX_ROBOTS_BYTES", 8 * 1024 * 1024))
MAX_HTML_BYTES = int(os.environ.get("REP_MAX_HTML_BYTES", 2 * 1024 * 1024))
MAX_META_TAGS = int(os.environ.get("REP_MAX_META_TAGS", 200))
MAX_META_TAG_VALUE_BYTES = int(os.environ.get("REP_MAX_META_TAG_VALUE_BYTES", 8192))
MAX_META_TOTAL_BYTES = int(os.environ.get("REP_MAX_META_TOTAL_BYTES", 8192))


def _truncate_meta_value(value, limit):
    if value is None:
        return None
    text = str(value)
    if len(text.encode("utf-8")) <= limit:
        return text
    trimmed = text.encode("utf-8")[: limit - 3].decode("utf-8", errors="ignore")
    return trimmed + "..."


def _parse_meta_robots_value(value):
    raw = (value or "").strip()
    if not raw:
        return {
            "raw": "",
            "rules": [],
            "malformed": False,
            "warning": "Empty robots meta tag."
        }

    normalized = re.sub(r"\s+", " ", raw).strip()
    rule_tokens = [token.strip().lower() for token in re.split(r"[,\s]+", normalized) if token.strip()]
    known_rules = {
        "index", "noindex", "follow", "nofollow", "all", "none",
        "noarchive", "nosnippet", "notranslate", "noimageindex",
        "max-snippet", "max-image-preview", "max-video-preview",
        "unavailable_after"
    }

    malformed = False
    bad_tokens = []
    for token in rule_tokens:
        if not token:
            continue
        if token.startswith("max-"):
            if token.split("-", 2)[-1].startswith("snippet"):
                continue
        if token.startswith("max-"):
            if token.endswith(("snippet", "image-preview", "video-preview")):
                continue
        if token.startswith("unavailable_after"):
            continue
        if token not in known_rules:
            bad_tokens.append(token)

    if not rule_tokens or bad_tokens:
        malformed = True

    if "index" in rule_tokens and "noindex" in rule_tokens:
        malformed = True
    if "follow" in rule_tokens and "nofollow" in rule_tokens:
        malformed = True

    return {
        "raw": raw,
        "rules": rule_tokens,
        "malformed": malformed,
        "warning": (
            "Malformed robots meta-tag rules detected."
            if malformed else None
        ),
        "unknown_tokens": bad_tokens
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
    content_type = response.headers.get("Content-Type", "").lower()

    return content_type

#function to check if the domain we contacted is html, and if so check if it has meta robots tags
async def check_meta_tags(response):
    html_bytes = await response.content.read(MAX_HTML_BYTES + 1)
    if len(html_bytes) > MAX_HTML_BYTES:
        html_bytes = html_bytes[:MAX_HTML_BYTES]
    html = html_bytes.decode(response.charset or "utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")

    meta_tags_search = soup.find_all("meta")
    if not meta_tags_search:
        return None

    meta_tags = []
    retained_bytes = 0
    for ordinal, tag in enumerate(meta_tags_search, start=1):
        if len(meta_tags) >= MAX_META_TAGS:
            break

        name = (tag.get("name") or "").strip()
        content = tag.get("content")
        if content is None:
            content = ""
        content = _truncate_meta_value(content, MAX_META_TAG_VALUE_BYTES)

        record = {
            "ordinal": ordinal,
            "name": name,
            "content": content,
            "is_robots_tag": name.lower() == "robots"
        }

        if name.lower() == "robots":
            parsed = _parse_meta_robots_value(content)
            record["robots_rules"] = parsed["rules"]
            record["robots_malformed"] = parsed["malformed"]
            record["robots_warning"] = parsed["warning"]
            record["robots_unknown_tokens"] = parsed["unknown_tokens"]
            record["robots_raw"] = parsed["raw"]

        record_bytes = len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
        if retained_bytes + record_bytes > MAX_META_TOTAL_BYTES:
            break
        meta_tags.append(record)
        retained_bytes += record_bytes

    return meta_tags

#connect to domain for robots.txt with error handling
async def fetch_robot(session, domain, on_robot_chunk=None):
    protocols = ["https", "http"]
    last_exception = None
    content_type = None
    meta_tags = None
    meta_tags_response_status = None
    meta_tags_last_exception = None
    meta_tags_error = None
    meta_tags_exception = None

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
                meta_tags_response_status = response.status
                if response.status == 200:
                    #Has index
                    content_type = get_content_type(response)
                    #if html, check for meta tags
                    if "text/html" in content_type:
                        meta_tags = await check_meta_tags(response)
                    break

        # HTTPS failed, try HTTP
        except (
            aiohttp.ClientConnectorCertificateError,
            aiohttp.ClientConnectorSSLError,
            aiohttp.ClientConnectorError,
            asyncio.TimeoutError,
        ) as e:
            meta_tags_error = str(e)
            continue

        except Exception as e:
            meta_tags_exception = str(e)
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
                content_type = get_content_type(response)
                if response.status == 200:
                    #Has robots.txt
                    received_bytes = 0
                    truncated = False
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        remaining = MAX_ROBOTS_BYTES - received_bytes
                        if remaining <= 0:
                            truncated = True
                            break
                        accepted = chunk[:remaining]
                        if on_robot_chunk and accepted:
                            on_robot_chunk(accepted)
                        received_bytes += len(accepted)
                        if len(accepted) < len(chunk):
                            truncated = True
                            break
                    return {
                        "status_code": 200,
                        "result": "ROBOTS_TOO_LARGE" if truncated else "SUCCESS",
                        "protocol": protocol,
                        "content_type": content_type,
                        "content": None,
                        "time": elapsed,
                        "exception": (
                            f"robots.txt exceeds {MAX_ROBOTS_BYTES} bytes"
                            if truncated else None
                        ),
                        "robot_bytes": received_bytes,
                        "robot_truncated": truncated,
                        "meta_tags": meta_tags,
                        "meta_tags_response_status": meta_tags_response_status,
                        "meta_tags_last_exception": meta_tags_last_exception,
                        "meta_tags_error": meta_tags_error,
                        "meta_tags_exception": meta_tags_exception
                    }

                # Try the other protocol before classifying a non-success response.
                content_type = get_content_type(response)
                if "text/html" in content_type:
                    meta_tags = await check_meta_tags(response)
                last_result = {
                    "status_code": response.status,
                    "result": f"HTTP_{response.status}",
                    "protocol": protocol,
                    "content_type": content_type,
                    "content": None,
                    "time": elapsed,
                    "exception": None,
                    "meta_tags": meta_tags,
                    "meta_tags_response_status": meta_tags_response_status,
                    "meta_tags_last_exception": meta_tags_last_exception,
                    "meta_tags_error": meta_tags_error,
                    "meta_tags_exception": meta_tags_exception
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
                "protocol": protocol,
                "content_type": content_type,
                "content": None,
                "time": None,
                "exception": str(e),
                "meta_tags": meta_tags,
                "meta_tags_response_status": meta_tags_response_status,
                "meta_tags_last_exception": meta_tags_last_exception,
                "meta_tags_error": meta_tags_error,
                "meta_tags_exception": meta_tags_exception
            }

    if "last_result" in locals():
        return last_result

    # HTTPS and HTTP both failed
    return {
        "status_code": None,
        "result": "CONNECTION_FAILED",
        "protocol": None,
        "content_type": content_type,
        "content": None,
        "time": None,
        "exception": str(last_exception) if last_exception else None,
        "robot_bytes": 0,
        "robot_truncated": False,
        "meta_tags": meta_tags,
        "meta_tags_response_status": meta_tags_response_status,
        "meta_tags_last_exception": meta_tags_last_exception,
        "meta_tags_error": meta_tags_error,
        "meta_tags_exception": meta_tags_exception
    }

#function for storing data for individual domains during crawl
async def process_domain(session, row, conn, master_conn, parsed_conn, crawl_id):
    domain = row.domain
    rank = row.Index
    domain_id = get_domain_id(conn, master_conn, domain)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO fetches(crawl_id, domain_id, tranco_rank, timestamp, completed)
        VALUES (?, ?, ?, ?, 0)
    """, (crawl_id, domain_id, rank, datetime.now().isoformat()))
    fetch_id = cur.lastrowid
    conn.commit()

    robot_parser = None

    def consume_robot_chunk(chunk):
        nonlocal robot_parser
        if robot_parser is None:
            robot_parser = StreamingRobotParser(fetch_id, parsed_conn)
        robot_parser.feed(chunk)

    result = await fetch_robot(session, domain, consume_robot_chunk)

    cur.execute("""
        UPDATE fetches SET
            status_code = ?,
            result = ?,
            protocol = ?,
            content_type = ?,
            response_time_ms = ?,
            exception = ?,
            meta_tags_response_status = ?,
            meta_tags_last_exception = ?,
            meta_tags_error = ?,
            meta_tags_exception = ?,
            meta_tags = ?
        WHERE fetch_id = ?
    """, (
        result.get("status_code"),
        result.get("result"),
        result.get("protocol"),
        result.get("content_type"),
        result.get("time"),
        result.get("exception"),
        result.get("meta_tags_response_status"),
        result.get("meta_tags_last_exception"),
        result.get("meta_tags_error"),
        result.get("meta_tags_exception"),
        json.dumps(result.get("meta_tags")) if result.get("meta_tags") else None,
        fetch_id
    ))

    if robot_parser is not None:
        raw_hash, policy_hash, byte_count, _ = robot_parser.finish(
            result.get("robot_truncated", False)
            or result.get("result") != "SUCCESS"
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
            int(result.get("robot_truncated", False)),
            fetch_id
        ))
    else:
        cur.execute(
            "UPDATE fetches SET completed=1 WHERE fetch_id=?",
            (fetch_id,)
        )

    conn.commit()
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
        batch = []
        batch_size = max(CONCURRENCY * 2, 1)
        for row in df:
            batch.append(process_domain(
                session, row, conn, master_conn, parsed_conn,
                crawl_id
            ))
            if len(batch) >= batch_size:
                await tqdm_asyncio.gather(*batch)
                batch.clear()
        if batch:
            await tqdm_asyncio.gather(*batch)

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