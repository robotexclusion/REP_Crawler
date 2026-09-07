#Holds functions for running the crawler

#imports
import aiohttp
import asyncio
import hashlib
import time
import json
import os
from datetime import datetime
from tqdm.asyncio import tqdm_asyncio
from bs4 import BeautifulSoup
from src.parse import StreamingRobotParser
from src.startup import checkpoint_crawl

MAX_ROBOTS_BYTES = int(os.environ.get("REP_MAX_ROBOTS_BYTES", 8 * 1024 * 1024))
MAX_HTML_BYTES = 2 * 1024 * 1024

#utf-8 decoding for text parsing
def sha256_text(text):

    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()

#functrion to save and name the captured robots files with unique identifiers
def save_robot_file(content, fetch_id, robots_dir, crawl_dir):

    #give the file a unique id based off the fetch number
    filename = f"{fetch_id:09d}.txt"

    #setr the path under the current crawl and write the file into the new text file
    path = robots_dir / filename
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    return str(path.relative_to(crawl_dir))

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

    #is html, check for robots tags
    meta_tags_search = soup.find_all(
        "meta",
        #uncomment to only pull robots tags
        # attrs={"name": lambda x: x and x.lower() in ["robots"]}
        #uncomment to not pull da couple of meta tags they are lengthy and not related to REP
        attrs={"name": lambda x: x and x.lower() not in ["viewport", "description", "author", "keywords"]}
    )

    #has tags, save them
    if meta_tags_search:
        meta_tags = [
            {
                "name": tag.get("name"),
                "content": tag.get("content")
            }
            for tag in meta_tags_search
        ]
        return meta_tags

    #no tags, return none
    return None

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
        "meta_tags": meta_tags,
        "meta_tags_response_status": meta_tags_response_status,
        "meta_tags_last_exception": meta_tags_last_exception,
        "meta_tags_error": meta_tags_error,
        "meta_tags_exception": meta_tags_exception
    }

#function for storing data for individual domains during crawl
async def process_domain(session, row, conn, master_conn, parsed_conn, crawl_id, robots_dir, crawl_dir):
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

    ####test output
    # print(f"Processing domain: {domain} with rank: {rank}")

    # Complete the checkpoint row only after network work is finished.
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
        file_hash, size = robot_parser.finish(
            result.get("robot_truncated", False)
            or result.get("result") != "SUCCESS"
        )
        cur.execute("""
            UPDATE fetches
            SET
                sha256 = ?,
                bytes = ?
            WHERE fetch_id = ?
        """, (
            file_hash,
            size,
            fetch_id
        ))
    cur.execute("UPDATE fetches SET completed=1 WHERE fetch_id=?", (fetch_id,))
    checkpoint_crawl(conn, crawl_id, rank)

#function for connections and running the crawler
async def run_crawl(
    df, USER_AGENT, TIMEOUT, CONCURRENCY, LIMIT_PER_HOST,
    conn, master_conn, parsed_conn, crawl_id, robots_dir, crawl_dir
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
                crawl_id, robots_dir, crawl_dir
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
        robots_dir,
        crawl_dir
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
                        crawl_id,
                        robots_dir,
                        crawl_dir
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
                        crawl_id,
                        robots_dir,
                        crawl_dir
                        )
        print("Crawl complete.")
    else:
        print("Crawl aborted.")
        return