import sqlite3
import re
import pandas as pd
import os
import html
import shutil
import json
import logging
import glob
import requests
from logging.handlers import RotatingFileHandler
from datetime import datetime
from bs4 import BeautifulSoup

# ========== 配置 ==========
# 企业微信机器人 Webhook（与 scheduler 共用）
WECHAT_WEBHOOK_URL = " "

# ========== 创建日志目录 ==========
LOG_DIR = './logs'
os.makedirs(LOG_DIR, exist_ok=True)

# ========== 配置日志（RotatingFileHandler） ==========
log_file = os.path.join(LOG_DIR, 'clean.log')
logger = logging.getLogger('clean_data')
logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

file_handler = RotatingFileHandler(
    log_file,
    maxBytes=5 * 1024 * 1024,  # 5MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

logger.addHandler(console_handler)
logger.addHandler(file_handler)

# ======================== 分类映射表 ========================
BEIJING_CATEGORY_MAP = {
    '1': '数据采购',
    '2': '数据出售',
    '3': '数据服务',
    '4': '数据工具',
    '5': '数据咨询',
}

SHANGHAI_CATEGORY_MAP = {
    '01': '金融数据',
    '02': '交通数据',
    '03': '企业数据',
    '04': '政务数据',
    '05': '科研数据',
    '06': '商业数据',
}

GUANGZHOU_CATEGORY_MAP = {
    '购买意向': '数据采购',
    '供给意向': '数据供给',
    # 后续发现新类型可在此添加
}

# ===== 新增：杭州数据交易所分类映射 =====
HANGZHOU_CATEGORY_MAP = {
    'DATA_DEMAND': '数据采购',
    'DATA_SUPPLY': '数据供给',
    'DATA_SERVICE': '数据服务',
    'DATA_PRODUCT': '数据产品',
    'DATA_TOOL': '数据工具',
}

# ===== 新增：深圳数据交易所分类映射（预置，待正式接入后生效） =====
SHENZHEN_CATEGORY_MAP = {
    '数据产品': '数据产品',
    '数据服务': '数据服务',
    '数据工具': '数据工具',
}

# ========== 企业微信告警函数 ==========
def send_wechat_alert(message: str):
    if not WECHAT_WEBHOOK_URL or "你的key" in WECHAT_WEBHOOK_URL:
        logger.warning("企业微信 Webhook 未配置，跳过告警")
        return
    try:
        data = {
            "msgtype": "text",
            "text": {"content": f"⚠️ 清洗告警\n{message}"}
        }
        resp = requests.post(WECHAT_WEBHOOK_URL, json=data, timeout=5)
        if resp.status_code == 200:
            logger.info("告警消息已发送")
        else:
            logger.error(f"告警发送失败: {resp.text}")
    except Exception as e:
        logger.error(f"告警发送异常: {e}")

# ======================== HTML 清洗函数 ========================
def clean_html_aggressive(raw: str) -> str:
    """使用 BeautifulSoup 彻底清除所有HTML标签，提取纯文本"""
    if not raw:
        return ''
    try:
        soup = BeautifulSoup(raw, 'lxml')
        for tag in soup(['script', 'style']):
            tag.decompose()
        text = soup.get_text(separator=' ', strip=True)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    except Exception as e:
        logger.warning(f"BeautifulSoup 清洗失败: {e}，使用正则回退")
        text = html.unescape(raw)
        text = re.sub(r'<[^>]+>', '', text)
        text = text.replace('<', '').replace('>', '')
        text = re.sub(r'\s+', ' ', text).strip()
        return text

# ======================== 从 raw_data 恢复字段 ========================
def recover_fields_from_raw(cursor):
    logger.info("🔄 从 raw_data 恢复字段...")
    # 上海
    cursor.execute("""
        SELECT id, raw_data FROM demands 
        WHERE source = '上海数据交易所' 
        AND (title IS NULL OR title = '' OR title = '无标题')
    """)
    rows = cursor.fetchall()
    recovered = 0
    for row_id, raw in rows:
        try:
            data = json.loads(raw)
            new_title = data.get('dataName', '') or data.get('name', '') or '无标题'
            new_desc = data.get('dataContent', '') or data.get('description', '')
            if new_title and new_title != '无标题':
                cursor.execute("UPDATE demands SET title=?, description=? WHERE id=?", (new_title, new_desc, row_id))
                recovered += 1
        except:
            pass
    logger.info(f"✅ 上海数交所: 恢复 {recovered} 条")
    # 北京
    cursor.execute("""
        SELECT id, raw_data FROM demands 
        WHERE source = '北京国际大数据交易所' 
        AND (title IS NULL OR title = '' OR title = '无标题')
    """)
    rows = cursor.fetchall()
    recovered = 0
    for row_id, raw in rows:
        try:
            data = json.loads(raw)
            new_title = data.get('demandTitle', '') or data.get('title', '') or '无标题'
            new_desc = data.get('demandDescribe', '') or data.get('description', '')
            if new_title and new_title != '无标题':
                cursor.execute("UPDATE demands SET title=?, description=? WHERE id=?", (new_title, new_desc, row_id))
                recovered += 1
        except:
            pass
    logger.info(f"✅ 北京数交所: 恢复 {recovered} 条")

# ======================== 数据质量检查 ========================
def check_data_quality(db_path='./demands.db'):
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM demands", conn)
    conn.close()
    if df.empty:
        logger.warning("⚠️ 数据库为空！")
        send_wechat_alert("数据库为空，可能抓取失败")
        return

    logger.info("\n" + "=" * 60)
    logger.info("📊 数据质量监控报告")
    logger.info("=" * 60)
    total = len(df)
    logger.info(f"\n📌 总记录数: {total}")
    logger.info("📌 各来源分布:")
    for src, cnt in df['source'].value_counts().items():
        logger.info(f"   - {src}: {cnt} 条")

    empty_title = df['title'].isna().sum() + (df['title'] == '').sum()
    empty_desc = df['description'].isna().sum() + (df['description'] == '').sum()
    empty_url = df['url'].isna().sum() + (df['url'] == '').sum()
    logger.info(f"\n⚠️ 空字段统计:")
    logger.info(f"   - 空标题: {empty_title} 条 ({empty_title/total*100:.1f}%)")
    logger.info(f"   - 空描述: {empty_desc} 条 ({empty_desc/total*100:.1f}%)")
    logger.info(f"   - 空URL: {empty_url} 条 ({empty_url/total*100:.1f}%)")

    suspicious = df[df['title'].str.contains('无标题|测试|tests|TBD', case=False, na=False)]
    if not suspicious.empty:
        logger.info(f"\n⚠️ 可疑标题数量: {len(suspicious)} 条")
    else:
        logger.info("\n✅ 标题无异常")

    bad_dates = df[df['publish_date'].isna() | (df['publish_date'] == '')]
    if not bad_dates.empty:
        logger.info(f"\n⚠️ 缺失发布日期的记录: {len(bad_dates)} 条")
    else:
        logger.info("\n✅ 发布日期正常")

    dup_count = df.duplicated(subset=['source', 'title'], keep=False).sum()
    if dup_count > 0:
        logger.info(f"\n⚠️ 疑似重复记录（同来源同标题）: {dup_count} 条")
    else:
        logger.info("\n✅ 无重复记录")

    today = datetime.now().strftime('%Y-%m-%d')
    today_count = df[df['created_at'].str.startswith(today)].shape[0]
    logger.info(f"\n📈 今日新增: {today_count} 条")
    logger.info("\n" + "=" * 60)
    logger.info("✅ 质量检查完成")
    logger.info("=" * 60 + "\n")

    if today_count == 0 and total > 0:
        send_wechat_alert(f"今日新增为0，可能抓取异常（总记录 {total} 条）")

# ======================== 去重 ========================
def remove_duplicates(db_path='./demands.db', keep='latest'):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT source, title, COUNT(*) as cnt
        FROM demands
        GROUP BY source, title
        HAVING cnt > 1
    """)
    dup_groups = cursor.fetchall()
    if not dup_groups:
        logger.info("✅ 无重复记录")
        conn.close()
        return
    total_deleted = 0
    for source, title, cnt in dup_groups:
        order = "DESC" if keep == 'latest' else "ASC"
        cursor.execute(f"""
            SELECT id, created_at FROM demands
            WHERE source = ? AND title = ?
            ORDER BY created_at {order}
        """, (source, title))
        rows = cursor.fetchall()
        delete_ids = [row[0] for row in rows[1:]]
        if delete_ids:
            placeholders = ','.join(['?'] * len(delete_ids))
            cursor.execute(f"DELETE FROM demands WHERE id IN ({placeholders})", delete_ids)
            total_deleted += len(delete_ids)
            logger.info(f"🗑️ 删除 {len(delete_ids)} 条重复记录 (来源: {source}, 标题: {title[:30]}...)")
    conn.commit()
    conn.close()
    logger.info(f"✅ 总计删除 {total_deleted} 条重复记录")

# ======================== 清理旧备份 ========================
def clean_old_backups(db_path='./demands.db', days_to_keep=7):
    backup_pattern = os.path.join(os.path.dirname(db_path), f"{os.path.basename(db_path)}.backup_aggressive_*")
    backup_files = glob.glob(backup_pattern)
    if not backup_files:
        logger.info("📂 未找到备份文件，无需清理")
        return
    backup_files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    keep_count = days_to_keep
    if len(backup_files) <= keep_count:
        logger.info(f"📂 备份文件仅 {len(backup_files)} 个，未超过 {keep_count} 个，无需清理")
        return
    deleted = 0
    for old_file in backup_files[keep_count:]:
        try:
            os.remove(old_file)
            deleted += 1
            logger.info(f"🗑️ 已删除旧备份: {os.path.basename(old_file)}")
        except Exception as e:
            logger.warning(f"⚠️ 无法删除 {old_file}: {e}")
    logger.info(f"✅ 清理完成，共删除 {deleted} 个旧备份文件")

# ======================== 核心清洗 ========================
def _perform_cleaning(db_path='./demands.db'):
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"数据库 {db_path} 不存在")
    backup_path = db_path + f'.backup_aggressive_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    shutil.copy2(db_path, backup_path)
    logger.info(f"已备份数据库至: {backup_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    recover_fields_from_raw(cursor)
    conn.commit()
    cursor.execute("SELECT id, title, description, raw_data FROM demands")
    rows = cursor.fetchall()
    logger.info(f"共 {len(rows)} 条记录")
    updated = 0
    for row_id, title, desc, raw in rows:
        new_title = clean_html_aggressive(title) if title else ''
        new_desc = clean_html_aggressive(desc) if desc else ''
        new_raw = clean_html_aggressive(raw) if raw else ''
        if new_title != title or new_desc != desc or new_raw != raw:
            cursor.execute("UPDATE demands SET title=?, description=?, raw_data=? WHERE id=?", (new_title, new_desc, new_raw, row_id))
            updated += 1
    conn.commit()
    logger.info(f"已清洗 {updated} 条记录")
    df = pd.read_sql_query("SELECT * FROM demands ORDER BY created_at DESC", conn)
    conn.close()

    # ========== 分类映射转换 ==========
    # 北京
    df.loc[df['source'] == '北京国际大数据交易所', 'category'] = df[df['source'] == '北京国际大数据交易所']['category'].map(
        lambda x: BEIJING_CATEGORY_MAP.get(str(x), str(x)) if pd.notna(x) else x
    )
    # 上海
    df.loc[df['source'] == '上海数据交易所', 'category'] = df[df['source'] == '上海数据交易所']['category'].map(
        lambda x: SHANGHAI_CATEGORY_MAP.get(str(x), str(x)) if pd.notna(x) else x
    )
    # 广州
    df.loc[df['source'] == '广州数据交易所', 'category'] = df[df['source'] == '广州数据交易所']['category'].map(
        lambda x: GUANGZHOU_CATEGORY_MAP.get(x, x) if pd.notna(x) else x
    )
    # ===== 新增：杭州 =====
    df.loc[df['source'] == '杭州数据交易所', 'category'] = df[df['source'] == '杭州数据交易所']['category'].map(
        lambda x: HANGZHOU_CATEGORY_MAP.get(x, x) if pd.notna(x) else x
    )
    # ===== 新增：深圳（预置，待正式接入后生效） =====
    df.loc[df['source'] == '深圳数据交易所', 'category'] = df[df['source'] == '深圳数据交易所']['category'].map(
        lambda x: SHENZHEN_CATEGORY_MAP.get(x, x) if pd.notna(x) else x
    )

    for col in ['title', 'description']:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: clean_html_aggressive(x) if isinstance(x, str) else x)
    if 'description' in df.columns:
        df['description'] = df['description'].apply(lambda x: x[:600] + '...' if isinstance(x, str) and len(x) > 600 else x)
    today_str = datetime.now().strftime('%Y-%m-%d')
    today_df = df[df['created_at'].str.startswith(today_str)]
    remove_duplicates(db_path)
    clean_old_backups(db_path)
    return df, today_df

# ======================== 每日增量 ========================
def clean_and_export_daily(db_path='./demands.db'):
    logger.info("\n" + "=" * 60)
    logger.info("🧹 每日增量清洗与导出（定时任务）")
    logger.info("=" * 60)
    try:
        df, today_df = _perform_cleaning(db_path)
    except Exception as e:
        logger.error(f"❌ 清洗失败: {e}")
        send_wechat_alert(f"清洗失败: {str(e)}")
        return
    today_str = datetime.now().strftime('%Y-%m-%d')
    if not today_df.empty:
        inc_dir = './data_demands_daily'
        os.makedirs(inc_dir, exist_ok=True)
        inc_path = os.path.join(inc_dir, f"demands_new_{today_str}.csv")
        today_df.to_csv(inc_path, index=False, encoding='utf-8-sig')
        logger.info(f"📈 今日新增 {len(today_df)} 条 → {inc_path}")
    else:
        logger.info("📈 今日无新增数据，未生成增量文件")
    check_data_quality(db_path)
    logger.info("✅ 每日增量任务完成\n")

# ======================== 手动全量 ========================
def clean_and_export_full(db_path='./demands.db'):
    logger.info("\n" + "=" * 60)
    logger.info("📦 全量清洗与导出（手动运行）")
    logger.info("=" * 60)
    try:
        df, today_df = _perform_cleaning(db_path)
    except Exception as e:
        logger.error(f"❌ 清洗失败: {e}")
        send_wechat_alert(f"全量清洗失败: {str(e)}")
        return
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = './data_demands_clean'
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"demands_clean_{timestamp}.csv")
    df.to_csv(output_path, index=False, encoding='utf-8-sig')
    logger.info(f"✅ 全量数据已导出: {output_path}")
    split_dir = './data_demands_clean_split'
    os.makedirs(split_dir, exist_ok=True)
    for source in df['source'].unique():
        subset = df[df['source'] == source]
        if not subset.empty:
            safe_name = source.replace(' ', '_').replace('/', '_')
            path = os.path.join(split_dir, f"{safe_name}_{timestamp}.csv")
            subset.to_csv(path, index=False, encoding='utf-8-sig')
            logger.info(f"📁 {source}: {len(subset)} 条 → {path}")
    today_str = datetime.now().strftime('%Y-%m-%d')
    if not today_df.empty:
        inc_dir = './data_demands_daily'
        os.makedirs(inc_dir, exist_ok=True)
        inc_path = os.path.join(inc_dir, f"demands_new_{today_str}.csv")
        today_df.to_csv(inc_path, index=False, encoding='utf-8-sig')
        logger.info(f"📈 今日新增 {len(today_df)} 条 → {inc_path}")
    else:
        logger.info("📈 今日无新增数据")
    logger.info("\n📊 数据统计:")
    logger.info(df['source'].value_counts().to_string())
    check_data_quality(db_path)
    logger.info("✅ 全量任务完成\n")

def clean_database_aggressive(db_path='./demands.db'):
    clean_and_export_full(db_path)

if __name__ == "__main__":
    clean_and_export_full()