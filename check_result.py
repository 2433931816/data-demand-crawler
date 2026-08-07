from crawler import ShangshuwangCrawler

c = ShangshuwangCrawler()
r = c.fetch_beijing_wechat()

print(f"抓取到 {len(r)} 条需求\n")
for d in r:
    print(f"标题: {d['title'][:50]}...")
    print(f"描述: {d['description'][:200]}...")
    print("-" * 50)