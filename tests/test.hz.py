import requests
from bs4 import BeautifulSoup
import os
from dotenv import load_dotenv

load_dotenv()

url = "https://mall.hzdex.cn/requirement?tab=hall"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://mall.hzdex.cn/",
    "Origin": "https://mall.hzdex.cn",
    "Cookie": os.getenv('COOKIE_HANGZHOU', ''),
}

print("正在请求:", url)
response = requests.get(url, headers=headers, timeout=30)
print("状态码:", response.status_code)
print("页面前 1500 字符:")
print(response.text[:1500])
with open('hz_response.html', 'w', encoding='utf-8') as f:
    f.write(response.text)