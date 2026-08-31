#Holds functions designed to handle the r2 data loading and unloading

#imports
import os
import gzip
import shutil
import boto3
from pathlib import Path

#grab cloudflare credentials
def grab_cloudflare_r2_access():
    cloudflare_account_id = os.environ.get(
        "CLOUDFLARE_R2_ACCOUNT_ID"
    )
    cloudflare_r2_access_key = os.environ.get(
        "CLOUDFLARE_R2_ACCESS_KEY_ID"
    )
    cloudflare_r2_secret_key = os.environ.get(
        "CLOUDFLARE_R2_SECRET_ACCESS_KEY"
    )
    cloudflare_r2_bucket = os.environ.get(
        "CLOUDFLARE_R2_BUCKET"
    )

    if not all([
        cloudflare_account_id,
        cloudflare_r2_access_key,
        cloudflare_r2_secret_key,
        cloudflare_r2_bucket
    ]):
        raise RuntimeError(
            "Missing one or more Cloudflare R2 environment variables."
        )

    return (
        cloudflare_account_id,
        cloudflare_r2_access_key,
        cloudflare_r2_secret_key,
        cloudflare_r2_bucket
    )

#get connection to r2 server
def get_r2_client():
    (
        account_id,
        access_key,
        secret_key,
        bucket
    ) = grab_cloudflare_r2_access()

    endpoint_url = (
        f"https://{account_id}.r2.cloudflarestorage.com"
    )

    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto"
    )

    return client, bucket

#pack data
def compress_data(file_path):
    file_path = Path(file_path)
    compressed_path = Path(
        str(file_path) + ".gz"
    )

    with open(file_path, "rb") as source:
        with gzip.open(compressed_path, "wb") as destination:
            shutil.copyfileobj(source, destination)
    return compressed_path

#unpack data
def uncompress_data(file_path, output_path=None):
    file_path = Path(file_path)

    if output_path is None:
        if file_path.suffix != ".gz":
            raise ValueError(
                "Input file does not have a .gz extension."
            )

        output_path = file_path.with_suffix("")

    output_path = Path(output_path)

    with gzip.open(file_path, "rb") as source:
        with open(output_path, "wb") as destination:
            shutil.copyfileobj(source, destination)
    return output_path

#export data
def upload_data(file_path, r2_path):
    client, bucket = get_r2_client()

    file_path = Path(file_path)

    print(
        f"Uploading {file_path} → "
        f"r2://{bucket}/{r2_path}"
    )

    client.upload_file(
        str(file_path),
        bucket,
        r2_path
    )

#load data
def download_data(r2_path, output_path):
    client, bucket = get_r2_client()

    output_path = Path(output_path)
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    print(
        f"Downloading "
        f"r2://{bucket}/{r2_path} → "
        f"{output_path}"
    )

    client.download_file(
        bucket,
        r2_path,
        str(output_path)
    )

#uplaod a specified crawl
def upload_crawl(crawl_id, base_dir):
    crawl_dir = Path(base_dir) / crawl_id

    if not crawl_dir.exists():
        raise FileNotFoundError(
            f"Crawl directory not found: {crawl_dir}"
        )

    # R2 directory for this crawl
    r2_prefix = f"crawls/{crawl_id}"

    #upload .csv files
    csv_files = list(crawl_dir.glob("*.csv"))

    for csv_file in csv_files:

        compressed_file = compress_data(csv_file)

        r2_path = (
            f"{r2_prefix}/"
            f"{compressed_file.name}"
        )

        upload_data(compressed_file, r2_path)

    #upload robots.txt files
    robots_dir = crawl_dir / "robots"
    if robots_dir.exists():
        for robots_file in robots_dir.glob("*"):
            if not robots_file.is_file():
                continue

            r2_path = (
                f"{r2_prefix}/robots/"
                f"{robots_file.name}"
            )

            upload_data(robots_file, r2_path)

    print(f"Crawl {crawl_id} successfully uploaded.")


#download a specified crawl
def download_crawl(crawl_id, output_dir):

    output_dir = Path(output_dir)
    crawl_dir = output_dir / crawl_id

    crawl_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    r2_prefix = f"crawls/{crawl_id}"

    client, bucket = get_r2_client()

    response = client.list_objects_v2(
        Bucket=bucket,
        Prefix=r2_prefix
    )

    contents = response.get("Contents", [])
    if not contents:
        raise FileNotFoundError(
            f"No crawl found in R2: {crawl_id}"
        )

    for obj in contents:
        r2_path = obj["Key"]

        relative_path = Path(
            r2_path
        ).relative_to(r2_prefix)

        local_path = crawl_dir / relative_path

        download_data(
            r2_path,
            local_path
        )

    print(f"Crawl {crawl_id} downloaded.")