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
        # 1. Session 初始化
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        })

        # 2. 加载配置文件
        import yaml
        with open('config.yaml', 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

        # 3. 从配置读取深圳文章链接
        self.shenzhen_article_urls = self.config.get('shenzhen', {}).get('article_urls', [])

        # 4. 初始化数据库
        self._init_db()

        def _load_parsed_articles(self) -> set:  # Akiyamadao
            """加载已解析的文章链接"""
            try:
                with open('parsed_articles.txt', 'r', encoding='utf-8') as f:
                    return set(line.strip() for line in f if line.strip())
            except FileNotFoundError:
                return set()

        def _save_parsed_article(self, url: str):  # Akiyamadao
            """保存已解析的文章链接"""
            with open('parsed_articles.txt', 'a', encoding='utf-8') as f:
                f.write(url + '\n')
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
                updated_at TEXT,
                source_priority INTEGER DEFAULT 2
            )
        ''')
        # 为已有数据库添加 source_priority 字段（如果不存在）
        try:
            self.cursor.execute('ALTER TABLE demands ADD COLUMN source_priority INTEGER DEFAULT 2')
        except sqlite3.OperationalError:
            pass  # 字段已存在，忽略
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
            # 获取 source_priority，默认值为 2（网站来源）
            source_priority = demand.get('source_priority', 2)

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
                        updated_at = ?,
                        source_priority = ?
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
                    source_priority,
                    demand_id
                ))
            else:
                self.cursor.execute('''
                    INSERT INTO demands
                    (id, source, title, description, category, publish_date, url, raw_data, created_at, updated_at, source_priority)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    now,
                    source_priority
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

                # ✅ 修复 url：优先使用 firstUrl，但如果是内部路径则用 id 构造完整链接
                first_url = item.get('firstUrl', '')
                if first_url and first_url.startswith('http'):
                    demand_url = first_url
                else:
                    # 直接用 id 构造尚数网详情页链接
                    demand_url = f"https://shangshuwang.cn/demand/{item.get('id', '')}"

                demand = {
                    'source': '尚数网',
                    'title': title,
                    'description': clean,
                    'publish_date': item.get('publish_time', '') or item.get('publishTime', ''),
                    'url': demand_url,
                    'category': item.get('app_range', ''),
                    'source_priority': 2,
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
                        'source_priority': 2,
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
        """抓取上海数据交易所的需求列表"""
        all_demands = []
        page = 1
        page_size = 20

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "Content-Type": "application/json;charset=UTF-8",
            "Referer": "https://nidts.chinadep.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": os.getenv('COOKIE_SHANGHAI', ''),
        }

        while True:
            try:
                url = "https://nidts.chinadep.com/dex-api/demand-bridge/demand/hall/list"
                payload = {
                    "pageNum": page,
                    "pageSize": page_size,
                }
                response = self.session.post(url, headers=headers, json=payload, timeout=30)

                if response.status_code != 200:
                    logger.error(f"上海数交所需求请求失败: {response.status_code}")
                    break

                data = response.json()
                if data.get('code') != 200:
                    logger.error(f"上海数交所需求 API 错误: {data.get('message')}")
                    break

                items = data.get('data', {}).get('list', [])
                if not items:
                    break

                if page == 1:
                    total = data.get('data', {}).get('total', 0)
                    logger.info(f"上海数交所需求共 {total} 条")

                for item in items:
                    demand = {
                        'source': '上海数据交易所',
                        'title': item.get('title', '无标题'),
                        'description': item.get('description', ''),
                        'publish_date': item.get('createTime', ''),
                        'url': f"https://nidts.chinadep.com/demand/{item.get('id', '')}",
                        'category': item.get('scene', ''),
                        'budget': item.get('priceCap', 0),
                        'keywords': ', '.join(item.get('keywords', [])),
                        'status': item.get('status', ''),
                        'source_priority': 2,
                    }
                    all_demands.append(demand)

                logger.info(f"上海数交所需求第 {page} 页抓取 {len(items)} 条")

                if len(items) < page_size:
                    break
                page += 1

            except Exception as e:
                logger.error(f"上海数交所需求抓取第 {page} 页失败: {e}")
                break

        logger.info(f"上海数交所需求总计抓取 {len(all_demands)} 条")
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
                        'source_priority': 2,
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
                        'source_priority': 2,
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

    # ---------- 数据源：深数网微信公众号 ----------
    def _load_parsed_article(self) -> set:
        """
        加载已解析的文章链接"""
        try:
            with open('parsed_articles.txt', 'r', encoding='utf-8-sig') as f:
                return set(line.strip() for line in f if line.strip())
        except FileNotFoundError:
            return set()

    def _save_parsed_article(self, url: str):
        """
        保存已解析的文章链接"""
        with open('parsed_articles.txt', 'a', encoding='utf-8-sig') as f:
            f.write(url + '\n')

    def fetch_shenzhen(self) -> List[Dict]:
        """
        抓取深圳数据交易所公众号发布的需求列表
        支持多种需求格式：01/02、采购需求1/2、需求一/二
        """
        all_demands = []

        # 加载已解析的文章链接
        parsed_urls = self._load_parsed_article()

        # 从配置读取文章链接
        article_urls = self.shenzhen_article_urls
        print(f"article_urls: {article_urls}")
        if not article_urls:
            logger.warning("深圳数交所文章链接列表为空，请检查 config.yaml")
            return all_demands

        wechat_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        }

        for url in article_urls:
            # 检查是否已解析
            if url in parsed_urls:
                logger.info(f"跳过已解析文章: {url}")
                continue

            try:
                response = self.session.get(url, headers=wechat_headers, timeout=30)
                if response.status_code != 200:
                    logger.error(f"深数所公众号文章请求失败: {url}, 状态码: {response.status_code}")
                    continue

                soup = BeautifulSoup(response.text, 'html.parser')
                content = soup.find('div', class_='rich_media_content')

                if not content:
                    continue

                clean_text = content.get_text(separator='\n', strip=True)

                if len(clean_text) < 50:
                    continue

                text = clean_text
                logger.info(f"文章总长度: {len(text)} 字符")

                import re

                # ===== 方法1：匹配 "**01**"、"**02**" 格式 =====
                blocks = re.split(r'\*\*0[1-9]\*\*', text)

                # ===== 方法2：匹配 "采购需求1"、"采购需求2" 格式 =====
                if len(blocks) <= 1:
                    blocks = re.split(r'(?:采购需求|需求发布)[：:]?\s*(?=\d)', text)
                    if len(blocks) <= 1:
                        blocks = re.split(r'(?:采购需求|需求发布)[：:]?\s*', text)
                    if blocks and not blocks[0].strip():
                        blocks = blocks[1:]

                # ===== 方法3：匹配 "需求一"、"需求二" 格式 =====
                if len(blocks) <= 1:
                    blocks = re.split(r'需求[一二三四五六七八九十]+[、，]?\s*', text)
                    if blocks and not blocks[0].strip():
                        blocks = blocks[1:]

                # ===== 方法4：匹配 "01"、"02"（无加粗）格式 =====
                if len(blocks) <= 1:
                    blocks = re.split(r'\n\s*(0[1-9])\s*\n', text)
                    if len(blocks) > 1:
                        filtered = []
                        for b in blocks:
                            if b.strip() in ['01', '02', '03', '04', '05', '06', '07', '08', '09']:
                                continue
                            if b.strip():
                                filtered.append(b)
                        blocks = filtered

                # 如果没有匹配到任何格式，按段落分割取包含关键词的段落
                if len(blocks) <= 1:
                    lines = text.split('\n')
                    current_block = []
                    for line in lines:
                        line = line.strip()
                        if any(kw in line for kw in ['产品类型', '产品描述', '数据要求', '需求说明']):
                            if current_block:
                                blocks.append('\n'.join(current_block))
                            current_block = [line]
                        elif current_block:
                            current_block.append(line)
                    if current_block:
                        blocks.append('\n'.join(current_block))

                demand_count = 0
                for block in blocks:
                    if not block or len(block.strip()) < 10:
                        continue

                    lines = block.strip().split('\n')

                    # 提取标题
                    # ===== 优化后的标题提取 =====
                    title = ''
                    full_block = '\n'.join(lines)
                    full_block = full_block.replace('**', '').replace('*', '')

                    # 1. 优先提取 "需求说明" 前面的内容作为标题
                    title_match = re.search(r'(.+?)(?:需求说明[：:]|数据要求[：:]|$)', full_block, re.DOTALL)
                    if title_match:
                        title = title_match.group(1).strip()
                        title = title.replace('**', '').replace('*', '').strip()
                        # 如果标题包含"产品类型"，则忽略，继续往下找
                        if '产品类型' in title:
                            title = ''

                    # 2. 如果上面没匹配到或匹配到的是"产品类型"，取前两行
                    if not title or '产品类型' in title:
                        for line in lines[:5]:
                            line_clean = line.strip().replace('**', '').replace('*', '').strip()
                            if line_clean and len(line_clean) > 3:
                                # 跳过包含"产品类型"、"数据要求"等关键词的行
                                if any(skip in line_clean for skip in ['产品类型', '数据要求', '需求说明', '覆盖范围']):
                                    continue
                                title = line_clean
                                break

                    # 3. 如果还是没提取到，取第一行非空内容
                    if not title:
                        for line in lines[:3]:
                            line_clean = line.strip().replace('**', '').replace('*', '').strip()
                            if line_clean and len(line_clean) > 3:
                                title = line_clean
                                break

                    if not title:
                        continue

                    # 如果标题包含"产品类型"，用后面的内容替代
                    if '产品类型' in title:
                        for line in lines:
                            line_clean = line.strip().replace('**', '').replace('*', '').strip()
                            if line_clean and len(line_clean) > 3 and '产品类型' not in line_clean:
                                if any(kw in line_clean for kw in ['数据集', '需求', '训练']):
                                    title = line_clean
                                    break
                    if not title:
                        continue

                    full_block = '\n'.join(lines)
                    full_block = full_block.replace('**', '').replace('*', '')

                    # 提取产品描述
                    desc_match = re.search(
                        r'产品描述[：:]\s*(.*?)(?=数据覆盖范围|产品类型|交付形式|计费方式|数据要求|需求说明|$)',
                        full_block, re.DOTALL)
                    description = desc_match.group(1).strip() if desc_match else ''

                    # 提取需求说明
                    if not description:
                        desc_match = re.search(r'需求说明[：:]\s*(.*?)(?=数据要求|数据覆盖范围|产品类型|$)', full_block,
                                               re.DOTALL)
                        description = desc_match.group(1).strip() if desc_match else ''

                    # 提取数据覆盖范围
                    scope_match = re.search(r'数据覆盖范围[：:]\s*(.*?)(?=数据更新频率|交付形式|产品类型|$)', full_block,
                                            re.DOTALL)
                    scope = scope_match.group(1).strip() if scope_match else ''

                    # 提取交付形式
                    delivery_match = re.search(r'交付形式[：:]\s*(.*?)(?=计费方式|产品类型|$)', full_block, re.DOTALL)
                    delivery = delivery_match.group(1).strip() if delivery_match else ''

                    # 提取数据要求
                    req_match = re.search(r'数据要求[：:]\s*(.*?)(?=需求说明|数据覆盖范围|产品类型|$)', full_block,
                                          re.DOTALL)
                    detailed_req = req_match.group(1).strip() if req_match else ''

                    # 产品类型
                    type_match = re.search(r'产品类型[：:]\s*(.*?)(?=产品描述|数据覆盖范围|$)', full_block, re.DOTALL)
                    product_type = type_match.group(1).strip() if type_match else ''

                    if product_type:
                        title = f"{product_type} - {title}" if title else product_type

                    title = title.replace('**', '').replace('*', '').strip()
                    if len(title) > 60:
                        title = title[:60] + '...'

                    if title and not any(skip in title for skip in ['深圳数据交易所', '声明', '扫码', '扫码关注']):
                        desc_parts = []
                        if description:
                            desc_parts.append(description)
                        if scope:
                            desc_parts.append(f"覆盖范围: {scope}")
                        if delivery:
                            desc_parts.append(f"交付形式: {delivery}")
                        if detailed_req:
                            desc_parts.append(f"数据要求: {detailed_req[:200]}")

                        final_desc = '\n'.join(desc_parts) if desc_parts else ''

                        demand = {
                            'source': '深圳数据交易所',
                            'title': title,
                            'description': final_desc[:800] if final_desc else '',
                            'detailed_requirements': detailed_req[:500] if detailed_req else '',
                            'publish_date': '',
                            'url': url,
                            'category': product_type,
                            'source_priority': 1,
                        }
                        all_demands.append(demand)
                        demand_count += 1
                        logger.info(f"从深数所公众号提取需求: {title}")

                logger.info(f"本篇文章提取到 {demand_count} 条需求")

                # 解析成功后，标记为已解析
                self._save_parsed_article(url)
                parsed_urls.add(url)

            except Exception as e:
                logger.error(f"深数所公众号文章解析失败: {url}, 错误: {e}")

        logger.info(f"深圳数据交易所公众号抓取完成，发现 {len(all_demands)} 条需求")
        return all_demands

    def fetch_beijing_wechat(self) -> List[Dict]:
        """
        抓取北京国际大数据交易所公众号发布的需求/征集信息
        支持：征集通知、数据寻源、数据需求清单等
        """
        all_demands = []

        # 加载已解析的文章链接
        parsed_urls = self._load_parsed_article()

        # 从配置读取文章链接
        article_urls = self.config.get('beijing_wechat', {}).get('article_urls', [])
        print(f"article_urls: {article_urls}")
        if not article_urls:
            logger.warning("北京数交所公众号文章链接列表为空，请检查 config.yaml")
            return all_demands

        wechat_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        }

        for url in article_urls:
            # 检查是否已解析
            if url in parsed_urls:
                logger.info(f"跳过已解析文章: {url}")
                continue

            try:
                response = self.session.get(url, headers=wechat_headers, timeout=30)
                if response.status_code != 200:
                    logger.error(f"北京数交所公众号文章请求失败: {url}, 状态码: {response.status_code}")
                    continue

                soup = BeautifulSoup(response.text, 'html.parser')
                content = soup.find('div', class_='rich_media_content')

                if not content:
                    continue

                clean_text = content.get_text(separator='\n', strip=True)

                if len(clean_text) < 50:
                    continue

                text = clean_text
                logger.info(f"文章总长度: {len(text)} 字符")

                import re

                # ===== 方法1：匹配 "**01**"、"**02**" 格式 =====
                blocks = re.split(r'\*\*0[1-9]\*\*', text)

                # ===== 方法2：匹配 "征集方向一"、"需求一" 等 =====
                if len(blocks) <= 1:
                    blocks = re.split(r'(?:征集方向|需求)[一二三四五六七八九十]+[、，]?\s*', text)
                    if blocks and not blocks[0].strip():
                        blocks = blocks[1:]

                # ===== 方法3：匹配 "一、"、"二、" 或 "1."、"2." =====
                if len(blocks) <= 1:
                    blocks = re.split(r'\n\s*[一二三四五六七八九十]+[、.．]\s*', text)
                    if blocks and not blocks[0].strip():
                        blocks = blocks[1:]

                if len(blocks) <= 1:
                    blocks = re.split(r'\n\s*[1-9][、.．]\s*', text)
                    if blocks and not blocks[0].strip():
                        blocks = blocks[1:]

                # ===== 方法4：匹配 "01"、"02"（无加粗）格式 =====
                if len(blocks) <= 1:
                    blocks = re.split(r'\n\s*(0[1-9])\s*\n', text)
                    if len(blocks) > 1:
                        filtered = []
                        for b in blocks:
                            if b.strip() in ['01', '02', '03', '04', '05', '06', '07', '08', '09']:
                                continue
                            if b.strip():
                                filtered.append(b)
                        blocks = filtered

                # 如果没有匹配到任何格式，按段落分割取包含关键词的段落
                if len(blocks) <= 1:
                    lines = text.split('\n')
                    current_block = []
                    for line in lines:
                        line = line.strip()
                        if any(kw in line for kw in ['征集方向', '需求方向', '征集内容', '需求内容', '数据需求']):
                            if current_block:
                                blocks.append('\n'.join(current_block))
                            current_block = [line]
                        elif current_block:
                            current_block.append(line)
                    if current_block:
                        blocks.append('\n'.join(current_block))

                # ===== 提取联系方式（北京特有） =====
                contact = ''
                contact_patterns = [
                    r'联系方式?[：:]\s*(.*?)(?=$)',
                    r'联系人[：:]\s*([^\n]+)',
                    r'电话[：:]\s*([^\n]+)',
                ]
                for pattern in contact_patterns:
                    match = re.search(pattern, text, re.DOTALL)
                    if match:
                        contact = match.group(1).strip()
                        break

                phone = ''
                phone_match = re.search(r'\d{11}', contact) if contact else None
                if phone_match:
                    phone = phone_match.group(0)
                if not phone:
                    phone_match = re.search(r'\d{3,4}[- ]?\d{7,8}', contact) if contact else None
                    if phone_match:
                        phone = phone_match.group(0)

                demand_count = 0
                for block in blocks:
                    if not block or len(block.strip()) < 10:
                        continue

                    lines = block.strip().split('\n')

                    # ===== 提取标题（与深圳逻辑一致） =====
                    title = ''
                    full_block = '\n'.join(lines)
                    full_block = full_block.replace('**', '').replace('*', '')

                    # 1. 优先提取 "需求说明"/"征集内容" 前面的内容作为标题
                    title_match = re.search(r'(.+?)(?:需求说明[：:]|征集内容[：:]|数据要求[：:]|$)', full_block, re.DOTALL)
                    if title_match:
                        title = title_match.group(1).strip()
                        title = title.replace('**', '').replace('*', '').strip()
                        # 如果标题包含"产品类型"或类似词，则忽略
                        if any(skip in title for skip in ['产品类型', '数据要求', '需求说明', '征集要求']):
                            title = ''

                    # 2. 如果上面没匹配到，取前两行
                    if not title:
                        for line in lines[:5]:
                            line_clean = line.strip().replace('**', '').replace('*', '').strip()
                            if line_clean and len(line_clean) > 3:
                                if any(skip in line_clean for skip in
                                       ['产品类型', '数据要求', '需求说明', '征集要求', '覆盖范围']):
                                    continue
                                title = line_clean
                                break

                    # 3. 如果还是没提取到，取第一行非空内容
                    if not title:
                        for line in lines[:3]:
                            line_clean = line.strip().replace('**', '').replace('*', '').strip()
                            if line_clean and len(line_clean) > 3:
                                title = line_clean
                                break

                    if not title:
                        continue

                    full_block = '\n'.join(lines)
                    full_block = full_block.replace('**', '').replace('*', '')

                    # ===== 提取征集内容/需求说明（与深圳逻辑一致） =====
                    desc_match = re.search(
                        r'(?:征集内容|需求说明)[：:]\s*(.*?)(?=征集要求|数据要求|联系方式|$)',
                        full_block, re.DOTALL)
                    description = desc_match.group(1).strip() if desc_match else ''

                    if not description:
                        desc_match = re.search(
                            r'(?:需求方向|征集方向)[：:]\s*(.*?)(?=征集要求|数据要求|联系方式|$)',
                            full_block, re.DOTALL)
                        description = desc_match.group(1).strip() if desc_match else ''

                    # ===== 提取征集要求/数据要求（与深圳逻辑一致） =====
                    req_match = re.search(
                        r'(?:征集要求|数据要求)[：:]\s*(.*?)(?=联系方式|$)',
                        full_block, re.DOTALL)
                    detailed_req = req_match.group(1).strip() if req_match else ''

                    # ===== 判断文章类型（北京特有） =====
                    article_type = '数据需求'
                    text_preview = text[:500]
                    if '征集通知' in text_preview:
                        article_type = '征集通知'
                    elif '数据寻源' in text_preview or '数据需求' in text_preview:
                        article_type = '数据寻源'
                    elif '需求公告' in text_preview:
                        article_type = '需求公告'
                    elif '图像数据' in text_preview or '数据集' in text_preview:
                        article_type = '数据需求清单'

                    title = title.replace('**', '').replace('*', '').strip()
                    if len(title) > 60:
                        title = title[:60] + '...'

                    if title and not any(
                            skip in title for skip in ['北京国际大数据交易所', '声明', '扫码', '扫码关注']):
                        desc_parts = []
                        if description:
                            desc_parts.append(description)
                        if detailed_req:
                            desc_parts.append(f"要求: {detailed_req[:200]}")
                        if contact:
                            desc_parts.append(f"联系方式: {contact}")

                        final_desc = '\n'.join(desc_parts) if desc_parts else ''

                        demand = {
                            'source': '北京国际大数据交易所-公众号',
                            'title': title,
                            'description': final_desc[:800] if final_desc else '',
                            'detailed_requirements': detailed_req[:500] if detailed_req else '',
                            'publish_date': '',
                            'url': url,
                            'category': article_type,
                            'phone': phone,
                            'source_priority': 1,
                        }
                        all_demands.append(demand)
                        demand_count += 1
                        logger.info(f"从北京数交所公众号提取需求: {title}")

                logger.info(f"本篇文章提取到 {demand_count} 条需求")

                # 解析成功后，标记为已解析
                self._save_parsed_article(url)
                parsed_urls.add(url)

            except Exception as e:
                logger.error(f"北京数交所公众号文章解析失败: {url}, 错误: {e}")

        logger.info(f"北京国际大数据交易所公众号抓取完成，发现 {len(all_demands)} 条需求")
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
                        'source_priority': 2,
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
        """抓取湖南大数据交易所的需求列表"""
        all_demands = []
        page = 1
        page_size = 20

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "Authorization": os.getenv('AUTHORIZATION_HUNAN', ''),
            "Referer": "https://trade.hunandex.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": os.getenv('COOKIE_HUNAN', ''),
        }

        while True:
            try:
                # 移除不可靠的排序参数，只保留分页
                url = f"https://trade.hunandex.com/prod-api/product/product/demandProductReg/findDemandList?pageNum={page}&pageSize={page_size}"
                response = self.session.get(url, headers=headers, timeout=30)

                if response.status_code != 200:
                    logger.error(f"湖南数交所需求请求失败: {response.status_code}")
                    break

                data = response.json()
                if data.get('code') != 200:
                    logger.error(f"湖南数交所需求 API 错误: {data.get('msg')}")
                    break

                items = data.get('data', {}).get('rows', [])
                if not items:
                    break

                if page == 1:
                    total = data.get('data', {}).get('total', 0)
                    logger.info(f"湖南数交所需求共 {total} 条")

                for item in items:
                    demand = {
                        'source': '湖南大数据交易所',
                        'title': item.get('synopsis', '无标题'),
                        'description': item.get('demandDetail', ''),
                        'publish_date': item.get('createTime', ''),
                        'url': f"https://www.hunandex.com/demand/{item.get('id', '')}",
                        'category': '',
                        'supplier': item.get('companyName', ''),
                        'budget': item.get('budgetAmount', '面议'),
                        'status': item.get('claimStatus', ''),
                        'views': item.get('viewCount', 0),
                        'source_priority': 2,
                    }
                    all_demands.append(demand)

                logger.info(f"湖南数交所需求第 {page} 页抓取 {len(items)} 条")

                if len(items) < page_size:
                    break
                page += 1

            except Exception as e:
                logger.error(f"湖南数交所需求抓取第 {page} 页失败: {e}")
                break

        logger.info(f"湖南数交所需求总计抓取 {len(all_demands)} 条")
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
                        'source_priority': 2,
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
                        'source_priority': 2,
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
        page_size = 100
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
                        'source_priority': 2,
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

    @retry_on_error(max_retries=3, delay=2, exceptions=(requests.exceptions.RequestException,))
    def fetch_fujian(self) -> List[Dict]:
        """抓取福建大数据交易所的需求列表"""
        all_demands = []
        page = 1
        page_size = 20

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "Referer": "https://trade.fjbdtex.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": os.getenv('COOKIE_FUJIAN', ''),
        }

        while True:
            try:
                url = f"https://trade.fjbdtex.com/tywpt-api/api/data-portal-center/portal/hwDemand/list?pageNo={page}&pageSize={page_size}&dataScene=&demandScene=&industryInvolved=&sortType=1&sort="
                response = self.session.get(url, headers=headers, timeout=30)

                if response.status_code != 200:
                    logger.error(f"福建数交所请求失败: {response.status_code}")
                    break

                data = response.json()
                if data.get('code') != 200:
                    logger.error(f"福建数交所 API 错误: {data.get('msg')}")
                    break

                items = data.get('result', {}).get('records', [])
                total = data.get('result', {}).get('total', 0)

                if page == 1:
                    if total == 0:
                        logger.info("福建数交所需求广场当前无数据")
                        break
                    logger.info(f"福建数交所共 {total} 条需求")

                if not items:
                    break

                for item in items:
                    demand = {
                        'source': '福建大数据交易所',
                        'title': item.get('demandName', '无标题'),
                        'description': item.get('demandDesc', ''),
                        'publish_date': item.get('releaseTime', ''),
                        'url': f"https://trade.fjbdtex.com/demand/{item.get('id', '')}",
                        'category': item.get('demandScene', ''),
                        'supplier': item.get('companyName', ''),
                        'source_priority': 2,
                    }
                    all_demands.append(demand)

                logger.info(f"福建数交所第 {page} 页抓取 {len(items)} 条")

                if len(items) < page_size:
                    break
                page += 1

            except Exception as e:
                logger.error(f"福建数交所抓取第 {page} 页失败: {e}")
                break

        logger.info(f"福建数交所总计抓取 {len(all_demands)} 条")
        return all_demands

    @retry_on_error(max_retries=3, delay=2, exceptions=(requests.exceptions.RequestException,))
    def fetch_anhui(self) -> List[Dict]:
        """抓取安徽省数据交易所的需求列表"""
        all_demands = []
        seen_ids = set()
        page = 1
        page_size = 10
        total_pages = None

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "Content-Type": "application/json",
            "Origin": "https://www.ahdexc.com",
            "Referer": "https://www.ahdexc.com/businessHall",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": os.getenv('COOKIE_ANHUI', ''),
        }

        while True:
            try:
                url = "https://www.ahdexc.com/api/portal/business/getNeedList"
                payload = {
                    "order": "desc",
                    "sidx": "create_time",
                    "tags": [],
                    "searchKey": "",
                    "pageNum": page,
                    "pageSize": page_size,
                    "minBudget": "",
                    "maxBudget": "",
                }
                response = self.session.post(url, headers=headers, json=payload, timeout=30)

                if response.status_code != 200:
                    logger.error(f"安徽数交所请求失败: {response.status_code}")
                    break

                data = response.json()
                if data.get('code') != 0:
                    logger.error(f"安徽数交所 API 错误: {data.get('msg')}")
                    break

                items = data.get('data', {}).get('list', [])

                if page == 1:
                    total = data.get('data', {}).get('total', 0)
                    if total == 0:
                        logger.warning("安徽数交所返回 total=0，无数据")
                        break
                    total_pages = data.get('data', {}).get('totalPage', 1)
                    logger.info(f"安徽数交所共 {total} 条需求，共 {total_pages} 页")

                if not items:
                    break

                added_count = 0
                for item in items:
                    demand_id = item.get('id', '')
                    if demand_id in seen_ids:
                        continue
                    seen_ids.add(demand_id)

                    tags = item.get('labelList', [])
                    tags_str = ', '.join(tags) if tags else ''

                    demand = {
                        'source': '安徽省数据交易所',
                        'title': item.get('needTitle', '无标题'),
                        'description': item.get('needDescription', ''),
                        'publish_date': item.get('launchDate', ''),
                        'url': f"https://www.ahdexc.com/demand/{demand_id}",
                        'category': '',
                        'supplier': item.get('companyName', ''),
                        'status': item.get('needStatusName', ''),
                        'tags': tags_str,
                        'views': item.get('pageViews', 0),
                        'source_priority': 2,
                    }
                    all_demands.append(demand)
                    added_count += 1

                logger.info(f"安徽数交所第 {page} 页抓取 {len(items)} 条，新增 {added_count} 条")

                if added_count == 0:
                    logger.info("后续页面无新增数据，停止抓取")
                    break

                if total_pages and page >= total_pages:
                    break

                if len(items) < page_size:
                    break

                page += 1

            except Exception as e:
                logger.error(f"安徽数交所抓取第 {page} 页失败: {e}")
                break

        logger.info(f"安徽数交所总计抓取 {len(all_demands)} 条（去重后）")
        return all_demands

    @retry_on_error(max_retries=3, delay=2, exceptions=(requests.exceptions.RequestException,))
    def fetch_bbg(self) -> List[Dict]:
        """抓取北部湾大数据交易中心的需求列表（从HTML解析）"""
        all_demands = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": os.getenv('COOKIE_BBG', ''),
        }
        try:
            url = "https://www.bbgdex.com/demand/put"
            response = self.session.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                logger.error(f"北部湾数交所请求失败: {response.status_code}")
                return all_demands

            soup = BeautifulSoup(response.text, 'html.parser')
            # 找到所有需求条目
            items = soup.select('.demand-item')
            if not items:
                logger.warning("北部湾数交所未找到需求条目，可能需要登录")
                return all_demands

            logger.info(f"北部湾数交所找到 {len(items)} 条需求")

            for item in items:
                # 标题
                title_elem = item.select_one('.title')
                title = title_elem.text.strip() if title_elem else '无标题'

                # 描述（如果有）
                desc_elem = item.select_one('.desc, .description')
                description = desc_elem.text.strip() if desc_elem else ''

                # 电话（如果有）
                phone_elem = item.select_one('.tel')
                phone = phone_elem.text.strip() if phone_elem else ''

                demand = {
                    'source': '北部湾大数据交易中心',
                    'title': title,
                    'description': description,
                    'publish_date': '',
                    'url': url,
                    'category': '',
                    'phone': phone,
                    'source_priority': 2,
                }
                all_demands.append(demand)

            logger.info(f"北部湾数交所抓取完成，发现 {len(all_demands)} 条需求")
        except Exception as e:
            logger.error(f"北部湾数交所抓取失败: {e}")
        return all_demands

    @retry_on_error(max_retries=3, delay=2, exceptions=(requests.exceptions.RequestException,))
    def fetch_zhejiang(self) -> List[Dict]:
        """抓取浙江大数据交易服务平台的需求列表"""
        all_demands = []
        page = 1
        page_size = 10
        total_pages = None

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "Authorization": os.getenv('AUTHORIZATION_ZHEJIANG', ''),
            "Content-Type": "application/json;charset=UTF-8",
            "Referer": "https://ditm.zjdex.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": os.getenv('COOKIE_ZHEJIANG', ''),
        }

        while True:
            try:
                url = "https://ditm.zjdex.com/tsslapi/demand/home"
                payload = {
                    "pageNum": page,
                    "pageSize": page_size,
                    "timestamp": int(datetime.now().timestamp() * 1000),  # 时间戳（毫秒）
                }
                response = self.session.post(url, headers=headers, json=payload, timeout=30)

                if response.status_code != 200:
                    logger.error(f"浙江数交所请求失败: {response.status_code}")
                    break

                data = response.json()
                if data.get('code') != 'SUCCESS':
                    logger.error(f"浙江数交所 API 错误: {data.get('msg')}")
                    break

                items = data.get('data', {}).get('list', [])

                if page == 1:
                    total = data.get('data', {}).get('total', 0)
                    total_pages = data.get('data', {}).get('totalPage', 1)
                    logger.info(f"浙江数交所共 {total} 条需求，共 {total_pages} 页")

                if not items:
                    break

                for item in items:
                    demand = {
                        'source': '浙江大数据交易服务平台',
                        'title': item.get('name', '无标题'),
                        'description': item.get('synopsis', ''),
                        'publish_date': item.get('createTime', ''),
                        'url': f"https://ditm.zjdex.com/demand/{item.get('id', '')}",
                        'category': item.get('parentCategoryName', ''),
                        'supplier': item.get('companyName', ''),
                        'source_priority': 2,
                    }
                    all_demands.append(demand)

                logger.info(f"浙江数交所第 {page} 页抓取 {len(items)} 条")

                if len(items) < page_size:
                    break
                if total_pages and page >= total_pages:
                    break
                page += 1

            except Exception as e:
                logger.error(f"浙江数交所抓取第 {page} 页失败: {e}")
                break

        logger.info(f"浙江数交所总计抓取 {len(all_demands)} 条")
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
            ('深数网公众号', self.fetch_shenzhen),
            ('山东数交所', self.fetch_shandong),
            ('湖南数交所', self.fetch_hunan),
            ('郑州数交所', self.fetch_zhengzhou),
            ('华东数交所', self.fetch_huadong),
            ('福建数交所', self.fetch_fujian),
            ('安徽数交所', self.fetch_anhui),
            ('北部湾数交所', self.fetch_bbg),
            ('浙江数交所', self.fetch_zhejiang),
            ('北数所公众号',self.fetch_beijing_wechat()),
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
            # ✅ 按 source_priority 排序（公众号优先，值为1的排在前面）
            all_demands.sort(key=lambda x: x.get('source_priority', 2))
            logger.info("数据已按来源优先级排序（公众号优先）")

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