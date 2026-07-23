import os
import sys
import schedule
import time
import logging
import requests
from logging.handlers import RotatingFileHandler
from datetime import datetime
from crawler import ShangshuwangCrawler
from clean_data import clean_and_export_daily

# ========== 配置 ==========
# 企业微信机器人 Webhook（请替换为你自己的）
WECHAT_WEBHOOK_URL = " "

# ========== 创建日志目录 ==========
LOG_DIR = './logs'
os.makedirs(LOG_DIR, exist_ok=True)

# ========== 配置日志（RotatingFileHandler） ==========
log_file = os.path.join(LOG_DIR, 'crawler.log')
logger = logging.getLogger('crawler_scheduler')
logger.setLevel(logging.INFO)
logger.propagate = False

# 控制台输出
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)

# 文件输出（轮转：单文件5MB，保留5个备份）
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

# ========== 锁定工作目录 ==========
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ========== 企业微信告警函数 ==========
def send_wechat_alert(message: str):
    """发送告警消息到企业微信群"""
    if not WECHAT_WEBHOOK_URL or "你的key" in WECHAT_WEBHOOK_URL:
        logger.warning("企业微信 Webhook 未配置，跳过告警")
        return
    try:
        data = {
            "msgtype": "text",
            "text": {"content": f"⚠️ 爬虫告警\n{message}"}
        }
        resp = requests.post(WECHAT_WEBHOOK_URL, json=data, timeout=5)
        if resp.status_code == 200:
            logger.info("告警消息已发送")
        else:
            logger.error(f"告警发送失败: {resp.text}")
    except Exception as e:
        logger.error(f"告警发送异常: {e}")

# ========== 定时任务函数 ==========
def job():
    # 周末跳过
    if datetime.now().weekday() >= 5:
        logger.info("今天是周末，不执行抓取任务")
        return

    logger.info("===== 定时任务开始执行 =====")
    crawler = ShangshuwangCrawler()
    error_occurred = False
    error_msg = ""

    try:
        crawler.fetch_all()
        logger.info("抓取完成，开始清洗数据...")
        logger.info("即将调用清洗函数...")
        clean_and_export_daily()
        logger.info("数据清洗完成")
    except Exception as e:
        error_occurred = True
        error_msg = f"❌ 任务执行异常: {str(e)}"
        logger.error(error_msg)
        send_wechat_alert(f"任务执行失败\n{error_msg}")
    finally:
        crawler.close()

    # 如果有错误但未发送告警（例如之前的异常已被捕获但未发送），可在此兜底
    if error_occurred:
        # 已发送，无需重复
        pass

    logger.info("===== 定时任务执行完毕 =====")

# ========== 设置定时计划 ==========
schedule.every().day.at("10:00").do(job)

logger.info(f"定时任务已启动，工作日 10:00 自动抓取（周末跳过）。日志文件: {log_file}")
logger.info("按 Ctrl+C 可停止。")

# ========== 循环执行 ==========
while True:
    schedule.run_pending()
    time.sleep(60)