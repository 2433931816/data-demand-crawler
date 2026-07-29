import requests
from bs4 import BeautifulSoup
import re

url = "https://mp.weixin.qq.com/s/OG7SgBZVhWKvtxYJcq96FA"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

r = requests.get(url, headers=headers, timeout=30)
print(f"状态码: {r.status_code}")
soup = BeautifulSoup(r.text, 'html.parser')

content = soup.find('div', class_='rich_media_content')
if content:
    print("=" * 60)
    print("找到 rich_media_content，内容前800字符:")
    print(content.get_text()[:800])
    print("=" * 60)
else:
    print("未找到 rich_media_content")

# 也尝试其他可能的 class
for cls in ['rich_media_content', 'article-content', 'content']:
    c = soup.find('div', class_=cls)
    if c:
        print(f"找到 class: {cls}, 内容前300字符: {c.get_text()[:300]}")
        break