#Holds functions designed to handle the r2 data loading and unloading

#imports
import os
from pathlib import Path

#grab cloudflare credentials
def grab_cloudflare_r2_access():
    cloudflare_email = os.environ.get(CLOUDFLARE_EMAIL)
    cloudflare_r2_api_key = os.environ.get(CLOUDFLARE_API_KEY)
    return cloudflare_email, cloudflare_r2_api_key

#pack data
def pack_data(crawl_id, base_dir):\
    cloudflare_email, cloudflare_r2_api_key = grab_cloudflare_r2_access()
    

#unpack data
def unpack_data(crawl_id, base_dir):
    cloudflare_email, cloudflare_r2_api_key = grab_cloudflare_r2_access()

#export data
def export_data():
    cloudflare_email, cloudflare_r2_api_key = grab_cloudflare_r2_access()


#load data
def load_data():
    cloudflare_email, cloudflare_r2_api_key = grab_cloudflare_r2_access()