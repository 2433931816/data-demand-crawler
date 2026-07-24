import requests
import json
import sqlite3
import hashlib
import logging
import pandas as pd
import re
from datetime import datetime
from typing import List, Dict
import os
import html
from dotenv import load_dotenv
from bs4 import BeautifulSoup

# ======================== 加载环境变量 ========================
load_dotenv()

# ======================== 日志配置 ========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ======================== 清洗辅助函数 ========================
def clean_html(raw: str) -> str:
    """去除HTML标签，提取纯文本"""
    if not raw:
        return ''
    try:
        text = html.unescape(raw)
        # 简单正则删除标签（不依赖 BeautifulSoup，减少依赖）
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    except:
        return raw

# ======================== 主爬虫类 ========================
class ShangshuwangCrawler:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        })
        self._init_db()

    # ---------- 数据库初始化 ----------
    def _init_db(self):
        self.conn = sqlite3.connect('./demands.db')
        self.cursor = self.conn.cursor()
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS demands (
                id TEXT PRIMARY KEY,
                source TEXT,
                title TEXT,
                description TEXT,
                category TEXT,
                publish_date TEXT,
                url TEXT,
                raw_data TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        ''')
        self.conn.commit()

    def _generate_id(self, source: str, title: str, date: str) -> str:
        raw = f"{source}_{title}_{date}"
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    def _save_demands(self, demands: List[Dict]):
        if not demands:
            logger.warning("没有数据需要保存")
            return
        now = datetime.now().isoformat()
        for demand in demands:
            demand_id = self._generate_id(
                demand['source'],
                demand['title'],
                demand.get('publish_date', '')
            )
            # 先查询该记录是否存在
            self.cursor.execute("SELECT created_at FROM demands WHERE id = ?", (demand_id,))
            existing = self.cursor.fetchone()
            if existing:
                # 存在：保留原来的 created_at，只更新其他字段
                created_at = existing[0]
                self.cursor.execute('''
                    UPDATE demands SET
                        source = ?,
                        title = ?,
                        description = ?,
                        category = ?,
                        publish_date = ?,
                        url = ?,
                        raw_data = ?,
                        updated_at = ?
                    WHERE id = ?
                ''', (
                    demand['source'],
                    demand['title'],
                    demand.get('description', ''),
                    demand.get('category', ''),
                    demand.get('publish_date', ''),
                    demand.get('url', ''),
                    json.dumps(demand, ensure_ascii=False),
                    now,
                    demand_id
                ))
            else:
                # 不存在：插入新记录，设置 created_at = now
                self.cursor.execute('''
                    INSERT INTO demands
                    (id, source, title, description, category, publish_date, url, raw_data, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    demand_id,
                    demand['source'],
                    demand['title'],
                    demand.get('description', ''),
                    demand.get('category', ''),
                    demand.get('publish_date', ''),
                    demand.get('url', ''),
                    json.dumps(demand, ensure_ascii=False),
                    now,
                    now
                ))
        self.conn.commit()
        logger.info(f"成功保存 {len(demands)} 条需求")

    def _export_csv(self):
        output_dir = './data_demands'
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = os.path.join(output_dir, f"demands_{timestamp}.csv")
        try:
            df = pd.read_sql_query("SELECT * FROM demands ORDER BY created_at DESC", self.conn)
            if 'description' in df.columns:
                df['description'] = df['description'].apply(
                    lambda x: x[:600] + '...' if isinstance(x, str) and len(x) > 600 else x
                )
            df.to_csv(output_path, index=False, encoding='utf-8-sig')
            logger.info(f"数据已导出至: {output_path}")
        except PermissionError:
            alt_path = os.path.join(output_dir, f"demands_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]}.csv")
            df = pd.read_sql_query("SELECT * FROM demands ORDER BY created_at DESC", self.conn)
            df.to_csv(alt_path, index=False, encoding='utf-8-sig')
            logger.info(f"数据已导出至（备用）: {alt_path}")

    # ---------- 数据源：尚数网（公开，无需Cookie） ----------
    def fetch_shangshuwang(self, max_pages: int = 1) -> List[Dict]:
        all_demands = []
        for page in range(1, max_pages + 1):
            logger.info(f"正在抓取尚数网第 {page} 页...")
            page_demands = self._fetch_shangshuwang_page(page)
            if not page_demands:
                break
            all_demands.extend(page_demands)
        return all_demands

    def _fetch_shangshuwang_page(self, page_number: int) -> List[Dict]:
        demands = []
        try:
            url = f"https://api.shangshuwang.cn/m/getSampleList/new?pageSize=10&pageNumber={page_number}&selectType=188&useType=188"
            response = self.session.get(url, timeout=30)
            if response.status_code != 200:
                logger.error(f"尚数网请求失败，状态码: {response.status_code}")
                return demands
            data = response.json()
            if data.get('code') != 200:
                return demands
            items = data.get('data', [])
            if not items:
                return demands
            for item in items:
                intro = item.get('sample_intro', '')
                clean = clean_html(intro)
                title = clean[:50] if clean else '无标题'
                demand = {
                    'source': '尚数网',
                    'title': title,
                    'description': clean,
                    'publish_date': item.get('publish_time', '') or item.get('publishTime', ''),
                    'url': item.get('firstUrl') or f"https://shangshuwang.cn/demand/{item.get('id', '')}",
                    'category': item.get('app_range', ''),
                }
                demands.append(demand)
            logger.info(f"尚数网第 {page_number} 页抓取 {len(demands)} 条")
        except Exception as e:
            logger.error(f"尚数网第 {page_number} 页失败: {e}")
        return demands

    # ---------- 数据源：北京国际大数据交易所（需Cookie，从环境变量读取） ----------
    def fetch_beijing(self) -> List[Dict]:
        all_demands = []
        page = 1
        page_size = 20
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bjidex.com/",
            "Origin": "https://www.bjidex.com",
            "Cookie": os.getenv('COOKIE_BEIJING', ''),
        }
        while True:
            try:
                url = f"https://mix.bjidex.com/oper-api/packet/officialList?demandTitle=&page={page}&size={page_size}"
                response = self.session.get(url, headers=headers, timeout=30)
                if response.status_code != 200:
                    logger.error(f"北京数交所请求失败: {response.status_code}")
                    break
                data = response.json()
                if data.get('code') != 200:
                    logger.error(f"北京数交所 API 错误: {data.get('msg')}")
                    break
                rows = data.get('rows', [])
                if not rows:
                    break
                if page == 1:
                    total = data.get('total', 0)
                    logger.info(f"北京数交所共 {total} 条需求")
                for item in rows:
                    if item.get('demandStatus') != 'PUBLISHED':
                        continue
                    demand = {
                        'source': '北京国际大数据交易所',
                        'title': item.get('demandTitle', '无标题'),
                        'description': item.get('demandDescribe', ''),
                        'publish_date': item.get('createTime', ''),
                        'url': f"https://mix.bjidex.com/demand/{item.get('id', '')}",
                        'category': item.get('demandType', ''),
                    }
                    all_demands.append(demand)
                logger.info(f"北京数交所第 {page} 页抓取 {len(rows)} 条")
                if len(rows) < page_size:
                    break
                page += 1
            except Exception as e:
                logger.error(f"北京数交所抓取第 {page} 页失败: {e}")
                break
        logger.info(f"北京数交所总计抓取 {len(all_demands)} 条")
        return all_demands

    # ---------- 数据源：上海数据交易所（需Cookie，从环境变量读取） ----------
    def fetch_shanghai(self) -> List[Dict]:
        all_demands = []
        page = 1
        page_size = 20
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://nidts.chinadep.com/",
            "Origin": "https://nidts.chinadep.com",
            "Cookie": os.getenv('COOKIE_SHANGHAI', ''),
        }
        while True:
            try:
                url = f"https://nidts.chinadep.com/daep/broker/product/visitor/pageProduct?pageSize={page_size}&pageNum={page}"
                response = self.session.get(url, headers=headers, timeout=30)
                if response.status_code != 200:
                    logger.error(f"上海数交所请求失败: {response.status_code}")
                    break
                data = response.json()
                if data.get('code') != 200:
                    logger.error(f"上海数交所 API 错误: {data.get('message')}")
                    break
                items = data.get('data', {}).get('list', [])
                if not items:
                    break
                if page == 1:
                    total = data.get('data', {}).get('total', 0)
                    logger.info(f"上海数交所共 {total} 条商品")
                for item in items:
                    title = item.get('dataName', '无标题')
                    description = item.get('dataContent', '')
                    supplier = item.get('supplierCompanyName', '')
                    publish_date = item.get('supplierProductReleaseTime', '')

                    demand = {
                        'source': '上海数据交易所',
                        'title': title,
                        'description': description,
                        'publish_date': publish_date,
                        'url': f"https://nidts.chinadep.com/product/{item.get('id', '')}",
                        'category': item.get('dataType', ''),
                        'supplier': supplier,
                    }
                    all_demands.append(demand)
                logger.info(f"上海数交所第 {page} 页抓取 {len(items)} 条")
                if len(items) < page_size:
                    break
                page += 1
            except Exception as e:
                logger.error(f"上海数交所抓取第 {page} 页失败: {e}")
                break
        logger.info(f"上海数交所总计抓取 {len(all_demands)} 条")
        return all_demands

    # ---------- 数据源：广州数据交易所（需Cookie + Access-Token，从环境变量读取） ----------
    def fetch_guangzhou(self) -> List[Dict]:
        """抓取广州数据交易所的需求列表"""
        all_demands = []
        page_no = 1
        page_size = 20

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://www.cantonde.com/",
            "Access-Token": os.getenv('ACCESS_TOKEN_GUANGZHOU', ''),
            "Cookie": os.getenv('COOKIE_GUANGZHOU', ''),
        }

        while True:
            try:
                payload = {
                    "xqlx": "",
                    "yycj": "",
                    "zt": "",
                    "ksrq": "",
                    "jsrq": "",
                    "sort": "",
                    "xqzt": "",
                    "pageNo": page_no,
                    "pageSize": page_size,
                }
                response = self.session.post(
                    "https://www.cantonde.com/si/xqdt/xqdtList",
                    headers=headers,
                    json=payload,
                    timeout=30
                )
                data = response.json()

                items = data.get('data', [])
                if not items:
                    for key in ['list', 'records', 'rows']:
                        if key in data.get('data', {}):
                            items = data['data'][key]
                            break

                if not items:
                    break

                for item in items:
                    raw_date = str(item.get('FBRQ', ''))
                    if len(raw_date) == 8:
                        publish_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
                    else:
                        publish_date = ''

                    demand = {
                        'source': '广州数据交易所',
                        'title': item.get('XQZT', '无标题'),
                        'description': item.get('XQSM', ''),
                        'publish_date': publish_date,
                        'url': f"https://www.cantonde.com/demand/{item.get('ID', '')}",
                        'category': item.get('XQLX_NOTE', ''),
                        'budget': item.get('CGYS', ''),
                        'scene': item.get('YYCJ_NOTE', ''),
                        'status': item.get('ZT_NOTE', ''),
                        'tags': item.get('XQBQ', ''),
                    }
                    all_demands.append(demand)

                if len(items) < page_size:
                    break
                page_no += 1
            except Exception as e:
                logger.error(f"广州数据交易所抓取失败: {e}")
                break

        return all_demands

    def fetch_hangzhou(self) -> List[Dict]:
        """抓取杭州数据交易所的需求列表（基于真实 cURL）"""
        all_demands = []
        page = 1
        page_size = 20

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "Connection": "keep-alive",
            "Referer": "https://h5.hzdex.cn/requirement?tab=hall",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Mobile Safari/537.36",
            "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Microsoft Edge";v="150"',
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": '"Android"',
            "Cookie": os.getenv('COOKIE_HANGZHOU', ''),
        }

        while True:
            try:
                url = f"https://h5.hzdex.cn/api/demands/page?demandClassify=DATA_DEMAND&demandName=&page={page}&pageSize={page_size}"
                response = self.session.get(url, headers=headers, timeout=30)

                if response.status_code != 200:
                    logger.error(f"杭州数交所请求失败: {response.status_code}")
                    break

                # 检查是否返回了 JSON
                if not response.text.strip().startswith('{'):
                    logger.error(f"杭州数交所返回非 JSON 数据: {response.text[:100]}")
                    break

                data = response.json()
                if not data.get('success'):
                    logger.error(f"杭州数交所 API 错误: {data}")
                    break

                items = data.get('data', {}).get('data', [])
                if not items:
                    break

                if page == 1:
                    total = data.get('data', {}).get('total', 0)
                    logger.info(f"杭州数交所共 {total} 条需求")

                for item in items:
                    demand = {
                        'source': '杭州数据交易所',
                        'title': item.get('demandName', '无标题'),
                        'description': item.get('desc', ''),
                        'publish_date': item.get('createdAt', ''),
                        'url': f"https://h5.hzdex.cn/demand/{item.get('id', '')}",
                        'category': item.get('demandType', ''),
                    }
                    all_demands.append(demand)

                logger.info(f"杭州数交所第 {page} 页抓取 {len(items)} 条")

                if len(items) < page_size:
                    break
                page += 1

            except Exception as e:
                logger.error(f"杭州数交所抓取第 {page} 页失败: {e}")
                break

        logger.info(f"杭州数交所总计抓取 {len(all_demands)} 条")
        return all_demands

    # ---------- 统一调度 ----------
    def fetch_all(self):
        all_demands = []
        all_demands.extend(self.fetch_shangshuwang())
        all_demands.extend(self.fetch_beijing())
        all_demands.extend(self.fetch_shanghai())
        all_demands.extend(self.fetch_guangzhou())
        all_demands.extend(self.fetch_hangzhou())
        if all_demands:
            self._save_demands(all_demands)
            self._export_csv()
        else:
            logger.warning("本次未抓取到任何数据")
        return all_demands

    def close(self):
        if hasattr(self, 'conn'):
            self.conn.close()

# ======================== 主程序入口 ========================
if __name__ == "__main__":
    crawler = ShangshuwangCrawler()
    try:
        crawler.fetch_all()
    finally:
        crawler.close()