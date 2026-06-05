import os
import shutil
import re
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, Response
import sqlite3
import pytz
import markdown
from PIL import Image, ImageOps
import io

def get_china_time():
    tz = pytz.timezone('Asia/Shanghai')
    return datetime.now(tz).strftime('%Y-%m-%d')

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'db', 'd.db')

# === 模板过滤器 ===
@app.template_filter('md')
def markdown_to_html(text):
    if not text:
        return ""
    text = re.sub(r'\[red\](.*?)\[/red\]', r'<span style="color: red;">\1</span>', text)
    return markdown.markdown(text, extensions=['tables', 'fenced_code', 'nl2br', 'sane_lists', 'toc'])

@app.template_filter('format_behavior')
def format_behavior(text):
    if not text:
        return ""
    text = re.sub(r'\[red\](.*?)\[/red\]', r'<span class="tag-red-color">\1</span>', text)
    text = re.sub(r'\[b\](.*?)\[/b\]', r'<strong>\1</strong>', text)
    text = re.sub(r'\[eat\](.*?)\[/eat\]', r'<span class="tag-eat-color">【水3L：\1】</span>', text)
    text = re.sub(r'\[train\](.*?)\[/train\]', r'<span class="tag-train-color">\1</span>', text)
    text = re.sub(r'\[weight\](.*?)\[/weight\]', r'<span class="tag-weight-color">\1</span>', text)
    return text.replace('\n', '<br>')

# === 数据库 ===
def ensure_dirs():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def backup_database():
    try:
        if os.path.exists(DB_PATH):
            backup_path = os.path.join(BASE_DIR, 'db', f'备份-{datetime.now().strftime("%Y%m%d-%H%M%S")}.db')
            shutil.copy2(DB_PATH, backup_path)
    except:
        pass

def get_db_connection():
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS blogs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL, content TEXT NOT NULL,
        level INTEGER DEFAULT 0,
        is_hidden INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
        updated_at TIMESTAMP DEFAULT (datetime('now','localtime'))
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS money_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time DATE NOT NULL, money REAL NOT NULL,
        text TEXT NOT NULL, type TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT (datetime('now','localtime'))
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS behavior_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date DATE NOT NULL, text TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT (datetime('now','localtime'))
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS weight_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date DATE NOT NULL UNIQUE,
        weight REAL,
        note TEXT,
        created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
        updated_at TIMESTAMP DEFAULT (datetime('now','localtime'))
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        title TEXT DEFAULT '',
        photo_date TEXT DEFAULT '',
        note TEXT DEFAULT '',
        data BLOB NOT NULL,
        size_kb REAL DEFAULT 0,
        created_at TIMESTAMP DEFAULT (datetime('now','localtime'))
    )''')
    
    c.execute('CREATE INDEX IF NOT EXISTS idx_behavior_date ON behavior_records(date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_blogs_created_at ON blogs(created_at)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_money_time ON money_records(time)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_weight_date ON weight_records(date)')
    
    try:
        c.execute("ALTER TABLE blogs ADD COLUMN is_archived INTEGER DEFAULT 0")
    except:
        pass
    
    try:
        c.execute("ALTER TABLE photos ADD COLUMN size_kb REAL DEFAULT 0")
    except:
        pass
    
    conn.commit()
    conn.close()

@app.route('/tizhong')
def tizhong():
    limit = request.args.get('limit', '30')
    conn = get_db_connection()
    if limit == '0':
        records = conn.execute('SELECT * FROM weight_records WHERE weight IS NOT NULL ORDER BY date ASC').fetchall()
    else:
        records = conn.execute('SELECT * FROM weight_records WHERE weight IS NOT NULL ORDER BY date DESC LIMIT ?', (int(limit),)).fetchall()
        records = list(reversed(records))
    conn.close()
    records_list = []
    for r in records:
        note_str = r['note'] or '[]'
        try:
            note_list = json.loads(note_str)
        except:
            note_list = []
        records_list.append({'id': r['id'], 'date': r['date'], 'weight': r['weight'], 'note': note_list})
    today = get_china_time()
    return render_template('tizhong.html', records_json=json.dumps(records_list, ensure_ascii=False), today=today, current_limit=limit)

@app.route('/tizhong/get_detail')
def get_weight_detail():
    date = request.args.get('date', '')
    if not date:
        return jsonify({'success': False, 'message': '缺少日期'})
    conn = get_db_connection()
    record = conn.execute('SELECT * FROM weight_records WHERE date = ?', (date,)).fetchone()
    conn.close()
    if record:
        note_str = record['note'] or '[]'
        try:
            note_list = json.loads(note_str)
        except:
            note_list = []
        return jsonify({'success': True, 'has_record': True, 'date': record['date'], 'weight': record['weight'], 'note_list': note_list})
    else:
        return jsonify({'success': True, 'has_record': False, 'date': date, 'note_list': []})

@app.route('/tizhong/save', methods=['POST'])
def save_weight():
    try:
        data = request.get_json()
        date = data.get('date', '').strip()
        weight = data.get('weight')
        note_text = data.get('note', '').strip()
        if not date:
            return jsonify({'success': False, 'message': '日期不能为空'})
        conn = get_db_connection()
        existing = conn.execute('SELECT * FROM weight_records WHERE date = ?', (date,)).fetchone()
        weight_val = None
        if weight is not None and weight != '':
            try:
                weight_val = float(weight)
            except:
                pass
        if existing:
            old_note_str = existing['note'] or '[]'
            try:
                note_list = json.loads(old_note_str)
            except:
                note_list = []
            if note_text:
                note_list.append(note_text)
            new_note_str = json.dumps(note_list, ensure_ascii=False)
            if weight_val is not None:
                conn.execute('UPDATE weight_records SET weight=?, note=?, updated_at=datetime("now","localtime") WHERE date=?', (weight_val, new_note_str, date))
            else:
                conn.execute('UPDATE weight_records SET note=?, updated_at=datetime("now","localtime") WHERE date=?', (new_note_str, date))
        else:
            note_list = [note_text] if note_text else []
            new_note_str = json.dumps(note_list, ensure_ascii=False)
            conn.execute('INSERT INTO weight_records (date, weight, note) VALUES (?, ?, ?)', (date, weight_val, new_note_str))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': '保存成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/tizhong/delete_note', methods=['POST'])
def delete_note():
    try:
        data = request.get_json()
        date = data.get('date', '')
        index = data.get('index')
        if not date or index is None:
            return jsonify({'success': False, 'message': '参数错误'})
        conn = get_db_connection()
        record = conn.execute('SELECT * FROM weight_records WHERE date = ?', (date,)).fetchone()
        if not record:
            conn.close()
            return jsonify({'success': False, 'message': '记录不存在'})
        note_str = record['note'] or '[]'
        try:
            note_list = json.loads(note_str)
        except:
            note_list = []
        if 0 <= index < len(note_list):
            note_list.pop(index)
        new_note_str = json.dumps(note_list, ensure_ascii=False)
        conn.execute('UPDATE weight_records SET note=?, updated_at=datetime("now","localtime") WHERE date=?', (new_note_str, date))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'note_list': note_list})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# === 博客相关路由 ===
@app.route('/')
def index():
    return redirect(url_for('tizhong'))

@app.route('/blogs')
def blogs_index():
    show_hidden = request.args.get('show_hidden', 'false')
    conn = get_db_connection()
    if show_hidden == 'true':
        blogs = conn.execute('SELECT * FROM blogs ORDER BY is_hidden DESC, level DESC, created_at DESC').fetchall()
    else:
        blogs = conn.execute('SELECT * FROM blogs WHERE is_hidden = 0 ORDER BY level DESC, created_at DESC').fetchall()
    conn.close()
    return render_template('blogs.html', blogs=blogs, show_hidden=show_hidden)

@app.route('/blogs/create')
def create_blog():
    return render_template('create_blog.html')

@app.route('/blogs/add', methods=['POST'])
def add_blog():
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    if not title or not content:
        return redirect(url_for('create_blog'))
    conn = get_db_connection()
    conn.execute('INSERT INTO blogs (title, content) VALUES (?,?)', (title, content))
    conn.commit()
    conn.close()
    return redirect(url_for('blogs_index'))

@app.route('/blogs/edit/<int:blog_id>')
def edit_blog(blog_id):
    conn = get_db_connection()
    blog = conn.execute('SELECT * FROM blogs WHERE id = ?', (blog_id,)).fetchone()
    conn.close()
    if blog and blog['is_archived'] == 1:
        return "该文章已归档，无法编辑", 403
    return render_template('edit_blog.html', blog=blog) if blog else redirect(url_for('blogs_index'))

@app.route('/blogs/update/<int:blog_id>', methods=['POST'])
def update_blog(blog_id):
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    if not title or not content:
        return redirect(url_for('edit_blog', blog_id=blog_id))
    conn = get_db_connection()
    conn.execute('UPDATE blogs SET title=?, content=?, updated_at=datetime("now","localtime") WHERE id=?', (title, content, blog_id))
    conn.commit()
    conn.close()
    return redirect(url_for('blog_detail', blog_id=blog_id))

@app.route('/blogs/<int:blog_id>')
def blog_detail(blog_id):
    conn = get_db_connection()
    blog = conn.execute('SELECT * FROM blogs WHERE id = ?', (blog_id,)).fetchone()
    conn.close()
    return render_template('blog_detail.html', blog=blog) if blog else redirect(url_for('blogs_index'))

@app.route('/blogs/delete/<int:blog_id>', methods=['POST'])
def delete_blog(blog_id):
    conn = get_db_connection()
    blog = conn.execute('SELECT is_archived FROM blogs WHERE id = ?', (blog_id,)).fetchone()
    if blog and blog['is_archived'] == 1:
        conn.close()
        return "该文章已归档，无法删除", 403
    conn.execute('DELETE FROM blogs WHERE id = ?', (blog_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('blogs_index'))

@app.route('/blogs/toggle_hidden/<int:blog_id>', methods=['POST'])
def toggle_blog_hidden(blog_id):
    try:
        conn = get_db_connection()
        blog = conn.execute('SELECT is_hidden FROM blogs WHERE id = ?', (blog_id,)).fetchone()
        if blog:
            new_status = 0 if blog['is_hidden'] == 1 else 1
            conn.execute('UPDATE blogs SET is_hidden = ? WHERE id = ?', (new_status, blog_id))
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'is_hidden': new_status})
        conn.close()
        return jsonify({'success': False, 'message': '文章不存在'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# === 记账相关路由 ===
@app.route('/qian')
def qian():
    year = request.args.get('year')
    month = request.args.get('month')
    type_ = request.args.get('type')
    sort = request.args.get('sort', 'desc')
    keyword = request.args.get('keyword', '')
    show_special = request.args.get('show_special', 'true')
    now = get_china_time()
    if year is None:
        year = now[:4]
    if month is None:
        month = now[5:7]
    conn = get_db_connection()
    conditions, params = [], []
    if year:
        conditions.append("strftime('%Y', time) = ?")
        params.append(year)
    if month:
        conditions.append("strftime('%m', time) = ?")
        params.append(month.zfill(2))
    if type_:
        conditions.append("type = ?")
        params.append(type_)
    if keyword:
        conditions.append("(text LIKE ? OR type LIKE ?)")
        params.extend([f'%{keyword}%', f'%{keyword}%'])
    if show_special == 'false':
        conditions.append("type NOT IN ('房贷', '赞助')")
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    order = f" ORDER BY time {sort}, id ASC"
    records = conn.execute(f"SELECT * FROM money_records {where} {order}", params).fetchall()
    total_in = total_out = 0
    income_categories = {}
    expense_categories = {}
    for r in records:
        m = r['money']
        t = r['type']
        if m > 0:
            total_in += m
            if t not in income_categories:
                income_categories[t] = {'total': 0, 'count': 0, 'type': t}
            income_categories[t]['total'] += m
            income_categories[t]['count'] += 1
        else:
            total_out += abs(m)
            if t not in expense_categories:
                expense_categories[t] = {'total': 0, 'count': 0, 'type': t}
            expense_categories[t]['total'] += abs(m)
            expense_categories[t]['count'] += 1
    all_totals = []
    if income_categories:
        all_totals.extend([v['total'] for v in income_categories.values()])
    if expense_categories:
        all_totals.extend([v['total'] for v in expense_categories.values()])
    global_max = max(all_totals) if all_totals else 1
    income_list = sorted([{**v, 'percentage': round(v['total']/global_max*100,1)} for v in income_categories.values()], key=lambda x: x['total'], reverse=True)
    expense_list = sorted([{**v, 'percentage': round(v['total']/global_max*100,1)} for v in expense_categories.values()], key=lambda x: x['total'], reverse=True)
    years = [y[0] for y in conn.execute("SELECT DISTINCT strftime('%Y', time) FROM money_records ORDER BY 1 DESC").fetchall()]
    months = [m[0] for m in conn.execute("SELECT DISTINCT strftime('%m', time) FROM money_records ORDER BY 1").fetchall()]
    types = [t[0] for t in conn.execute("SELECT DISTINCT type FROM money_records ORDER BY 1").fetchall()]
    grouped_records = {}
    for r in records:
        s = str(r['time'])
        if len(s) < 10: continue
        y, m, d = s[:4], s[5:7], s[8:10]
        if y not in grouped_records:
            grouped_records[y] = {'name': f'{y}年', 'total':0,'income_total':0,'expense_total':0,'months':{}}
        if m not in grouped_records[y]['months']:
            grouped_records[y]['months'][m] = {'name': f'{int(m)}月','total':0,'income_total':0,'expense_total':0,'days':{}}
        if d not in grouped_records[y]['months'][m]['days']:
            grouped_records[y]['months'][m]['days'][d] = {'date':s,'total':0,'income_total':0,'expense_total':0,'records':[]}
        day = grouped_records[y]['months'][m]['days'][d]
        day['records'].append(r)
        amt = r['money']
        day['total'] += amt
        if amt >0:
            day['income_total'] += amt
            grouped_records[y]['months'][m]['income_total'] += amt
            grouped_records[y]['income_total'] += amt
        else:
            day['expense_total'] -= amt
            grouped_records[y]['months'][m]['expense_total'] -= amt
            grouped_records[y]['expense_total'] -= amt
        grouped_records[y]['months'][m]['total'] += amt
        grouped_records[y]['total'] += amt
    conn.close()
    return render_template('qian.html', grouped_records=grouped_records, available_years=years, available_months=months, available_types=types, current_year=year, current_month=month.zfill(2) if month else None, current_type=type_, sort_order=sort, keyword=keyword, now=now, total_income=total_in, total_expense=total_out, balance=total_in-total_out, income_categories=income_list, expense_categories=expense_list, show_special=show_special)

@app.route('/add_money_record', methods=['POST'])
def add_money_record():
    try:
        time = request.form.get('time', '').strip()
        money_str = request.form.get('money', '')
        text = request.form.get('text', '').strip()
        type_ = request.form.get('type', '').strip()
        if not time or not money_str or not text or not type_:
            return jsonify({'success': False, 'message': '请完整填写'})
        money = float(money_str)
        conn = get_db_connection()
        conn.execute('INSERT INTO money_records (time, money, text, type) VALUES (?,?,?,?)', (time, money, text, type_))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': '成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/delete_money_record/<int:record_id>', methods=['POST'])
def delete_money_record(record_id):
    try:
        conn = get_db_connection()
        conn.execute('DELETE FROM money_records WHERE id=?', (record_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# === 行为记录路由 ===
@app.route('/shijian')
def shijian():
    year = request.args.get('year')
    month = request.args.get('month')
    sort = request.args.get('sort','desc')
    keyword = request.args.get('keyword','')
    now = get_china_time()
    if year is None:
        year = now[:4]
    if month is None:
        month = now[5:7]
    conn = get_db_connection()
    cond, params = [], []
    if year:
        cond.append("strftime('%Y', date)=?")
        params.append(year)
    if month:
        cond.append("strftime('%m', date)=?")
        params.append(month.zfill(2))
    if keyword:
        cond.append("text LIKE ?")
        params.append(f'%{keyword}%')
    where = " WHERE "+" AND ".join(cond) if cond else ""
    order = f" ORDER BY date {sort}, id ASC"
    records = conn.execute(f"SELECT * FROM behavior_records {where} {order}", params).fetchall()
    years = [y[0] for y in conn.execute("SELECT DISTINCT strftime('%Y', date) FROM behavior_records ORDER BY 1 DESC").fetchall()]
    months = [m[0] for m in conn.execute("SELECT DISTINCT strftime('%m', date) FROM behavior_records ORDER BY 1").fetchall()]
    grouped_data = {'years':{},'total_count':0}
    for r in records:
        s = str(r['date'])
        if len(s)<10:continue
        y,m,d = s[:4],s[5:7],s[8:10]
        if y not in grouped_data['years']:
            grouped_data['years'][y] = {'name':f'{y}年','count':0,'months':{}}
        if m not in grouped_data['years'][y]['months']:
            grouped_data['years'][y]['months'][m] = {'name':f'{int(m)}月','count':0,'days':{}}
        if d not in grouped_data['years'][y]['months'][m]['days']:
            grouped_data['years'][y]['months'][m]['days'][d] = {'date':s,'date_short':s[5:],'count':0,'records':[]}
        day = grouped_data['years'][y]['months'][m]['days'][d]
        day['records'].append(dict(r))
        day['count'] +=1
        grouped_data['years'][y]['months'][m]['count'] +=1
        grouped_data['years'][y]['count'] +=1
        grouped_data['total_count'] +=1
    conn.close()
    return render_template('shijian.html', grouped_data=grouped_data['years'], total_count=grouped_data['total_count'], available_years=years, available_months=months, current_year=year, current_month=month, sort_order=sort, keyword=keyword, now=now)

@app.route('/add_behavior_record', methods=['POST'])
def add_behavior_record():
    try:
        date = request.form.get('date','').strip()
        text = request.form.get('text','').strip()
        if not date or not text:
            return jsonify({'success':False,'message':'必填'})
        conn = get_db_connection()
        conn.execute('INSERT INTO behavior_records (date,text) VALUES (?,?)',(date,text))
        conn.commit()
        conn.close()
        return jsonify({'success':True})
    except Exception as e:
        return jsonify({'success':False,'message':str(e)})

@app.route('/delete_behavior_record/<int:record_id>', methods=['POST'])
def delete_behavior_record(record_id):
    try:
        conn = get_db_connection()
        conn.execute('DELETE FROM behavior_records WHERE id=?',(record_id,))
        conn.commit()
        conn.close()
        return jsonify({'success':True})
    except Exception as e:
        return jsonify({'success':False,'message':str(e)})

@app.route('/qian/export_page')
def export_money_page():
    conn = get_db_connection()
    years = [y[0] for y in conn.execute("SELECT DISTINCT strftime('%Y', time) FROM money_records ORDER BY 1 DESC").fetchall()]
    types = [t[0] for t in conn.execute("SELECT DISTINCT type FROM money_records ORDER BY 1").fetchall()]
    conn.close()
    now = get_china_time()
    current_year = now[:4]
    current_month = now[5:7]
    return render_template('export_money.html', available_years=years, available_types=types, current_year=current_year, current_month=current_month)

@app.route('/qian/export/filtered', methods=['POST'])
def export_money_records_filtered():
    try:
        data = request.get_json()
        year = data.get('year', '')
        month = data.get('month', '')
        categories = data.get('categories', [])
        money_type = data.get('money_type', '')
        keyword = data.get('keyword', '')
        show_special = data.get('show_special', 'true')
        conn = get_db_connection()
        conditions = []
        params = []
        if year:
            conditions.append("strftime('%Y', time) = ?")
            params.append(year)
        if month:
            conditions.append("strftime('%m', time) = ?")
            params.append(month.zfill(2))
        if categories and len(categories) > 0:
            placeholders = ','.join(['?' for _ in categories])
            conditions.append(f"type IN ({placeholders})")
            params.extend(categories)
        if keyword:
            conditions.append("(text LIKE ? OR type LIKE ?)")
            params.extend([f'%{keyword}%', f'%{keyword}%'])
        if show_special == 'false':
            conditions.append("type NOT IN ('房贷', '赞助')")
        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        records = conn.execute(f"SELECT id, time, money, text, type, created_at FROM money_records {where_clause} ORDER BY time DESC, id ASC", params).fetchall()
        result_records = []
        category_stats = {}
        for record in records:
            if money_type == 'income' and record['money'] <= 0:
                continue
            if money_type == 'expense' and record['money'] >= 0:
                continue
            result_records.append({'time': record['time'], 'money': record['money'], 'text': record['text'], 'type': record['type']})
            cat_type = record['type']
            if cat_type not in category_stats:
                category_stats[cat_type] = {'count': 0, 'total_income': 0, 'total_expense': 0}
            if record['money'] > 0:
                category_stats[cat_type]['total_income'] += record['money']
            else:
                category_stats[cat_type]['total_expense'] += record['money']
            category_stats[cat_type]['count'] += 1
        conn.close()
        total_income = sum(r['money'] for r in result_records if r['money'] > 0)
        total_expense = sum(r['money'] for r in result_records if r['money'] < 0)
        selected_category_stats = {}
        if categories and len(categories) > 0:
            for cat in categories:
                if cat in category_stats:
                    selected_category_stats[cat] = category_stats[cat]
                else:
                    selected_category_stats[cat] = {'count': 0, 'total_income': 0, 'total_expense': 0}
        export_data = {
            'export_time': get_china_time(),
            'total_records': len(result_records),
            'total_income': total_income,
            'total_expense': total_expense,
            'balance': total_income + total_expense,
            'filters': {'year': year, 'month': month, 'categories': categories, 'money_type': money_type, 'keyword': keyword, 'show_special': show_special},
            'category_summary': {'all_categories': category_stats, 'selected_categories': selected_category_stats},
            'records': result_records
        }
        return jsonify(export_data)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# === 照片相关路由 ===
@app.route('/tupian')
def photos_page():
    conn = get_db_connection()
    photos = conn.execute('SELECT id, filename, title, photo_date, note, size_kb, created_at FROM photos ORDER BY photo_date DESC, id DESC').fetchall()
    conn.close()
    today = get_china_time()
    return render_template('tupian.html', photos=photos, today=today)


@app.route('/tupian/upload', methods=['POST'])
def photo_upload():
    try:
        file = request.files.get('photo')
        if not file or file.filename == '':
            return jsonify({'success': False, 'message': '请选择文件'})
        note = request.form.get('note', '').strip()
        photo_date = request.form.get('photo_date', '').strip()
        filename = file.filename
        img = Image.open(file.stream)
        img = ImageOps.exif_transpose(img)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        w, h = img.size
        if w > 1200:
            img.thumbnail((1200, 1200 * h // w), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85, optimize=True)
        compressed = buf.getvalue()
        size_kb = round(len(compressed) / 1024, 1)
        conn = get_db_connection()
        conn.execute('INSERT INTO photos (filename, title, photo_date, note, data, size_kb) VALUES (?, ?, ?, ?, ?, ?)',
                     (filename, '', photo_date, note, compressed, size_kb))
        conn.commit()
        new_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]  # ← 加这行
        conn.close()
        return jsonify({'success': True, 'message': '上传成功', 'id': new_id})  # ← 加了 'id'
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/tupian/delete/<int:photo_id>', methods=['POST'])
def photo_delete(photo_id):
    try:
        conn = get_db_connection()
        conn.execute('DELETE FROM photos WHERE id = ?', (photo_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/tupian/<int:photo_id>')
def photo_view(photo_id):
    conn = get_db_connection()
    row = conn.execute('SELECT data FROM photos WHERE id = ?', (photo_id,)).fetchone()
    conn.close()
    if row:
        return Response(row['data'], mimetype='image/jpeg')
    return '', 404


@app.route('/backup')
def manual_backup():
    try:
        backup_database()
        return '备份成功'
    except Exception as e:
        return f'备份失败：{str(e)}'

        
# === 启动 ===
if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5525)