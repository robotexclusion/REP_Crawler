# REP_Crawler

Web crawler to examine Robots Exclusion Protocol (REP) implementation in the top 1m web domains.

## Description

<p>Python project utilizing the [TRANCO list](https://tranco-list.eu/) to identify the top web domains, and then queries them for Robots Exclusion Protocol (REP) implemtations aligning with [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html) , as well as \<meta\> tags in .html text defined by the [Web Robots Pages](https://www.robotstxt.org/). All data from the web crawls are stored in `/data`, in the form of SQLite databases and a validation script for manual verification is included.</p>
<p>Due to the large amount of files and text generated, crawl result directories are included in the .gitignore file and are only available on the local hardware running the crawl. To address this, at the end of the crawl all gathered data is uploaded to a connected CLoudFlare R2 Object Storage database. The database has a "public bucket" assigned that can be accessed with CloudFlare credentials at [repcrawler.download](http://repcrawler.download).</p>

## Functions

- `python main.py` runs the user agent and performs the web crawl.
- `python validation.py` runs the functions to generate and replicate random sampling for manual validation of results (i.e., through a web browser).
- `python query.py` runs a SQLite query on the main domain file (Master list of all domains queried across all crawls).
  
All data from the web crawls is stored in `/data`. Robots.txt responses are parsed while they are being downloaded, so new crawls retain parsed results and metadata instead of saving a separate file for every response. After the parsing and output functions complete, `main.py` passes the new databases and output files through gzip compression and uploads them to a connected CloudFlare R2 Object Storage database.

- `/data/domains.sqlite` stores the ID's of all domains ever queried to reference across queries.
- `/data/[number]` stores the data for individual crawls. The crawls are assigned a `crawl_id` based on the timestamp of running `main.py`.
- `data/[number]/robots/` is retained for compatibility with older crawls. New crawls parse the responses directly and do not create individual `robots.txt` files.
- `data/[number]/output` stores raw and parsed .csv outputs of the respective crawl.

## Dependencies

- pandas
- requests
- tqdm
- BeautifulSoup4
- aiohttp
- boto3

## Arguments

For `main.py`:

- `-h, --help` shows information about program and arguments then exits.
- `-a, --autorun` skips user verification of process steps, running the entire program automatically.
- `-o [crawl_id], --output [crawl_id]` skips crawling and generates output data using a given crawl ID directory. Robots and meta-tag parsing happen during the crawl.
- `-c [crawl_id], --crawlid [crawl_id]` provides the crawl ID when using output or resume options
- `-u, --noupload` skip uploading the crawl data to the connected R2 bucket
- `--max-domains [value]` limits the number of domains in a crawl. The default is 100, and `0` runs the full Tranco list
- `--resume` resumes an interrupted crawl using its saved Tranco snapshot. This option requires `--crawlid`

For `validation.py`:

- `-s [crawl id], --single [crawl id]` generates a validation sample for one web crawl.
- `-m [crawl id] [crawl id] ... , --multiple [crawl id] [crawl id] ...` generates aligned samples for multiple web crawls so changes can be compared by domain.
- `-v [random seed], --seedvalue [random seed]` uses a specific seed for reproducible sampling. A random seed is used by default.
- `-n [value], --numsamples [value]` sets the number of domains to sample. The default is 100.
- `--data-dir [path]` sets the root data directory. The default is `./data`.

Validation samples include direct HTTP and HTTPS homepage and `robots.txt` URLs,
recorded response metadata, parsed robots directives and diagnostics, and the
captured meta tags. Multiple-crawl validation samples the same completed domain
set in every requested crawl and also writes a combined comparison CSV. The
validator targets the current crawl schema; older crawl files should be removed
or regenerated before validation.

Example:

```bash
python validation.py --single 202609071849 --numsamples 100 --seedvalue 42
python validation.py --multiple 202609071849 202609071900 --seedvalue 42
```

## Initialization

Note: *This project was created to run on a Linux system, the commands listed for your OS may differ*

Sign up for an api key to pull the TRANCO list from their [website](https://tranco-list.eu/). The email and api key will need to be added to your enviroment variables.

This project includes a `uv.lock` file. Install `uv` on your Linux system, then use it to create the virtual environment and install the locked dependencies.

Run the following command to download the project:

```bash
git clone https://github.com/robotexclusion/REP_Crawler
```

Navigate into the project directory:

```bash
cd REP_Crawler
```

To set up the project with uv:

```bash
uv venv --python 3.12
```

```bash
source .venv/bin/activate
```

```bash
uv sync --locked
```

To intentionally refresh dependency versions later, run `uv lock --upgrade`
and then `uv sync --locked`.

Alternatively, install the fallback requirements without uv:

```bash
pip install -r requirements.txt
```

Run the main crawler:

```bash
python main.py
```

The crawler parses robots responses while they are streamed and retains only
parsed SQLite rows and metadata. A robots response is limited to 8 MiB by
default so an unbounded response cannot exhaust memory. To change the limit,
set the `REP_MAX_ROBOTS_BYTES` environment variable. Responses over the limit
are marked `ROBOTS_TOO_LARGE` and counted as parse errors rather than being
reported as complete.

Progress is checkpointed after each completed domain. If a crawl stops, resume
it with:

```bash
python main.py --autorun --resume --crawlid 202609071731 --max-domains 0 --noupload
```

The saved Tranco snapshot is reused, completed domains are skipped, and any
incomplete fetch rows from the interrupted run are discarded before retrying.
