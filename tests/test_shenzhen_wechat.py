import requests
import os
from dotenv import load_dotenv
import json

load_dotenv()

url = "https://www.szdex.com/dmall/v1.0/qd/xqglQd/pageList"
headers = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Referer": "https://www.szdex.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Cookie": os.getenv('COOKIE_SHENZHEN', ''),
    "X-Requested-With": "XMLHttpRequest",
}
payload = {
    "pageNo": 1,
    "pageSize": 12,
    "xqMc": "",
    "xqZt": "2",
    "yylyIdList": [],
    "yycjIdList": [],
    "tags": [],
    "xqLx": "",
    "xqLxFId": "",
    "xqSfgk": 1,
}

response = requests.post(url, headers=headers, json=payload, timeout=30)
print("状态码:", response.status_code)
print("响应内容:", response.text)