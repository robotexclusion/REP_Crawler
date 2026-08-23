#Holds functions for running the crawler

#imports
import aiohttp
import asyncio
import hashlib
import time
import json
from datetime import datetime
from tqdm.asyncio import tqdm_asyncio
from bs4 import BeautifulSoup

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
    html = await response.text(errors="ignore")
    soup = BeautifulSoup(html, "html.parser")

    #is html, check for robots tags
    meta_tags_search = soup.find_all(
        "meta"
        #uncomment to only pull robots tags
        # attrs={"name": lambda x: x and x.lower() in ["robots"]}
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
async def fetch_robot(session, domain):
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
                if response.status == 200:
                    #Has robots.txt
                    text = await response.text(errors="ignore")
                    return {
                        "status_code": 200,
                        "result": "SUCCESS",
                        "protocol": protocol,
                        "content_type": content_type,
                        "content": text,
                        "time": elapsed,
                        "exception": None,
                        "meta_tags": meta_tags,
                        "meta_tags_response_status": meta_tags_response_status,
                        "meta_tags_last_exception": meta_tags_last_exception,
                        "meta_tags_error": meta_tags_error,
                        "meta_tags_exception": meta_tags_exception
                    }

                # does not have robots.txt, but responded
                #get content type
                content_type = get_content_type(response)
                #if html, check for meta tags
                if "text/html" in content_type:
                    meta_tags = await check_meta_tags(response)

                return {
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
async def process_domain(session, row, conn, master_conn, crawl_id, robots_dir, crawl_dir):
    domain = row.domain
    rank = row.Index
    result = await fetch_robot(session, domain)
    domain_id = get_domain_id(conn, master_conn, domain)
    cur = conn.cursor()
    master_cur = master_conn.cursor()

    ####test output
    print(f"Processing domain: {domain} with rank: {rank}")

    # Insert initial metadata row
    cur.execute("""
        INSERT INTO fetches (
            crawl_id,
            domain_id,
            tranco_rank,
            timestamp,
            status_code,
            result,
            protocol,
            content_type,
            response_time_ms,
            filename,
            bytes,
            sha256,
            exception,
            meta_tags_response_status,
            meta_tags_last_exception,
            meta_tags_error,
            meta_tags_exception
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        crawl_id,
        domain_id,
        rank,
        datetime.now().isoformat(),
        result.get("status_code"),
        result.get("result"),
        result.get("protocol"),
        result.get("content_type"),
        result.get("time"),
        None,
        None,
        None,
        result.get("exception"),
        result.get("meta_tags_response_status"),
        result.get("meta_tags_last_exception"),
        result.get("meta_tags_error"),
        result.get("meta_tags_exception")
    ))
    fetch_id = cur.lastrowid


    #if we got any meta tag results, save them
    if result.get("meta_tags"):
        cur.execute("""
        UPDATE fetches
        SET
            meta_tags = ?
        WHERE fetch_id = ?
        """, (
            json.dumps(result.get("meta_tags")),
            fetch_id
        ))


    # Save robots.txt if we received one
    if result.get("content"):
        filename = save_robot_file(
            result["content"],
            fetch_id,
            robots_dir,
            crawl_dir
        )
        file_hash = sha256_text(
            result["content"]
        )
        size = len(
            result["content"].encode("utf-8")
        )
        cur.execute("""
            UPDATE fetches
            SET
                filename = ?,
                sha256 = ?,
                bytes = ?
            WHERE fetch_id = ?
        """, (
            filename,
            file_hash,
            size,
            fetch_id
        ))
    conn.commit()

#function for connections and running the crawler
async def run_crawl(
    df, USER_AGENT, TIMEOUT, CONCURRENCY, LIMIT_PER_HOST,
    conn, master_conn, crawl_id, robots_dir, crawl_dir
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
        tasks = []
        for row in df.itertuples():
            print(f"Appending domain: {row.domain} with rank: {row.Index}")
            tasks.append(process_domain(
                session,
                row,
                conn,
                master_conn,
                crawl_id,
                robots_dir,
                crawl_dir
            ))
        await tqdm_asyncio.gather(
            *tasks
        )

