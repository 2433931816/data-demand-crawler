import requests
import json
import sqlite3
import hashlib
import logging
import pandas as pd
import re
import time
from functools import wraps
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

# ======================== 重试装饰器 ========================
def retry_on_error(max_retries=3, delay=2, backoff=2, exceptions=(Exception,)):
    """
    自动重试装饰器
    :param max_retries: 最大重试次数
    :param delay: 初始延迟（秒）
    :param backoff: 延迟倍增因子
    :param exceptions: 需要捕获的异常类型
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            _delay = delay
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries:
                        logger.error(f"函数 {func.__name__} 重试 {max_retries} 次后仍失败: {e}")
                        raise
                    logger.warning(f"函数 {func.__name__} 第 {attempt+1} 次尝试失败: {e}，{_delay}秒后重试...")
                    time.sleep(_delay)
                    _delay *= backoff
            return None
        return wrapper
    return decorator

# ======================== 清洗辅助函数 ========================
def clean_html(raw: str) -> str:
    """去除HTML标签，提取纯文本"""
    if not raw:
        return ''
    try:
        text = html.unescape(raw)
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
            self.cursor.execute("SELECT created_at FROM demands WHERE id = ?", (demand_id,))
            existing = self.cursor.fetchone()
            if existing:
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
    @retry_on_error(max_retries=3, delay=2, exceptions=(requests.exceptions.RequestException,))
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
            response.raise_for_status()
            data = response.json()
            if data.get('code') != 200:
                return demands
            items = data.get('data', [])
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
        except requests.exceptions.RequestException as e:
            logger.error(f"尚数网第 {page_number} 页请求异常: {e}")
            raise
        except Exception as e:
            logger.error(f"尚数网第 {page_number} 页失败: {e}")
            raise
        return demands

    # ---------- 数据源：北京国际大数据交易所 ----------
    @retry_on_error(max_retries=3, delay=2, exceptions=(requests.exceptions.RequestException,))
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
                response.raise_for_status()
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
            except requests.exceptions.RequestException as e:
                logger.error(f"北京数交所第 {page} 页请求异常: {e}")
                raise
            except Exception as e:
                logger.error(f"北京数交所第 {page} 页失败: {e}")
                raise
        logger.info(f"北京数交所总计抓取 {len(all_demands)} 条")
        return all_demands

    # ---------- 数据源：上海数据交易所 ----------
    @retry_on_error(max_retries=3, delay=2, exceptions=(requests.exceptions.RequestException,))
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
                response.raise_for_status()
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
                    demand = {
                        'source': '上海数据交易所',
                        'title': item.get('dataName', '无标题'),
                        'description': item.get('dataContent', ''),
                        'publish_date': item.get('supplierProductReleaseTime', ''),
                        'url': f"https://nidts.chinadep.com/product/{item.get('id', '')}",
                        'category': item.get('dataType', ''),
                        'supplier': item.get('supplierCompanyName', ''),
                    }
                    all_demands.append(demand)
                logger.info(f"上海数交所第 {page} 页抓取 {len(items)} 条")
                if len(items) < page_size:
                    break
                page += 1
            except requests.exceptions.RequestException as e:
                logger.error(f"上海数交所第 {page} 页请求异常: {e}")
                raise
            except Exception as e:
                logger.error(f"上海数交所第 {page} 页失败: {e}")
                raise
        logger.info(f"上海数交所总计抓取 {len(all_demands)} 条")
        return all_demands

    # ---------- 数据源：广州数据交易所 ----------
    @retry_on_error(max_retries=3, delay=2, exceptions=(requests.exceptions.RequestException,))
    def fetch_guangzhou(self) -> List[Dict]:
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
                response.raise_for_status()
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
            except requests.exceptions.RequestException as e:
                logger.error(f"广州数交所第 {page_no} 页请求异常: {e}")
                raise
            except Exception as e:
                logger.error(f"广州数交所第 {page_no} 页失败: {e}")
                raise
        logger.info(f"广州数交所总计抓取 {len(all_demands)} 条")
        return all_demands

    # ---------- 数据源：杭州数据交易所 ----------
    @retry_on_error(max_retries=3, delay=2, exceptions=(requests.exceptions.RequestException,))
    def fetch_hangzhou(self) -> List[Dict]:
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
                response.raise_for_status()
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
            except requests.exceptions.RequestException as e:
                logger.error(f"杭州数交所第 {page} 页请求异常: {e}")
                raise
            except Exception as e:
                logger.error(f"杭州数交所第 {page} 页失败: {e}")
                raise
        logger.info(f"杭州数交所总计抓取 {len(all_demands)} 条")
        return all_demands

    # ---------- 数据源：深圳数据交易所（待审核通过后启用） ----------
    @retry_on_error(max_retries=3, delay=2, exceptions=(requests.exceptions.RequestException,))
    def fetch_shenzhen(self) -> List[Dict]:
        all_demands = []
        page = 1
        page_size = 12
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "Content-Type": "application/json",
            "Referer": "https://www.szdex.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": os.getenv('COOKIE_SHENZHEN', ''),
        }
        while True:
            try:
                url = "https://www.szdex.com/dmall/v1.0/sjsp/spgl/pageQuerySjspList"
                payload = {"page": page, "size": page_size}
                response = self.session.post(url, headers=headers, json=payload, timeout=30)
                response.raise_for_status()
                data = response.json()
                if data.get('code') != 200:
                    logger.error(f"深圳数交所 API 错误: {data.get('msg')}")
                    break
                items = data.get('data', {}).get('rows', [])
                if not items:
                    break
                if page == 1:
                    total = data.get('data', {}).get('totalCount', 0)
                    logger.info(f"深圳数交所共 {total} 条商品")
                for item in items:
                    raw_time = item.get('cjsj', '')
                    if raw_time:
                        try:
                            publish_date = datetime.fromtimestamp(int(raw_time) / 1000).strftime('%Y-%m-%d %H:%M:%S')
                        except:
                            publish_date = ''
                    else:
                        publish_date = ''
                    demand = {
                        'source': '深圳数据交易所',
                        'title': item.get('spMc', '无标题'),
                        'description': item.get('spms', ''),
                        'publish_date': publish_date,
                        'url': f"https://www.szdex.com/product/{item.get('id', '')}",
                        'category': item.get('spsjlxFlMc', ''),
                        'supplier': item.get('fbfQyMc', ''),
                        'price': item.get('xsjg', '面议'),
                        'scene': item.get('yycjMcs', ''),
                    }
                    all_demands.append(demand)
                logger.info(f"深圳数交所第 {page} 页抓取 {len(items)} 条")
                if len(items) < page_size:
                    break
                page += 1
            except requests.exceptions.RequestException as e:
                logger.error(f"深圳数交所第 {page} 页请求异常: {e}")
                raise
            except Exception as e:
                logger.error(f"深圳数交所第 {page} 页失败: {e}")
                raise
        logger.info(f"深圳数交所总计抓取 {len(all_demands)} 条")
        return all_demands

    def fetch_shandong(self) -> List[Dict]:
        """抓取山东数据交易平台的需求列表"""
        all_demands = []
        page = 0
        page_size = 9

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "Referer": "https://www.sddep.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": os.getenv('COOKIE_SHANDONG', ''),
        }

        while True:
            try:
                url = f"https://www.sddep.com/server/website-manager/noauth/website25/demandList?page={page}&size={page_size}"
                response = self.session.get(url, headers=headers, timeout=30)

                if response.status_code != 200:
                    logger.error(f"山东数交所请求失败: {response.status_code}")
                    break

                data = response.json()
                # 兼容 status 为字符串或数字
                if str(data.get('status')) != '200':
                    logger.error(f"山东数交所 API 错误: {data.get('message')}")
                    break

                items = data.get('list', [])
                if not items:
                    break

                if page == 0:
                    logger.info(f"山东数交所第一页返回 {len(items)} 条")

                for item in items:
                    demand = {
                        'source': '山东数据交易平台',
                        'title': item.get('name', '无标题'),
                        'description': item.get('resume', ''),
                        'publish_date': item.get('gmtCreate', ''),
                        'url': f"https://www.sddep.com/demand/{item.get('id', '')}",
                        'category': '',  # 可后续映射 type 或 dataType
                    }
                    all_demands.append(demand)

                logger.info(f"山东数交所第 {page + 1} 页抓取 {len(items)} 条")

                if len(items) < page_size:
                    break
                page += 1

            except Exception as e:
                logger.error(f"山东数交所抓取第 {page + 1} 页失败: {e}")
                break

        logger.info(f"山东数交所总计抓取 {len(all_demands)} 条")
        return all_demands

    @retry_on_error(max_retries=3, delay=2, exceptions=(requests.exceptions.RequestException,))
    def fetch_hunan(self) -> List[Dict]:
        """抓取湖南大数据交易所的数据产品列表"""
        all_demands = []
        page = 1
        page_size = 50

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "Authorization": "Bearer eyJ0eXAiOiJkVI1QiLCJhbGciOiJIUzI1NiJ9.eyJsb2dpblR5cGUiOiJsb2dpbilslmxVZ2luSWQiOiJzeXNFdXNlcjOyMDgwNTUxOTQyNTQyODM5ODEwliwicm5TdHliOiJIU0poZnlISXdidjIURE1jV3hIR09NakpHWUhGSUxvQylsnVzZXJJZCI6MjA4MDU1MTk0MjU0MjgzOTgxMH0.kQSAxdd4uqx14KHBh8VIFo2O4nsgg6M7TeZaDAw5qGU",
            "Cookie": "Admin-Token=eyJ0eXAiOiJkVI1QiLCJhbGciOiJIUzI1NiJ9.eyJsb2dpblR5cGUiOiJsb2dpbilslmxVZ2luSWQiOiJzeXNFdXNlcjOyMDgwNTUxOTQyNTQyODM5ODEwliwicm5TdHliOiJIU0poZnlISXdidjIURE1jV3hIR09NakpHWUhGSUxvQylsnVzZXJJZCI6MjA4MDU1MTk0MjU0MjgzOTgxMH0.kQSAxdd4uqx14KHBh8VIFo2O4nsgg6M7TeZaDAw5qGU; zH_CN",
            "Device-Type": "h5",
            "Referer": "https://www.hunandex.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        while True:
            try:
                url = f"https://trade.hunandex.com/prod-api/product/product/productData/list?pageNum={page}&pageSize={page_size}&isAsc=asc&orderByColumn=s.sort&name="
                response = self.session.get(url, headers=headers, timeout=30)

                if response.status_code != 200:
                    logger.error(f"湖南数交所请求失败: {response.status_code}")
                    break

                data = response.json()
                if data.get('code') != 200:
                    logger.error(f"湖南数交所 API 错误: {data.get('msg')}")
                    break

                items = data.get('data', {}).get('rows', [])
                if not items:
                    break

                if page == 1:
                    total = data.get('data', {}).get('total', 0)
                    logger.info(f"湖南数交所共 {total} 条数据产品")

                for item in items:
                    demand = {
                        'source': '湖南大数据交易所',
                        'title': item.get('name', '无标题'),
                        'description': item.get('productIntroduce', ''),
                        'publish_date': item.get('releaseTime', ''),
                        'url': f"https://www.hunandex.com/product/{item.get('id', '')}",
                        'category': item.get('scenariosNames', '') or item.get('sectorName', ''),
                        'supplier': item.get('supplierName', ''),
                        'price': item.get('price', '面议'),
                        'product_type': item.get('productType', ''),
                    }
                    all_demands.append(demand)

                logger.info(f"湖南数交所第 {page} 页抓取 {len(items)} 条")

                if len(items) < page_size:
                    break
                page += 1

            except Exception as e:
                logger.error(f"湖南数交所抓取第 {page} 页失败: {e}")
                break

        logger.info(f"湖南数交所总计抓取 {len(all_demands)} 条")
        return all_demands

    @retry_on_error(max_retries=3, delay=2, exceptions=(requests.exceptions.RequestException,))
    def fetch_zhengzhou(self) -> List[Dict]:
        """抓取郑州数据交易中心的需求列表"""
        all_demands = []
        seen_ids = set()
        page = 0
        page_size = 10
        max_pages = 3  # 安全限制

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "Content-Type": "application/json",
            "Origin": "https://market.zzbdex.com",
            "Referer": "https://market.zzbdex.com/demand",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": os.getenv('COOKIE_ZHENGZHOU', ''),
        }

        while page < max_pages:
            try:
                url = "https://market.zzbdex.com/data-deal-admin/demandInfo/queryDemandHallPage"
                payload = {
                    "current": page,
                    "size": page_size,
                }
                response = self.session.post(url, headers=headers, json=payload, timeout=30)

                if response.status_code != 200:
                    logger.error(f"郑州数交所请求失败: {response.status_code}")
                    break

                data = response.json()
                if data.get('code') != 0:
                    logger.error(f"郑州数交所 API 错误: {data.get('msg')}")
                    break

                items = data.get('data', {}).get('records', [])

                if page == 0:
                    total = data.get('data', {}).get('total', 0)
                    if total > 0:
                        logger.info(f"郑州数交所共 {total} 条需求")

                if not items:
                    break

                added_count = 0
                for item in items:
                    demand_id = item.get('demandId', '')
                    if demand_id in seen_ids:
                        continue
                    seen_ids.add(demand_id)

                    budget_start = item.get('demandBudgetStart', '')
                    budget_end = item.get('demandBudgetEnd', '')
                    budget = f"{budget_start} - {budget_end}" if (budget_start or budget_end) else '面议'

                    demand = {
                        'source': '郑州数据交易中心',
                        'title': item.get('demandName', '无标题').replace('\n', ' '),
                        'description': item.get('demandDescription', ''),
                        'publish_date': item.get('releaseTime', ''),
                        'url': f"https://market.zzbdex.com/demand/{demand_id}",
                        'category': item.get('sceneName', ''),
                        'supplier': item.get('demandCName', ''),
                        'budget': budget,
                        'contact': item.get('contacts', ''),
                        'phone': item.get('contactsPhone', ''),
                        'scene_desc': item.get('appScenariosDescription', ''),
                    }
                    all_demands.append(demand)
                    added_count += 1

                logger.info(f"郑州数交所第 {page + 1} 页抓取 {len(items)} 条，新增 {added_count} 条")

                if added_count == 0 or len(items) < page_size:
                    break

                page += 1

            except Exception as e:
                logger.error(f"郑州数交所抓取第 {page + 1} 页失败: {e}")
                break

        logger.info(f"郑州数交所总计抓取 {len(all_demands)} 条")
        return all_demands

    @retry_on_error(max_retries=3, delay=2, exceptions=(requests.exceptions.RequestException,))
    def fetch_guiyang(self) -> List[Dict]:
        """抓取贵阳大数据交易所的需求列表"""
        all_demands = []
        page = 1
        page_size = 20  # 可尝试调整为 20 或 50，看接口是否支持

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "Referer": "https://www.gzdex.com.cn/need/list",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": os.getenv('COOKIE_GUIYANG', ''),
        }

        while True:
            try:
                url = f"https://www.gzdex.com.cn/apaas/backmgt/demand/hall/list?page={page}&pageSize={page_size}&search=&order=-1&productType="
                response = self.session.get(url, headers=headers, timeout=30)

                if response.status_code != 200:
                    logger.error(f"贵阳数交所请求失败: {response.status_code}")
                    break

                data = response.json()
                if data.get('success') != 1:
                    logger.error(f"贵阳数交所 API 错误: {data.get('errMsg')}")
                    break

                items = data.get('data', {}).get('list', [])
                if not items:
                    break

                if page == 1:
                    logger.info(f"贵阳数交所当前页 {len(items)} 条")

                for item in items:
                    demand = {
                        'source': '贵阳大数据交易所',
                        'title': item.get('title', '无标题'),
                        'description': item.get('describe', ''),
                        'publish_date': item.get('releaseTimeStr', ''),
                        'url': f"https://www.gzdex.com.cn/demand/{item.get('id', '')}",
                        'category': item.get('productClassifyName', ''),
                        'supplier': item.get('need', ''),
                        'price': item.get('capitalBudget', '面议'),
                    }
                    all_demands.append(demand)

                logger.info(f"贵阳数交所第 {page} 页抓取 {len(items)} 条")

                if len(items) < page_size:
                    break
                page += 1

            except Exception as e:
                logger.error(f"贵阳数交所抓取第 {page} 页失败: {e}")
                break

        logger.info(f"贵阳数交所总计抓取 {len(all_demands)} 条")
        return all_demands

    @retry_on_error(max_retries=3, delay=2, exceptions=(requests.exceptions.RequestException,))
    def fetch_huadong(self) -> List[Dict]:
        """抓取华东江苏大数据交易中心的需求列表"""
        all_demands = []
        seen_ids = set()
        page = 1
        page_size = 50
        total_pages = None

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Origin": "http://www.hddatapay.com",
            "Referer": "http://www.hddatapay.com/viewJsp/demand.jsp?v=12.8",
            "User-Agent": "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Mobile Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Cookie": os.getenv('COOKIE_HUADONG', ''),
        }

        while True:
            try:
                url = "http://www.hddatapay.com/api/demandInfoList"
                payload = {
                    "pageNum": page,
                    "pageSize": page_size,
                }
                response = self.session.post(url, headers=headers, data=payload, timeout=30)

                if response.status_code != 200:
                    logger.error(f"华东数交请求失败: {response.status_code}")
                    break

                data = response.json()
                if data.get('code') != '0':
                    logger.error(f"华东数交 API 错误: {data.get('msg')}")
                    break

                items = data.get('data', {}).get('demandInfoCellDtoList', [])

                # 第一页获取总数并计算总页数
                if page == 1:
                    total = data.get('data', {}).get('total', 0)
                    if total == 0:
                        logger.warning("华东数交返回 total=0，无数据")
                        break
                    total_pages = (total + page_size - 1) // page_size
                    logger.info(f"华东数交共 {total} 条需求，共 {total_pages} 页")

                # 如果当前页没有数据，停止
                if not items:
                    break

                # 解析并去重
                added_count = 0
                for item in items:
                    demand_id = item.get('id', '')
                    if demand_id in seen_ids:
                        continue
                    seen_ids.add(demand_id)

                    raw_time = item.get('issueTime', '')
                    if raw_time:
                        try:
                            publish_date = datetime.fromtimestamp(int(raw_time) / 1000).strftime('%Y-%m-%d %H:%M:%S')
                        except:
                            publish_date = ''
                    else:
                        publish_date = ''

                    demand = {
                        'source': '华东江苏大数据交易中心',
                        'title': item.get('demandName', '无标题'),
                        'description': item.get('info', ''),
                        'publish_date': publish_date,
                        'url': f"http://www.hddatapay.com/demand/{demand_id}",
                        'category': item.get('scene', ''),
                        'supplier': item.get('demandSide', ''),
                        'price': item.get('purchaseBudget', '面议'),
                        'coverage': item.get('coverRange', ''),
                        'demand_type': item.get('demandType', ''),
                    }
                    all_demands.append(demand)
                    added_count += 1

                logger.info(f"华东数交第 {page} 页抓取 {len(items)} 条，新增 {added_count} 条")

                # ===== 停止条件 =====
                # 1. 如果当前页新增为 0，说明后续都是重复数据
                if added_count == 0:
                    logger.info("后续页面无新增数据，停止抓取")
                    break

                # 2. 如果已经达到总页数，停止
                if total_pages and page >= total_pages:
                    break

                # 3. 如果当前页数据少于 page_size，说明是最后一页
                if len(items) < page_size:
                    break

                page += 1

            except Exception as e:
                logger.error(f"华东数交抓取第 {page} 页失败: {e}")
                break

        logger.info(f"华东数交总计抓取 {len(all_demands)} 条（去重后）")
        return all_demands

    # ---------- 统一调度 ----------
    def fetch_all(self):
        all_demands = []
        fetch_functions = [
            ('尚数网', self.fetch_shangshuwang),
            ('北京数交所', self.fetch_beijing),
            ('上海数交所', self.fetch_shanghai),
            ('广州数交所', self.fetch_guangzhou),
            ('杭州数交所', self.fetch_hangzhou),
            # ('深圳数交所', self.fetch_shenzhen),  # 待审核通过后启用
            ('山东数交所', self.fetch_shandong),
            ('湖南数交所', self.fetch_hunan),
            ('郑州数交所', self.fetch_zhengzhou),
            ('华东数交所', self.fetch_huadong)

        ]
        for name, func in fetch_functions:
            try:
                logger.info(f"开始抓取 {name}...")
                demands = func()
                all_demands.extend(demands)
                logger.info(f"{name} 抓取完成，共 {len(demands)} 条")
            except Exception as e:
                logger.error(f"{name} 抓取失败: {e}")
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