# REP_Crawler

Web crawler to examine Robots Exclusion Protocol (REP) implementation in the top 1m web domains.

## Description

Python project utilizing the [TRANCO list](https://tranco-list.eu/) to identify the top web domains, and then queries them for Robots Exclusion Protocol (REP) implementations using the standards in [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html), as well as \<meta\> tags in HTML text described by the [Web Robots Pages](https://www.robotstxt.org/). Crawl data is stored in `/data` as SQLite databases and CSV files. The validation script creates small samples for manual browser checks. Crawl result directories are included in `.gitignore` because a full crawl creates a lot of data. At the end of a crawl, the databases and CSV files are compressed and uploaded to a connected Cloudflare R2 bucket.


## Functions

- `python main.py` runs the user agent and performs the web crawl.
- `python src/validation.py` generates reproducible samples for manual validation in a web browser and comparisons between crawls.
- `python src/r2.py` tests the r2 enviroment variables and cloud database connection.

- `/data/domains.sqlite` stores the IDs of all domains ever queried.
- `/data/[crawl_id]` stores the data for an individual crawl. Crawl IDs are based on the timestamp when `main.py` starts.
- `/data/[crawl_id]/output` stores the CSV outputs for that crawl.
  
All data from the web crawls is stored in `/data`. Robots.txt responses are parsed while they are being downloaded.The crawler retains parsed results and metadata instead of saving a separate file for every response. After output generation, `main.py` compresses the databases and CSV files and uploads them to the connected Cloudflare R2 bucket.

A robots.txt response is limited to 8 MiB by default so an unbounded response cannot exhaust memory. To change the limit, set `REP_MAX_ROBOTS_BYTES`. The HTML response is limited to 2 MiB by default; `REP_MAX_HTML_BYTES`, `REP_MAX_META_TAGS`, `REP_MAX_META_TAG_VALUE_BYTES`, and `REP_MAX_META_TOTAL_BYTES` can be used to adjust the meta-tag limits. Responses over the robots limit are marked `ROBOTS_TOO_LARGE`.

`index_truncated` indicates that the homepage exceeded the HTML read limit; `meta_tags_truncated` indicates that individual tags exceeded the limit. `truncated` in crawl data refers to the robots.txt response.

Errors in contacting either the index page of a domain or the robots.txt extentiosn are recorded. the HTTP codes and any specifiic error messages obatined are included in the outout dataset. Additionally, some domains offer redirects upon a request for a `*/robot.txt`, these are recorded as `NOT_ROBOTS_FILE`.

## Data layout

- `/data/domains.sqlite` stores the master list of domains and their IDs.
- `/data/master_domains.csv` is the CSV dump of the master domain database created during output/upload.
- `/data/[crawl_id]/tranco_list_[timestamp].csv` is the saved Tranco snapshot used for that crawl.
- `/data/[crawl_id]/metadata.sqlite` stores crawl state, domain IDs, fetch results, response metadata, hashes, and checkpoints.
- `/data/[crawl_id]/parsed.sqlite` stores robots groups, user agents, directives, and diagnostics.
- `/data/[crawl_id]/output/` stores the generated CSV files:
	- `[crawl_id]_crawl_data.csv`
	- `[crawl_id]_robotstxt_data.csv`
	- `[crawl_id]_diagnostics_data.csv`
	- `[crawl_id]_meta_tags_data.csv`

## Dependencies

- aiohttp
- beautifulsoup4
- boto3
- python-dotenv
- requests
- tqdm

## Arguments

For `main.py`:

- `-h, --help` shows information about program arguments then exits.
- `-a, --autorun` skips user verification of process steps, running the entire program automatically. By default, the program will ask for user confirmation at the start of each step.
- `-o [crawl_id], --output [crawl_id]` skips crawling and generates output data using a given crawl ID directory. Robots and meta-tag parsing happen during the crawl.
- `-c [crawl_id], --crawlid [crawl_id]` provides the crawl ID when using output or resume options.
- `-u, --noupload` skips uploading the crawl data to the connected R2 bucket.
- `--max-domains [value]` limits the number of domains in a crawl. The default is 100, and `0` runs the full Tranco list.
- `-r, --resume` resumes an interrupted crawl using its saved Tranco snapshot. You will need to provide a `crawl_id` with the `-c` argument.

Example:
```bash
python main.py -a --max-domains 10000
python main.py --autorun -output --crawlid 202609071849 --resume
```

For `validation.py`:

- `-s [crawl id], --single [crawl id]` generates a validation sample for one web crawl.
- `-m [crawl id] [crawl id] ... , --multiple [crawl id] [crawl id] ...` generates aligned samples for multiple web crawls so changes can be compared by domain.
- `-v [random seed], --seedvalue [random seed]` uses a specific seed for reproducible sampling. A random seed is used by default.
- `-n [value], --numsamples [value]` sets the number of domains to sample. The default is 100.
- `--data-dir [path]` sets the root data directory. The default is `./data`.

Validation samples include URLs, recorded response metadata, parsed robots directives,  diagnostic determination of rules, and the captured meta tags. Multiple-crawl validation samples the same completed domain set in every requested crawl and also outputs a comparison CSV.

Example:

```bash
python validation.py --single 202609071849 --numsamples 100 --seedvalue 42
python validation.py --multiple 202609071849 202609071900 --seedvalue 42
```

## Initialization

Note: *This project was created to run on a Linux system, the commands listed for your OS may differ*

Sign up for an API key to pull the TRANCO list from their [website](https://tranco-list.eu/). Add the email and API token to your environment variables as `TRANCO_EMAIL` and `TRANCO_API_TOKEN`.

For R2 uploads, also set `CLOUDFLARE_R2_ACCESS_KEY_ID`, `CLOUDFLARE_R2_SECRET_ACCESS_KEY`, `CLOUDFLARE_R2_BUCKET`, and `CLOUDFLARE_R2_S3_API`. Use `--noupload` when working locally without R2 credentials.

This project includes a `uv.lock` file. Install `uv` on your system, then use it to create the virtual environment and install the locked dependencies if desired.

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

Alternatively, install the requirements without uv:

```bash
pip install -r requirements.txt
```

## Operation

Run the main crawler:

```bash
python main.py
```

Progress is csaved with each completed domain. If a crawl stops, you may resume
it with:

```bash
python main.py - -r -c [crawl_id]
```
