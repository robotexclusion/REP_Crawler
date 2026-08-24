# REP_Crawler

Web crawler to examine Robots Exclusion Protocol (REP) implementation in the top 1m web domains.

## Description

Python project utilizing the [TRANCO list](https://tranco-list.eu/) to identify the top web domains, and then queries them for Robots Exclusion Protocol (REP) implemtations aligning with [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html) , as well as \<meta\> tags in .html text defined by the [Web Robots Pages](https://www.robotstxt.org/). All data from the web crawls are stored in `/data`, in the form of SQLite databases and a validation script for manual verification is included.

## Functions

- `python main.py` runs the user agent and performs the web crawl.
- `python validation.py` runs the functions to generate and replicate random sampling for manual validation of results (i.e., through a web browser).
- `python query.py` runs a SQLite query on the main domain file (Master list of all domains queried across all crawls).
  
- All data from the web crawls is stored in `/data`.
- `/data/domains.sqlite` stores the ID's of all domains ever queried to reference across queries.
- `/data/[number]` stores the data for individual crawls. The crawls are assigned a `crawl_id` based on the timestamp of running `main.py`.
- `data/[number]/robots/` stores the collected `robots.txt` files.
- `data/[number]/output` stores raw and parsed .csv outputs of the respective crawl.

## Dependencies

- uv
- os
- sqlite3
- asyncio
- pandas
- requests
- tqdm
- BeautifulSoup
- aiohttp

## Arguments

Note: *all arguments for `main.py` only*

- `-h, --help` show information about program and arguments then exits
- `-a --autorun` skips user verification of process steps, running the entire program automatically

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

Set up a virtual envrioment with uv:

```bash
uv venv rep_crawler
```

```bash
source rep_crawler/bin/activate
```

```bash
uv sync
```

Run the main crawler:

```bash
python main.py
```
