import sqlite3

conn = sqlite3.connect('./demands.db')
cursor = conn.cursor()

cursor.execute("""
    SELECT DATE(created_at), COUNT(*) 
    FROM demands 
    GROUP BY DATE(created_at) 
    ORDER BY DATE(created_at) DESC 
    LIMIT 10
""")

rows = cursor.fetchall()
print("📅 最近10天的数据分布：")
for date, count in rows:
    print(f"{date}: {count} 条")

conn.close()