from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
import time
import re


def search_wechat_articles(keyword: str, max_pages: int = 2) -> list:
    """
    通过搜狗微信搜索获取公众号文章列表
    """
    articles = []

    # 配置 Chrome 选项（无头模式，不显示浏览器窗口）
    chrome_options = Options()
    chrome_options.add_argument('--headless')  # 无头模式，不显示窗口
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument(
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    try:
        for page in range(1, max_pages + 1):
            # 构建搜狗搜索 URL
            url = f"https://weixin.sogou.com/weixin?type=2&query={keyword}&page={page}&ie=utf8"
            driver.get(url)

            # 等待文章列表加载
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '.news-list .news-item, .news-list li'))
            )

            # 提取文章信息
            items = driver.find_elements(By.CSS_SELECTOR, '.news-list .news-item, .news-list li')

            for item in items:
                try:
                    title_elem = item.find_element(By.CSS_SELECTOR, '.news-title a, .tit a')
                    title = title_elem.text.strip()
                    link = title_elem.get_attribute('href')

                    # 过滤非公众号链接
                    if not link or 'mp.weixin.qq.com' not in link:
                        continue

                    # 提取摘要
                    abstract_elem = item.find_elements(By.CSS_SELECTOR, '.txt-info, .abstract')
                    abstract = abstract_elem[0].text.strip() if abstract_elem else ''

                    # 提取发布时间
                    time_elem = item.find_elements(By.CSS_SELECTOR, '.s-p, .time, .news-time')
                    publish_time = time_elem[0].text.strip() if time_elem else ''

                    articles.append({
                        'title': title,
                        'url': link,
                        'abstract': abstract,
                        'publish_time': publish_time,
                    })
                except:
                    continue

            # 检查是否有下一页
            try:
                next_btn = driver.find_element(By.CSS_SELECTOR, '#sogou_next')
                if 'disable' in next_btn.get_attribute('class'):
                    break
            except:
                break

            time.sleep(2)  # 翻页间隔

    finally:
        driver.quit()
 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    return articles


def filter_demand_articles(articles: list) -> list:
    """筛选需求发布类文章"""
    keywords = ['需求', '数据集', '征集']
    return [a for a in articles if any(kw in a['title'] for kw in keywords)]


if __name__ == "__main__":
    # 测试
    print("正在搜索深圳数据交易所文章...")
    results = search_wechat_articles("深圳数据交易所", max_pages=2)
    print(f"共找到 {len(results)} 篇文章")

    demand_articles = filter_demand_articles(results)
    print(f"其中需求类文章 {len(demand_articles)} 篇")

    for article in demand_articles[:5]:
        print(f"\n标题: {article['title']}")
        print(f"链接: {article['url']}")
        print("-" * 40)