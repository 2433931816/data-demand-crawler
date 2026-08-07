import sqlite3

conn = sqlite3.connect('./demands.db')
cursor = conn.cursor()

# 查询深圳数据交易所的优先级
cursor.execute("SELECT source, source_priority FROM demands WHERE source='深圳数据交易所' LIMIT 5")
rows = cursor.fetchall()

if rows:
    for row in rows:
        print(f'{row[0]}: {row[1]}')
else:
    print('暂无深圳数据')

# 查询所有数据源的优先级分布
cursor.execute("SELECT source, source_priority, COUNT(*) FROM demands GROUP BY source, source_priority")
print("\n各数据源优先级分布:")
for row in cursor.fetchall():
    print(f'{row[0]}: 优先级{row[1]} - {row[2]} 条')

conn.close()