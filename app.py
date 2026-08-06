from flask import Flask, jsonify, render_template, request, send_file
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import io
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def get_db_connection():
    conn = sqlite3.connect('./demands.db')
    conn.row_factory = sqlite3.Row
    return conn


@app.route('/')
def dashboard():
    return render_template('dashboard.html')

@app.route('/demands')
def demands_page():
    return render_template('demands.html')

@app.route('/stats')
def stats_page():
    return render_template('stats.html')

@app.route('/api/dashboard')
def api_dashboard():
    conn = get_db_connection()

    # 获取前端传递的参数
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    source = request.args.get('source', 'all')

    # 构建SQL查询
    query = "SELECT * FROM demands WHERE 1=1"
    params = []
    if start_date:
        query += " AND created_at >= ?"
        params.append(start_date)
    if end_date:
        query += " AND created_at <= ?"
        params.append(end_date + ' 23:59:59')
    if source != 'all':
        query += " AND source = ?"
        params.append(source)
    query += " ORDER BY created_at DESC"

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    if df.empty:
        return jsonify({'error': 'No data'})

    # 总览指标
    total = len(df)

    # 今日新增（独立查询，不受前端日期参数影响）
    today = datetime.now().strftime('%Y-%m-%d')
    conn2 = get_db_connection()
    today_query = "SELECT * FROM demands WHERE DATE(created_at) = DATE('now')"
    today_df_full = pd.read_sql_query(today_query, conn2)
    conn2.close()
    today_count = len(today_df_full)

    # 来源分布
    source_counts = df['source'].value_counts().to_dict()

    # 分类分布
    category_counts = df['category'].value_counts().to_dict()

    # 每日趋势（最近30天）
    df['created_date'] = df['created_at'].str[:10]
    daily_counts = df.groupby('created_date').size().to_dict()
    sorted_dates = sorted(daily_counts.keys(), reverse=True)[:30]
    sorted_dates.reverse()
    daily_data = {d: daily_counts.get(d, 0) for d in sorted_dates}

    # 各平台每日趋势
    platform_daily = {}
    for src in df['source'].unique():
        sub = df[df['source'] == src]
        sub_daily = sub.groupby('created_date').size().to_dict()
        platform_daily[src] = {d: sub_daily.get(d, 0) for d in sorted_dates}

    # 近7日
    last_7_dates = sorted_dates[-7:] if len(sorted_dates) >= 7 else sorted_dates
    last_7_data = {d: daily_counts.get(d, 0) for d in last_7_dates}

    # 今日新增列表（前20条）
    today_list = today_df_full[['title', 'source', 'created_at']].head(20).to_dict('records')

    # 所有数据源列表
    all_sources = df['source'].unique().tolist()
    logger.info(f"数据源列表（共 {len(all_sources)} 个）: {all_sources}")

    return jsonify({
        'total': total,
        'today_count': today_count,
        'source_counts': source_counts,
        'category_counts': category_counts,
        'daily_data': daily_data,
        'platform_daily': platform_daily,
        'last_7_dates': last_7_dates,
        'last_7_data': last_7_data,
        'dates': sorted_dates,
        'today_list': today_list,
        'all_sources': all_sources,
        'current_source': source,
        'start_date': start_date,
        'end_date': end_date
    })


@app.route('/api/demand/<demand_id>')
def api_demand_detail(demand_id):
    """获取单条需求的详细信息"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, source, title, description, category, publish_date, url, created_at, source_priority, raw_data
        FROM demands WHERE id = ?
    ''', (demand_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({'code': 404, 'msg': '需求不存在'})

    # 从 raw_data 中提取额外字段
    raw_data = {}
    try:
        import json
        if row[9]:
            raw_data = json.loads(row[9])
    except:
        pass

    return jsonify({
        'code': 0,
        'data': {
            'id': row[0],
            'source': row[1],
            'title': row[2],
            'description': row[3],
            'category': row[4] or '',
            'publish_date': row[5] or '',
            'url': row[6] or '',
            'created_at': row[7] or '',
            'source_priority': row[8] or 2,
            'supplier': raw_data.get('supplier', ''),
            'budget': raw_data.get('budget', ''),
            'phone': raw_data.get('phone', ''),
            'detailed_requirements': raw_data.get('detailed_requirements', ''),
        }
    })


@app.route('/demand/<demand_id>')
def demand_detail_page(demand_id):
    """需求详情页面"""
    return render_template('demand_detail.html')

@app.route('/api/export')
def export_csv():
    # 导出当前筛选条件的数据为CSV
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    source = request.args.get('source', 'all')

    conn = get_db_connection()
    query = "SELECT * FROM demands WHERE 1=1"
    params = []
    if start_date:
        query += " AND created_at >= ?"
        params.append(start_date)
    if end_date:
        query += " AND created_at <= ?"
        params.append(end_date + ' 23:59:59')
    if source != 'all':
        query += " AND source = ?"
        params.append(source)
    query += " ORDER BY created_at DESC"

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    if df.empty:
        return "无数据可导出", 400

    output = io.StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig')
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'demands_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )


# ==================== 新增：全部需求列表 API ====================
@app.route('/api/demands')
def api_demands():
    """
    获取全部需求列表（支持分页、排序、筛选）
    """
    # 获取请求参数
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 20, type=int)
    source = request.args.get('source', 'all')
    keyword = request.args.get('keyword', '')
    sort_by = request.args.get('sort_by', 'publish_date')  # publish_date / source_priority
    sort_order = request.args.get('sort_order', 'desc')  # asc / desc

    # 计算偏移量
    offset = (page - 1) * page_size

    conn = get_db_connection()
    cursor = conn.cursor()

    # 构建查询条件
    where_clauses = []
    params = []

    if source != 'all':
        where_clauses.append("source = ?")
        params.append(source)

    if keyword:
        where_clauses.append("(title LIKE ? OR description LIKE ?)")
        params.append(f"%{keyword}%")
        params.append(f"%{keyword}%")

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    # 构建排序
    if sort_by == 'source_priority':
        order_clause = "ORDER BY source_priority ASC, publish_date DESC"
    else:
        order_clause = f"ORDER BY publish_date {sort_order}"

    # 查询总数
    count_sql = f"SELECT COUNT(*) FROM demands WHERE {where_sql}"
    cursor.execute(count_sql, params)
    total = cursor.fetchone()[0]

    # 查询数据
    query = f"""
        SELECT id, source, title, description, category, publish_date, url, created_at, source_priority
        FROM demands 
        WHERE {where_sql}
        {order_clause}
        LIMIT ? OFFSET ?
    """
    cursor.execute(query, params + [page_size, offset])
    rows = cursor.fetchall()

    # 转换为字典列表
    items = []
    for row in rows:
        items.append({
            'id': row[0],
            'source': row[1],
            'title': row[2],
            'description': row[3][:200] + '...' if row[3] and len(row[3]) > 200 else row[3] or '',
            'category': row[4] or '',
            'publish_date': row[5] or '',
            'url': row[6] or '',
            'created_at': row[7] or '',
            'source_priority': row[8] or 2,
        })

    conn.close()

    return jsonify({
        'code': 0,
        'data': {
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': (total + page_size - 1) // page_size,
            'list': items
        }
    })


# ==============================================================

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)