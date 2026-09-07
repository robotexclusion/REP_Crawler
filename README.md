# REP_Crawler

Web crawler to examine Robots Exclusion Protocol (REP) implementation in the top 1m web domains.

## Description

<p>Python project utilizing the [TRANCO list](https://tranco-list.eu/) to identify the top web domains, and then queries them for Robots Exclusion Protocol (REP) implementations aligning with [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html), as well as \<meta\> tags in HTML text described by the [Web Robots Pages](https://www.robotstxt.org/). Crawl data is stored in `/data` as SQLite databases and CSV files. The validation script creates small samples for manual browser checks.</p>
<p>Crawl result directories are included in `.gitignore` because a full crawl creates a lot of data. At the end of a crawl, the databases and CSV files are compressed and uploaded to the connected Cloudflare R2 bucket.</p>

## Functions

- `python main.py` runs the user agent and performs the web crawl.
- `python validation.py` generates reproducible samples for manual validation in a web browser and comparisons between crawls.
  
All data from the web crawls is stored in `/data`. Robots.txt responses are parsed while they are being downloaded, so the crawler retains parsed results and metadata instead of saving a separate file for every response. After output generation, `main.py` compresses the databases and CSV files and uploads them to the connected Cloudflare R2 bucket.

Robots directive records retain the normalized directive, value, source line,
and raw line. `Allow` and `Disallow` are classified as `RFC9309`,
`User-agent` as `USRAGT`, known non-RFC records such as `Sitemap` and
`Crawl-delay` as `EXTENSION`, and other records as `UNKNOWN`. Diagnostics retain
invalid UTF-8, control characters, invalid product tokens, invalid path
patterns, missing separators, and other parse conditions without discarding the
original directive line.

Meta robots tags are collected only from the domain index HTML. Their raw
content and parsed tokens are retained. Formatting errors, unknown tokens, and
conflicting rules are recorded separately so a well-formed but contradictory
tag is not mislabeled as syntactically malformed.

- `/data/domains.sqlite` stores the IDs of all domains ever queried.
- `/data/[crawl_id]` stores the data for an individual crawl. Crawl IDs are based on the timestamp when `main.py` starts.
- `/data/[crawl_id]/output` stores the CSV outputs for that crawl.

## Data layout

- `/data/domains.sqlite` stores the master list of domains and their IDs.
- `/data/master_domains.csv` is the CSV dump of the master domain database created during output/upload.
- `/data/[crawl_id]/tranco_list_*.csv` is the saved Tranco snapshot used for that crawl.
- `/data/[crawl_id]/metadata.sqlite` stores crawl state, domain IDs, fetch results, response metadata, hashes, and checkpoints.
- `/data/[crawl_id]/parsed.sqlite` stores robots groups, user agents, directives, and diagnostics.
- `/data/[crawl_id]/output/` stores the three generated CSV files:
	- `[crawl_id]_crawl_data.csv`
	- `[crawl_id]_robotstxt_data.csv`
	- `[crawl_id]_meta_tags_data.csv`

The crawler does not retain complete robots.txt or HTML response bodies. Robots
content is parsed as it is read. Index HTML is capped before meta-tag extraction,
and robots.txt content is capped before parsing.

## Dependencies

The project uses `uv.lock` for the locked dependency set. The main runtime
dependencies are `aiohttp`, `beautifulsoup4`, `boto3`, `python-dotenv`,
`requests`, and `tqdm`.

## Arguments

For `main.py`:

- `-h, --help` shows information about program and arguments then exits.
- `-a, --autorun` skips user verification of process steps, running the entire program automatically.
- `-o [crawl_id], --output [crawl_id]` skips crawling and generates output data using a given crawl ID directory. Robots and meta-tag parsing happen during the crawl.
- `-c [crawl_id], --crawlid [crawl_id]` provides the crawl ID when using output or resume options.
- `-u, --noupload` skips uploading the crawl data to the connected R2 bucket.
- `--max-domains [value]` limits the number of domains in a crawl. The default is 100, and `0` runs the full Tranco list.
- `--resume` resumes an interrupted crawl using its saved Tranco snapshot. This option requires `--crawlid`.

For `validation.py`:

- `-s [crawl id], --single [crawl id]` generates a validation sample for one web crawl.
- `-m [crawl id] [crawl id] ... , --multiple [crawl id] [crawl id] ...` generates aligned samples for multiple web crawls so changes can be compared by domain.
- `-v [random seed], --seedvalue [random seed]` uses a specific seed for reproducible sampling. A random seed is used by default.
- `-n [value], --numsamples [value]` sets the number of domains to sample. The default is 100.
- `--data-dir [path]` sets the root data directory. The default is `./data`.

Validation samples include direct HTTP and HTTPS homepage and `robots.txt` URLs,
recorded response metadata, parsed robots directives and diagnostics, and the
captured meta tags. Multiple-crawl validation samples the same completed domain
set in every requested crawl and also writes a combined comparison CSV.

Example:

```bash
python validation.py --single 202609071849 --numsamples 100 --seedvalue 42
python validation.py --multiple 202609071849 202609071900 --seedvalue 42
```

## Initialization

Note: *This project was created to run on a Linux system, the commands listed for your OS may differ*

Sign up for an API key to pull the TRANCO list from their [website](https://tranco-list.eu/). Add the email and API token to your environment variables:

```bash
export TRANCO_EMAIL="your-email"
export TRANCO_API_TOKEN="your-token"
```

For R2 uploads, also set `CLOUDFLARE_R2_ACCOUNT_ID`,
`CLOUDFLARE_R2_ACCESS_KEY_ID`, `CLOUDFLARE_R2_SECRET_ACCESS_KEY`,
`CLOUDFLARE_R2_BUCKET`, and `CLOUDFLARE_R2_S3_API`. Use `--noupload` when
working locally without R2 credentials.

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
set `REP_MAX_ROBOTS_BYTES`. The HTML response is limited to 2 MiB by default;
`REP_MAX_HTML_BYTES`, `REP_MAX_META_TAGS`, `REP_MAX_META_TAG_VALUE_BYTES`, and
`REP_MAX_META_TOTAL_BYTES` can be used to adjust the meta-tag limits. Responses
over the robots limit are marked `ROBOTS_TOO_LARGE` and retain their truncation
status and parser diagnostics.

Progress is checkpointed after each completed domain. If a crawl stops, resume
it with:

```bash
python main.py --autorun --resume --crawlid 202609071731 --max-domains 0 --noupload
```

The saved Tranco snapshot is reused, completed ranks are skipped, and any
incomplete fetch rows and parsed rows from the interrupted run are discarded
before retrying. Checkpoints keep the highest completed rank and the completed
domain count.
