# REP_Crawler

Web crawler to examine Robots Exclusion Protocol (REP) implementation in the top 1m web domains.

## Description

Python project utilizing the [TRANCO list](https://tranco-list.eu/) to identify the top web domains, and then queries them for Robots Exclusion Protocol (REP) implemtations aligning with [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html) , as well as \<meta\> tags in .html text defined by the [Web Robots Pages](https://www.robotstxt.org/). All data from the web crawls are stored in `/data`, in the form of SQLite databases and a validation script for manual verification is included. At the end of the crawl, all data is uploaded to a connected CLoudFlare R2 Object Storage database. The database has a "public bucket" assigned that can be accessed with CloudFlare credentials at [repcrawler.download](http://repcrawler.download)

## Functions

- `python main.py` runs the user agent and performs the web crawl.
- `python validation.py` runs the functions to generate and replicate random sampling for manual validation of results (i.e., through a web browser).
- `python query.py` runs a SQLite query on the main domain file (Master list of all domains queried across all crawls).
  
All data from the web crawls is stored in `/data`. After the parsing and output functions complete, `main.py` passes the new databases and crawled robots.txt files through gzip compression and uploads them to a connected CloudFlare R2 Object Storage database. 

- `/data/domains.sqlite` stores the ID's of all domains ever queried to reference across queries.
- `/data/[number]` stores the data for individual crawls. The crawls are assigned a `crawl_id` based on the timestamp of running `main.py`.
- `data/[number]/robots/` stores the collected `robots.txt` files.
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
- `-p [crawl_id], --parse [crawl_id]` skips the crawl step and starts with parsing data using a given crawl_id directory
- `-o [crawl_id], --output [crawl_id]` skips the crawl and parsing steps and starts with generating output data using a given crawl_id directory
- `-u, --noupload` skip uploading the crawl data to the connected R2 bucket

For `validation.py':

- `-s [crawl id], --single [crawl id]` Generate validation for a single web crawl
- `-m [crawl id] [crawl id], --multiple [crawl id] [crawl id]` Generate validation for multiple web crawls (useful to compare changes in results)
- `-v [random seed], --seedvalue [random seed]` Pass a specific seed value for random sampling (Default: new seed on each validation)
- `-n [value], --numsamples [value]` Pass a specific number of samples to generate for validation (Default: 100)

## Initialization

Note: *This project was created to run on a Linux system, the commands listed for your OS may differ*

Sign up for an api key to pull the TRANCO list from their [website](https://tranco-list.eu/). The email and api key will need to be added to your enviroment variables.

This project includes a `uv.lock` file, intended to be used with uv to set up a virtual enviroment and resolve dependencies. to utilize this file, you will need to install uv on your system.

Run the following command to download the project:

```bash
git clone https://github.com/robotexclusion/REP_Crawler
```

Navigate into the project directory:

```bash
cd REP_Crawler
```

To set up a virtual envrioment with uv:

```bash
uv venv rep_crawler
```

```bash
source rep_crawler/bin/activate
```

```bash
uv pip install -r requirements.txt
```

```bash
uv sync
```

Alternatively, install the requirements without a virtual enviroment:

```bash
pip install -r requirements.txt
```

Run the main crawler:

```bash
python main.py
```
