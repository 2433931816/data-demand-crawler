import sqlite3

conn = sqlite3.connect('./demands.db')
cursor = conn.cursor()

# 删除上海和湖南的旧数据（商品/产品）
cursor.execute("DELETE FROM demands WHERE source IN ('上海数据交易所', '湖南大数据交易所')")
deleted = cursor.rowcount
conn.commit()
conn.close()

print(f"已删除 {deleted} 条旧数据（上海、湖南）")