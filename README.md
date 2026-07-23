# 数据需求自动采集与可视化系统

## 项目简介
本项目实现了对**尚数网、北京国际大数据交易所、上海数据交易所、广州数据交易所**数据需求的每日自动抓取、清洗、存储与可视化展示。

## 功能模块
- **数据抓取**：定时抓取4个平台的数据需求（工作日10:00自动执行）
- **数据清洗**：自动去重、字段修复、HTML标签清理、分类映射
- **数据存储**：SQLite数据库 + CSV导出（全量/拆分/增量）
- **可视化看板**：Flask + ECharts 构建，支持筛选、导出、趋势分析

## 技术栈
Python · Requests · BeautifulSoup · Pandas · SQLite · Flask · ECharts

## 快速运行
```bash
# 安装依赖
pip install -r requirements.txt

# 启动爬虫调度（定时任务）
python scheduler.py

# 启动看板
python app.pygit mv README README.md
git add README.md