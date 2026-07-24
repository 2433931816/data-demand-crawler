import requests
import os
from dotenv import load_dotenv

load_dotenv()

url = "https://h5.hzdex.cn/api/demands/page?demandClassify=DATA_DEMAND&demandName=&page=1&pageSize=8"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://h5.hzdex.cn/",
    "Origin": "https://h5.hzdex.cn",
    "Accept": "application/json, text/plain, */*",
    "Cookie": os.getenv('COOKIE_HANGZHOU', ''),
}

r = requests.get(url, headers=headers)
print("状态码:", r.status_code)
print("内容前500字符:", r.text[:500])