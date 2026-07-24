# 📊 数据需求自动采集与可视化系统

> 多源数据需求的每日自动抓取、清洗、存储与可视化展示

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)

---

## 🎯 项目简介

本项目实现了对 **尚数网、北京、上海、广州、杭州、深圳、山东、湖南、郑州、贵阳、华东江苏** 等全国主要数据交易平台的数据需求/数据产品的每日自动抓取、清洗、存储与可视化展示。

系统每天定时运行，自动产出干净的增量数据，并通过交互式看板直观展示需求趋势与来源分布。

---

## ✨ 功能特性

- **自动抓取**：工作日 10:00 定时运行，支持 11 个数据源
- **数据清洗**：自动去重、字段修复、HTML 标签清理、分类映射
- **数据存储**：SQLite 数据库 + CSV 导出（全量 / 拆分 / 增量）
- **可视化看板**：Flask + ECharts 实现，支持日期 / 来源筛选、数据导出
- **安全加固**：敏感信息通过环境变量管理，不写入代码
- **日志轮转**：自动切割日志，单文件 5MB，保留 5 个备份
- **异常重试**：网络请求自动重试，提高稳定性

---

## 🛠️ 技术栈

| 类别 | 技术 |
|------|------|
| 爬虫 | Python · Requests · BeautifulSoup |
| 数据处理 | Pandas · SQLite · 正则表达式 |
| 定时调度 | schedule |
| 可视化 | Flask · ECharts |
| 日志 | RotatingFileHandler |
| 版本控制 | Git · GitHub |

---

## 📊 数据来源

| 数据源 | 状态 | 接入方式 | 数据量（最新） |
|--------|------|----------|----------------|
| 尚数网 | ✅ 已接入 | 公开 API | ~10 条 |
| 北京国际大数据交易所 | ✅ 已接入 | API + Cookie | ~10 条 |
| 上海数据交易所 | ✅ 已接入 | API + Cookie | ~3882 条 |
| 广州数据交易所 | ✅ 已接入 | API + Token | ~39 条 |
| 杭州数据交易所 | ✅ 已接入 | API + Cookie | ~23 条 |
| 山东数据交易平台 | ✅ 已接入 | API + Cookie | ~16 条 |
| 湖南大数据交易所 | ✅ 已接入 | API + Cookie + Token | ~2703 条 |
| 郑州数据交易中心 | ✅ 已接入 | API + Cookie | ~10 条 |
| 贵阳大数据交易所 | ✅ 已接入 | API + Cookie | ~20 条 |
| 华东江苏大数据交易中心 | ⚠️ 部分接入 | API + Cookie | ~50 条（共62条，接口分页限制） |
| 深圳数据交易所 | ⏳ 待审核 | API + Cookie | 等待企业认证 |

> 华东江苏大数据交易中心因接口分页问题，实际抓取 50 条（总 62 条）。

---

## 📊 看板预览

### 总览卡片

![总览](screenshots/overview.png)

### 每日新增趋势

![趋势](screenshots/trend.png)

### 来源分布

![来源分布](screenshots/source_distribution.png)

### 今日新增需求列表

![今日新增列表](screenshots/daily_list.png)

> 注：截图当日无新增需求，不代表系统异常。

---

## 🚀 快速运行

### 1. 克隆项目

```bash
git clone https://github.com/2433931816/data-demand-crawler.git
cd data-demand-crawler