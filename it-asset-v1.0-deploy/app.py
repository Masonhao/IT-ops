"""
企业运维管理系统 - Flask 主应用
基于 Flask + SQLite，含用户认证与权限管理
"""
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, g
from functools import wraps
from models import init_db, get_db, generate_asset_no, generate_equip_no, hash_password, verify_password
from datetime import datetime, timedelta
import json
import os
import logging
import time
from collections import defaultdict

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

# 从环境变量读取 SECRET_KEY，未设置时随机生成（开发环境）
app.secret_key = os.environ.get('SECRET_KEY')
if not app.secret_key:
    import secrets
    app.secret_key = secrets.token_hex(32)
    print("[WARN] SECRET_KEY 未设置，已随机生成。生产环境请务必设置环境变量 SECRET_KEY")

# Session 安全配置
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# 生产环境请取消注释下一行，确保仅通过 HTTPS 传输 session cookie
# app.config['SESSION_COOKIE_SECURE'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)

# 初始化日志
logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

# 初始化数据库
init_db()

# ==================== 权限控制 ====================

MODULE_MAP = {
    'asset': '资产管理',
    'category': '资产分类',
    'software': '软件授权',
    'supplier': '供应商',
    'contract': '合同管理',
    'domain': '域名管理',
    'inventory': '盘点管理',
    'alert': '到期预警',
    'report': '报表统计',
    'equipment': '设备台账',
    'inspection': '每日巡检',
    'worklog': '工作日志',
    'report_daily': '日报管理',
    'report_weekly': '周报管理',
    'report_monthly': '月报管理',
    'user': '用户管理',
}


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json:
                return jsonify({'error': '请先登录'}), 401
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': '请先登录'}), 401
        if session.get('role') != 'admin':
            return jsonify({'error': '需要管理员权限'}), 403
        return f(*args, **kwargs)
    return decorated


def check_permission(module):
    """检查当前用户是否有指定模块权限"""
    if session.get('role') == 'admin':
        return True
    perms = session.get('permissions', '')
    if perms == 'all':
        return True
    return module in perms.split(',')


def require_permission(module):
    """装饰器：要求指定模块权限"""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not check_permission(module):
                if request.is_json:
                    return jsonify({'error': f'无权访问【{MODULE_MAP.get(module, module)}】模块'}), 403
                return render_template('error.html', message=f'无权访问【{MODULE_MAP.get(module, module)}】模块'), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


@app.before_request
def load_user():
    g.user = None
    if 'user_id' in session:
        conn = get_db()
        g.user = conn.execute('SELECT * FROM user WHERE id = ?', (session['user_id'],)).fetchone()
        conn.close()


# ==================== 登录/认证 ====================

# 登录频率限制存储（IP -> {count, reset_time}）
_login_rate_limit = defaultdict(lambda: {'count': 0, 'reset': 0})
_MAX_LOGIN_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 60


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    data = request.get_json() or request.form
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if not username or not password:
        return jsonify({'error': '请输入用户名和密码'}), 400

    # 频率限制
    client_ip = request.remote_addr or 'unknown'
    now = time.time()
    limit = _login_rate_limit[client_ip]
    if now > limit['reset']:
        limit['count'] = 0
        limit['reset'] = now + _LOGIN_WINDOW_SECONDS
    limit['count'] += 1
    if limit['count'] > _MAX_LOGIN_ATTEMPTS:
        app.logger.warning(f"登录频率超限: IP={client_ip}, user={username}")
        return jsonify({'error': '登录尝试次数过多，请稍后再试'}), 429

    conn = get_db()
    user = conn.execute('SELECT * FROM user WHERE username = ? AND is_active = 1',
                        (username,)).fetchone()
    conn.close()

    is_valid, is_legacy = verify_password(password, user['password'] if user else '')
    if not user or not is_valid:
        return jsonify({'error': '用户名或密码错误'}), 401

    # 自动迁移旧 SHA256 密码到新哈希格式
    if is_legacy:
        conn = get_db()
        conn.execute('UPDATE user SET password = ? WHERE id = ?', (hash_password(password), user['id']))
        conn.commit()
        conn.close()
        app.logger.info(f"密码已自动迁移到新哈希格式: user_id={user['id']}")

    session.permanent = True
    session['user_id'] = user['id']
    session['username'] = user['username']
    session['real_name'] = user['real_name']
    session['role'] = user['role']
    session['permissions'] = user['permissions']

    return jsonify({
        'message': '登录成功',
        'user': {'id': user['id'], 'username': user['username'],
                 'real_name': user['real_name'], 'role': user['role']}
    })


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


@app.route('/api/me')
@login_required
def get_me():
    conn = get_db()
    user = conn.execute('SELECT id, username, real_name, role, permissions FROM user WHERE id = ?',
                        (session['user_id'],)).fetchone()
    conn.close()
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    u = dict(user)
    u['permissions_list'] = u['permissions'].split(',') if u['permissions'] else []
    return jsonify(u)


# ==================== 页面路由 ====================

@app.route('/')
@login_required
def index():
    return render_template('index.html')


@app.route('/asset')
@login_required
@require_permission('asset')
def asset_page():
    return render_template('asset.html')


@app.route('/category')
@login_required
@require_permission('category')
def category_page():
    return render_template('category.html')


@app.route('/software')
@login_required
@require_permission('software')
def software_page():
    return render_template('software.html')


@app.route('/supplier')
@login_required
@require_permission('supplier')
def supplier_page():
    return render_template('supplier.html')


@app.route('/contract')
@login_required
@require_permission('contract')
def contract_page():
    return render_template('contract.html')


@app.route('/inventory')
@login_required
@require_permission('inventory')
def inventory_page():
    return render_template('inventory.html')


@app.route('/alert')
@login_required
@require_permission('alert')
def alert_page():
    return render_template('alert.html')


@app.route('/report')
@login_required
@require_permission('report')
def report_page():
    return render_template('report.html')


@app.route('/domain')
@login_required
@require_permission('domain')
def domain_page():
    return render_template('domain.html')


@app.route('/equipment')
@login_required
@require_permission('equipment')
def equipment_page():
    return render_template('equipment.html')


@app.route('/inspection')
@login_required
@require_permission('inspection')
def inspection_page():
    return render_template('inspection.html')


@app.route('/inspection/templates')
@login_required
@admin_required
def inspection_template_page():
    return render_template('inspection_template.html')


@app.route('/inspection/tasks')
@login_required
@admin_required
def inspection_task_page():
    return render_template('inspection_task.html')


@app.route('/worklog')
@login_required
@require_permission('worklog')
def worklog_page():
    return render_template('worklog.html')


@app.route('/report/daily')
@login_required
@require_permission('report_daily')
def report_daily_page():
    return render_template('report_daily.html')


@app.route('/report/weekly')
@login_required
@require_permission('report_weekly')
def report_weekly_page():
    return render_template('report_weekly.html')


@app.route('/report/monthly')
@login_required
@require_permission('report_monthly')
def report_monthly_page():
    return render_template('report_monthly.html')


@app.route('/user')
@login_required
@require_permission('user')
def user_page():
    return render_template('user.html')


# ==================== 用户管理 API ====================

@app.route('/api/users', methods=['GET'])
@login_required
@admin_required
def get_users():
    conn = get_db()
    rows = conn.execute('SELECT id, username, real_name, role, permissions, is_active, created_at FROM user ORDER BY id').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/users', methods=['POST'])
@login_required
@admin_required
def create_user():
    data = request.get_json()
    raw_pw = data.get('password', '').strip()
    if not raw_pw:
        raw_pw = 'ChangeMe123!'  # 随机强密码，首次登录后应强制修改
    conn = get_db()
    try:
        cursor = conn.execute('''
            INSERT INTO user (username, password, real_name, role, permissions)
            VALUES (?, ?, ?, ?, ?)
        ''', (data['username'], hash_password(raw_pw),
              data.get('real_name'), data.get('role', 'engineer'),
              data.get('permissions', 'report_daily')))
        conn.commit()
    except Exception as e:
        conn.close()
        app.logger.error(f"create_user error: {e}", exc_info=True)
        return jsonify({'error': '用户名已存在或创建失败'}), 400
    conn.close()
    return jsonify({'id': cursor.lastrowid}), 201


@app.route('/api/users/<int:uid>', methods=['GET'])
@login_required
@admin_required
def get_user(uid):
    conn = get_db()
    row = conn.execute(
        'SELECT id, username, real_name, role, permissions, is_active, created_at FROM user WHERE id = ?',
        (uid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': '用户不存在'}), 404
    return jsonify(dict(row))


@app.route('/api/users/<int:uid>', methods=['PUT'])
@login_required
@admin_required
def update_user(uid):
    data = request.get_json()
    conn = get_db()
    fields = []
    params = []
    for f in ['real_name', 'role', 'permissions', 'is_active']:
        if f in data:
            fields.append(f'{f} = ?')
            params.append(data[f])
    if data.get('password'):
        fields.append('password = ?')
        params.append(hash_password(data['password']))
    if not fields:
        conn.close()
        return jsonify({'error': '无更新内容'}), 400
    params.append(uid)
    conn.execute(f'UPDATE user SET {", ".join(fields)} WHERE id = ?', params)
    conn.commit()
    conn.close()
    return jsonify({'message': '更新成功'})


@app.route('/api/users/<int:uid>', methods=['DELETE'])
@login_required
@admin_required
def delete_user(uid):
    if uid == 1:
        return jsonify({'error': '不能删除默认管理员'}), 400
    conn = get_db()
    conn.execute('DELETE FROM user WHERE id = ?', (uid,))
    conn.commit()
    conn.close()
    return jsonify({'message': '删除成功'})


# ==================== 资产 API (保留原有) ====================

@app.route('/api/assets', methods=['GET'])
@login_required
@require_permission('asset')
def get_assets():
    conn = get_db()
    params = []
    conditions = []
    category_id = request.args.get('category_id')
    status = request.args.get('status')
    department = request.args.get('department')
    keyword = request.args.get('keyword')
    if category_id:
        conditions.append('a.category_id = ?')
        params.append(category_id)
    if status:
        conditions.append('a.status = ?')
        params.append(status)
    if department:
        conditions.append('a.department LIKE ?')
        params.append(f'%{department}%')
    if keyword:
        conditions.append('(a.name LIKE ? OR a.asset_no LIKE ? OR a.serial_no LIKE ? OR a.custodian LIKE ?)')
        params.extend([f'%{keyword}%'] * 4)
    where = ' AND '.join(conditions) if conditions else '1=1'
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    offset = (page - 1) * per_page
    total = conn.execute(f'SELECT COUNT(*) as cnt FROM asset a WHERE {where}', params).fetchone()['cnt']
    rows = conn.execute(f'''
        SELECT a.*, c.name as category_name, s.name as supplier_name
        FROM asset a
        LEFT JOIN category c ON a.category_id = c.id
        LEFT JOIN supplier s ON a.supplier_id = s.id
        WHERE {where}
        ORDER BY a.updated_at DESC
        LIMIT ? OFFSET ?
    ''', params + [per_page, offset]).fetchall()
    conn.close()
    return jsonify({'total': total, 'page': page, 'per_page': per_page, 'data': [dict(r) for r in rows]})


@app.route('/api/assets/<int:asset_id>', methods=['GET'])
@login_required
@require_permission('asset')
def get_asset(asset_id):
    conn = get_db()
    row = conn.execute('''
        SELECT a.*, c.name as category_name, s.name as supplier_name
        FROM asset a
        LEFT JOIN category c ON a.category_id = c.id
        LEFT JOIN supplier s ON a.supplier_id = s.id
        WHERE a.id = ?
    ''', (asset_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': '资产不存在'}), 404
    records = conn.execute(
        'SELECT * FROM asset_record WHERE asset_id = ? ORDER BY action_date DESC',
        (asset_id,)).fetchall()
    conn.close()
    result = dict(row)
    result['records'] = [dict(r) for r in records]
    return jsonify(result)


@app.route('/api/assets', methods=['POST'])
@login_required
@require_permission('asset')
def create_asset():
    data = request.get_json()
    conn = get_db()
    asset_no = data.get('asset_no') or generate_asset_no(data['category_id'])
    try:
        cursor = conn.execute('''
            INSERT INTO asset (asset_no, name, category_id, brand, model, serial_no,
                status, location, department, custodian, purchase_date, purchase_price,
                warranty_expire, supplier_id, depreciation_method, useful_life,
                residual_rate, current_value, remark)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (asset_no, data['name'], data['category_id'], data.get('brand'),
              data.get('model'), data.get('serial_no'), data.get('status', 'in_stock'),
              data.get('location'), data.get('department'), data.get('custodian'),
              data.get('purchase_date'), data.get('purchase_price'),
              data.get('warranty_expire'), data.get('supplier_id'),
              data.get('depreciation_method', 'straight_line'),
              data.get('useful_life', 60), data.get('residual_rate', 5.0),
              data.get('current_value', data.get('purchase_price')), data.get('remark')))
        asset_id = cursor.lastrowid
        conn.execute('''
            INSERT INTO asset_record (asset_id, action, to_department, to_location, to_custodian, operator, remark)
            VALUES (?, 'stock_in', ?, ?, ?, ?, ?)
        ''', (asset_id, data.get('department'), data.get('location'),
              data.get('custodian'), data.get('operator', '系统'), '资产入库'))
        conn.commit()
    except Exception as e:
        conn.close()
        app.logger.error(f"create_asset error: {e}", exc_info=True)
        return jsonify({'error': '操作失败，请检查输入数据'}), 400
    conn.close()
    return jsonify({'id': asset_id, 'asset_no': asset_no}), 201


@app.route('/api/assets/<int:asset_id>', methods=['PUT'])
@login_required
@require_permission('asset')
def update_asset(asset_id):
    data = request.get_json()
    conn = get_db()
    fields = []
    params = []
    editable = ['name', 'category_id', 'brand', 'model', 'serial_no', 'status',
                'location', 'department', 'custodian', 'purchase_date', 'purchase_price',
                'warranty_expire', 'supplier_id', 'depreciation_method', 'useful_life',
                'residual_rate', 'current_value', 'remark']
    for f in editable:
        if f in data:
            fields.append(f'{f} = ?')
            params.append(data[f])
    if not fields:
        conn.close()
        return jsonify({'error': '无更新内容'}), 400
    fields.append('updated_at = ?')
    params.append(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    params.append(asset_id)
    conn.execute(f'UPDATE asset SET {", ".join(fields)} WHERE id = ?', params)
    conn.commit()
    conn.close()
    return jsonify({'message': '更新成功'})


@app.route('/api/assets/<int:asset_id>', methods=['DELETE'])
@login_required
@require_permission('asset')
def delete_asset(asset_id):
    conn = get_db()
    conn.execute('DELETE FROM asset_record WHERE asset_id = ?', (asset_id,))
    conn.execute('DELETE FROM asset WHERE id = ?', (asset_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': '删除成功'})


@app.route('/api/assets/<int:asset_id>/action', methods=['POST'])
@login_required
@require_permission('asset')
def asset_action(asset_id):
    data = request.get_json()
    action = data.get('action')
    conn = get_db()
    asset = conn.execute('SELECT * FROM asset WHERE id = ?', (asset_id,)).fetchone()
    if not asset:
        conn.close()
        return jsonify({'error': '资产不存在'}), 404
    asset = dict(asset)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    status_map = {'allocate': 'in_use', 'transfer': 'in_use', 'repair': 'repair',
                  'return': 'in_stock', 'scrap': 'scrapped', 'dispose': 'disposed'}
    new_status = data.get('new_status') or status_map.get(action, asset['status'])
    update_fields = ['status = ?', 'updated_at = ?']
    update_params = [new_status, now]
    if data.get('to_department'):
        update_fields.append('department = ?')
        update_params.append(data['to_department'])
    if data.get('to_location'):
        update_fields.append('location = ?')
        update_params.append(data['to_location'])
    if data.get('to_custodian'):
        update_fields.append('custodian = ?')
        update_params.append(data['to_custodian'])
    update_params.append(asset_id)
    conn.execute(f'UPDATE asset SET {", ".join(update_fields)} WHERE id = ?', update_params)
    conn.execute('''
        INSERT INTO asset_record (asset_id, action, from_department, to_department,
            from_location, to_location, from_custodian, to_custodian, operator, remark)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (asset_id, action, asset['department'], data.get('to_department'),
          asset['location'], data.get('to_location'), asset['custodian'],
          data.get('to_custodian'), data.get('operator', '系统'), data.get('remark', '')))
    conn.commit()
    conn.close()
    return jsonify({'message': '操作成功'})


# ==================== 分类 API ====================

@app.route('/api/categories', methods=['GET'])
@login_required
def get_categories():
    conn = get_db()
    rows = conn.execute('SELECT * FROM category ORDER BY sort_order, id').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/categories', methods=['POST'])
@login_required
@require_permission('category')
def create_category():
    data = request.get_json()
    conn = get_db()
    try:
        cursor = conn.execute('INSERT INTO category (name, parent_id, sort_order) VALUES (?, ?, ?)',
                              (data['name'], data.get('parent_id'), data.get('sort_order', 0)))
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({'error': '分类名称已存在'}), 400
    conn.close()
    return jsonify({'id': cursor.lastrowid}), 201


@app.route('/api/categories/<int:cat_id>', methods=['PUT'])
@login_required
@require_permission('category')
def update_category(cat_id):
    data = request.get_json()
    conn = get_db()
    conn.execute('UPDATE category SET name=?, parent_id=?, sort_order=? WHERE id=?',
                 (data['name'], data.get('parent_id'), data.get('sort_order', 0), cat_id))
    conn.commit()
    conn.close()
    return jsonify({'message': '更新成功'})


@app.route('/api/categories/<int:cat_id>', methods=['DELETE'])
@login_required
@require_permission('category')
def delete_category(cat_id):
    conn = get_db()
    count = conn.execute('SELECT COUNT(*) as cnt FROM asset WHERE category_id = ?', (cat_id,)).fetchone()['cnt']
    if count > 0:
        conn.close()
        return jsonify({'error': f'该分类下有 {count} 条资产，无法删除'}), 400
    conn.execute('DELETE FROM category WHERE id = ?', (cat_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': '删除成功'})


# ==================== 供应商 API ====================

@app.route('/api/suppliers', methods=['GET'])
@login_required
@require_permission('supplier')
def get_suppliers():
    conn = get_db()
    rows = conn.execute('SELECT * FROM supplier ORDER BY id DESC').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/suppliers', methods=['POST'])
@login_required
@require_permission('supplier')
def create_supplier():
    data = request.get_json()
    conn = get_db()
    cursor = conn.execute('''
        INSERT INTO supplier (name, contact_person, contact_phone, contact_email, address, remark)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (data['name'], data.get('contact_person'), data.get('contact_phone'),
          data.get('contact_email'), data.get('address'), data.get('remark')))
    conn.commit()
    conn.close()
    return jsonify({'id': cursor.lastrowid}), 201


@app.route('/api/suppliers/<int:sid>', methods=['PUT'])
@login_required
@require_permission('supplier')
def update_supplier(sid):
    data = request.get_json()
    conn = get_db()
    conn.execute('''
        UPDATE supplier SET name=?, contact_person=?, contact_phone=?, contact_email=?, address=?, remark=?
        WHERE id=?
    ''', (data['name'], data.get('contact_person'), data.get('contact_phone'),
          data.get('contact_email'), data.get('address'), data.get('remark'), sid))
    conn.commit()
    conn.close()
    return jsonify({'message': '更新成功'})


@app.route('/api/suppliers/<int:sid>', methods=['DELETE'])
@login_required
@require_permission('supplier')
def delete_supplier(sid):
    conn = get_db()
    conn.execute('DELETE FROM supplier WHERE id = ?', (sid,))
    conn.commit()
    conn.close()
    return jsonify({'message': '删除成功'})


# ==================== 软件授权 API ====================

@app.route('/api/software', methods=['GET'])
@login_required
@require_permission('software')
def get_software():
    conn = get_db()
    rows = conn.execute('''
        SELECT sw.*, s.name as supplier_name FROM software sw
        LEFT JOIN supplier s ON sw.supplier_id = s.id
        ORDER BY sw.id DESC
    ''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/software', methods=['POST'])
@login_required
@require_permission('software')
def create_software():
    data = request.get_json()
    conn = get_db()
    cursor = conn.execute('''
        INSERT INTO software (name, version, license_type, license_count, used_count,
            license_key, expire_date, supplier_id, purchase_date, purchase_price, remark)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (data['name'], data.get('version'), data.get('license_type', 'perpetual'),
          data.get('license_count', 1), data.get('used_count', 0),
          data.get('license_key'), data.get('expire_date'), data.get('supplier_id'),
          data.get('purchase_date'), data.get('purchase_price'), data.get('remark')))
    conn.commit()
    conn.close()
    return jsonify({'id': cursor.lastrowid}), 201


@app.route('/api/software/<int:sid>', methods=['PUT'])
@login_required
@require_permission('software')
def update_software(sid):
    data = request.get_json()
    conn = get_db()
    fields = []
    params = []
    for f in ['name', 'version', 'license_type', 'license_count', 'used_count',
              'license_key', 'expire_date', 'supplier_id', 'purchase_date', 'purchase_price', 'remark']:
        if f in data:
            fields.append(f'{f} = ?')
            params.append(data[f])
    params.append(sid)
    conn.execute(f'UPDATE software SET {", ".join(fields)} WHERE id = ?', params)
    conn.commit()
    conn.close()
    return jsonify({'message': '更新成功'})


@app.route('/api/software/<int:sid>', methods=['DELETE'])
@login_required
@require_permission('software')
def delete_software(sid):
    conn = get_db()
    conn.execute('DELETE FROM software WHERE id = ?', (sid,))
    conn.commit()
    conn.close()
    return jsonify({'message': '删除成功'})


# ==================== 合同 API ====================

@app.route('/api/contracts', methods=['GET'])
@login_required
@require_permission('contract')
def get_contracts():
    conn = get_db()
    rows = conn.execute('''
        SELECT ct.*, s.name as supplier_name FROM contract ct
        LEFT JOIN supplier s ON ct.supplier_id = s.id
        ORDER BY ct.id DESC
    ''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/contracts', methods=['POST'])
@login_required
@require_permission('contract')
def create_contract():
    data = request.get_json()
    conn = get_db()
    cursor = conn.execute('''
        INSERT INTO contract (contract_no, title, supplier_id, contract_type, amount,
            start_date, end_date, status, remark)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (data['contract_no'], data['title'], data.get('supplier_id'),
          data.get('contract_type', 'purchase'), data.get('amount'),
          data.get('start_date'), data.get('end_date'),
          data.get('status', 'active'), data.get('remark')))
    conn.commit()
    conn.close()
    return jsonify({'id': cursor.lastrowid}), 201


@app.route('/api/contracts/<int:cid>', methods=['PUT'])
@login_required
@require_permission('contract')
def update_contract(cid):
    data = request.get_json()
    conn = get_db()
    fields = []
    params = []
    for f in ['contract_no', 'title', 'supplier_id', 'contract_type', 'amount',
              'start_date', 'end_date', 'status', 'remark']:
        if f in data:
            fields.append(f'{f} = ?')
            params.append(data[f])
    params.append(cid)
    conn.execute(f'UPDATE contract SET {", ".join(fields)} WHERE id = ?', params)
    conn.commit()
    conn.close()
    return jsonify({'message': '更新成功'})


@app.route('/api/contracts/<int:cid>', methods=['DELETE'])
@login_required
@require_permission('contract')
def delete_contract(cid):
    conn = get_db()
    conn.execute('DELETE FROM contract WHERE id = ?', (cid,))
    conn.commit()
    conn.close()
    return jsonify({'message': '删除成功'})


# ==================== 盘点 API ====================

@app.route('/api/inventories', methods=['GET'])
@login_required
@require_permission('inventory')
def get_inventories():
    conn = get_db()
    rows = conn.execute('SELECT * FROM inventory_task ORDER BY id DESC').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/inventories', methods=['POST'])
@login_required
@require_permission('inventory')
def create_inventory():
    data = request.get_json()
    conn = get_db()
    now = datetime.now().strftime('%Y%m')
    row = conn.execute('SELECT COUNT(*) as cnt FROM inventory_task').fetchone()
    task_no = f"PD-{now}-{(row['cnt']+1):04d}"
    cursor = conn.execute('''
        INSERT INTO inventory_task (task_no, title, status, created_by, remark)
        VALUES (?, ?, 'pending', ?, ?)
    ''', (task_no, data['title'], data.get('created_by', '系统'), data.get('remark')))
    task_id = cursor.lastrowid
    assets = conn.execute("SELECT id, status FROM asset WHERE status IN ('in_stock','in_use')").fetchall()
    for a in assets:
        conn.execute('''
            INSERT INTO inventory_item (task_id, asset_id, expected_status, is_matched)
            VALUES (?, ?, ?, 1)
        ''', (task_id, a['id'], a['status']))
    conn.commit()
    conn.close()
    return jsonify({'id': task_id, 'task_no': task_no}), 201


@app.route('/api/inventories/<int:task_id>', methods=['GET'])
@login_required
@require_permission('inventory')
def get_inventory_detail(task_id):
    conn = get_db()
    task = conn.execute('SELECT * FROM inventory_task WHERE id = ?', (task_id,)).fetchone()
    if not task:
        conn.close()
        return jsonify({'error': '盘点任务不存在'}), 404
    items = conn.execute('''
        SELECT ii.*, a.asset_no, a.name as asset_name, a.location, a.department, a.custodian
        FROM inventory_item ii
        LEFT JOIN asset a ON ii.asset_id = a.id
        WHERE ii.task_id = ?
        ORDER BY ii.is_matched, a.asset_no
    ''', (task_id,)).fetchall()
    conn.close()
    result = dict(task)
    result['items'] = [dict(r) for r in items]
    return jsonify(result)


@app.route('/api/inventories/<int:task_id>/check', methods=['POST'])
@login_required
@require_permission('inventory')
def check_inventory_item(task_id):
    data = request.get_json()
    conn = get_db()
    conn.execute('''
        UPDATE inventory_item SET actual_status=?, is_matched=?, operator=?, check_time=?, remark=?
        WHERE task_id=? AND asset_id=?
    ''', (data.get('actual_status'), 1 if data.get('actual_status') == data.get('expected_status') else 0,
          data.get('operator', '系统'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
          data.get('remark', ''), task_id, data['asset_id']))
    conn.commit()
    conn.close()
    return jsonify({'message': '盘点确认成功'})


@app.route('/api/inventories/<int:task_id>/complete', methods=['POST'])
@login_required
@require_permission('inventory')
def complete_inventory(task_id):
    conn = get_db()
    conn.execute('UPDATE inventory_task SET status=?, completed_at=? WHERE id=?',
                 ('completed', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), task_id))
    conn.commit()
    conn.close()
    return jsonify({'message': '盘点完成'})


@app.route('/api/inventories/<int:task_id>/start', methods=['POST'])
@login_required
@require_permission('inventory')
def start_inventory(task_id):
    conn = get_db()
    row = conn.execute('SELECT status FROM inventory_task WHERE id = ?', (task_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': '任务不存在'}), 404
    if row['status'] != 'pending':
        conn.close()
        return jsonify({'error': '任务已在进行中或已完成'}), 400
    conn.execute("UPDATE inventory_task SET status='in_progress' WHERE id=?", (task_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': '已开始盘点'})


# ==================== 预警 API ====================

@app.route('/api/alerts', methods=['GET'])
@login_required
@require_permission('alert')
def get_alerts():
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    warning_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
    alerts = []
    rows = conn.execute('''
        SELECT id, asset_no, name, warranty_expire, 'warranty' as alert_type
        FROM asset WHERE warranty_expire IS NOT NULL AND status != 'scrapped'
        AND warranty_expire <= ? AND warranty_expire >= ?
        ORDER BY warranty_expire
    ''', (warning_date, today)).fetchall()
    for r in rows:
        d = dict(r)
        days_left = (datetime.strptime(r['warranty_expire'], '%Y-%m-%d') - datetime.now()).days
        d['level'] = 'danger' if days_left <= 7 else 'warning'
        d['message'] = f"资产 {r['asset_no']}({r['name']}) 保修将于 {r['warranty_expire']} 到期（剩余{days_left}天）"
        alerts.append(d)
    rows = conn.execute('''
        SELECT id, name, version, expire_date, 'license' as alert_type
        FROM software WHERE expire_date IS NOT NULL
        AND expire_date <= ? AND expire_date >= ?
        ORDER BY expire_date
    ''', (warning_date, today)).fetchall()
    for r in rows:
        d = dict(r)
        days_left = (datetime.strptime(r['expire_date'], '%Y-%m-%d') - datetime.now()).days
        d['level'] = 'danger' if days_left <= 7 else 'warning'
        d['message'] = f"软件 {r['name']} {r['version']} 授权将于 {r['expire_date']} 到期（剩余{days_left}天）"
        alerts.append(d)
    rows = conn.execute('''
        SELECT id, contract_no, title, end_date, 'contract' as alert_type
        FROM contract WHERE status = 'active'
        AND end_date <= ? AND end_date >= ?
        ORDER BY end_date
    ''', (warning_date, today)).fetchall()
    for r in rows:
        d = dict(r)
        days_left = (datetime.strptime(r['end_date'], '%Y-%m-%d') - datetime.now()).days
        d['level'] = 'danger' if days_left <= 7 else 'warning'
        d['message'] = f"合同 {r['contract_no']}({r['title']}) 将于 {r['end_date']} 到期（剩余{days_left}天）"
        alerts.append(d)
    rows = conn.execute('''
        SELECT id, domain_name, registrar, custodian, expire_date, 'domain' as alert_type
        FROM domain WHERE status != 'expired'
        AND expire_date <= ? AND expire_date >= ?
        ORDER BY expire_date
    ''', (warning_date, today)).fetchall()
    for r in rows:
        d = dict(r)
        days_left = (datetime.strptime(r['expire_date'], '%Y-%m-%d') - datetime.now()).days
        d['level'] = 'danger' if days_left <= 30 else 'warning'
        d['message'] = f"域名 {r['domain_name']} 将于 {r['expire_date']} 到期（剩余{days_left}天），请及时续费"
        alerts.append(d)
    conn.close()
    alerts.sort(key=lambda x: 0 if x['level'] == 'danger' else 1)
    return jsonify(alerts)


# ==================== 报表 API ====================

@app.route('/api/reports/overview', methods=['GET'])
@login_required
@require_permission('report')
def report_overview():
    conn = get_db()
    status_stats = conn.execute('SELECT status, COUNT(*) as count FROM asset GROUP BY status').fetchall()
    category_stats = conn.execute('''
        SELECT c.name, COUNT(a.id) as count, COALESCE(SUM(a.purchase_price), 0) as total_value
        FROM category c
        LEFT JOIN asset a ON a.category_id = c.id AND c.parent_id IS NULL
        GROUP BY c.id ORDER BY count DESC
    ''').fetchall()
    dept_stats = conn.execute('''
        SELECT department, COUNT(*) as count, COALESCE(SUM(purchase_price), 0) as total_value
        FROM asset WHERE department IS NOT NULL AND department != ''
        GROUP BY department ORDER BY count DESC
    ''').fetchall()
    total = conn.execute('SELECT COUNT(*) as cnt, COALESCE(SUM(purchase_price),0) as val FROM asset').fetchone()
    in_use = conn.execute("SELECT COUNT(*) as cnt FROM asset WHERE status='in_use'").fetchone()
    in_stock = conn.execute("SELECT COUNT(*) as cnt FROM asset WHERE status='in_stock'").fetchone()
    repair = conn.execute("SELECT COUNT(*) as cnt FROM asset WHERE status='repair'").fetchone()
    scrapped = conn.execute("SELECT COUNT(*) as cnt FROM asset WHERE status='scrapped'").fetchone()
    conn.close()
    return jsonify({
        'total_count': total['cnt'], 'total_value': total['val'],
        'in_use_count': in_use['cnt'], 'in_stock_count': in_stock['cnt'],
        'repair_count': repair['cnt'], 'scrapped_count': scrapped['cnt'],
        'status_stats': [dict(r) for r in status_stats],
        'category_stats': [dict(r) for r in category_stats],
        'dept_stats': [dict(r) for r in dept_stats],
    })


@app.route('/api/reports/depreciation', methods=['GET'])
@login_required
@require_permission('report')
def report_depreciation():
    conn = get_db()
    rows = conn.execute('''
        SELECT a.id, a.asset_no, a.name, a.purchase_date, a.purchase_price,
               a.depreciation_method, a.useful_life, a.residual_rate, a.current_value,
               c.name as category_name
        FROM asset a
        LEFT JOIN category c ON a.category_id = c.id
        WHERE a.status NOT IN ('scrapped','disposed') AND a.purchase_price IS NOT NULL
        ORDER BY a.purchase_date
    ''').fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        if r['purchase_date'] and r['purchase_price'] and r['useful_life']:
            purchase_dt = datetime.strptime(r['purchase_date'], '%Y-%m-%d')
            months_used = max(0, (datetime.now() - purchase_dt).days // 30)
            residual_value = r['purchase_price'] * r['residual_rate'] / 100
            monthly_depr = (r['purchase_price'] - residual_value) / r['useful_life'] if r['useful_life'] else 0
            accum_depr = min(monthly_depr * months_used, r['purchase_price'] - residual_value)
            book_value = r['purchase_price'] - accum_depr
            d['months_used'] = months_used
            d['monthly_depreciation'] = round(monthly_depr, 2)
            d['accumulated_depreciation'] = round(accum_depr, 2)
            d['book_value'] = round(book_value, 2)
        result.append(d)
    return jsonify(result)


# ==================== 域名管理 API ====================

@app.route('/api/domains', methods=['GET'])
@login_required
@require_permission('domain')
def get_domains():
    conn = get_db()
    rows = conn.execute('SELECT * FROM domain ORDER BY expire_date ASC').fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d['expire_date']:
            try:
                exp_dt = datetime.strptime(d['expire_date'], '%Y-%m-%d')
                days_left = (exp_dt - datetime.now()).days
                d['days_left'] = days_left
                # 仅在内存中计算状态，不修改数据库（避免 GET 请求产生副作用）
                if days_left <= 30 and days_left > 0:
                    d['status'] = 'urgent'
                elif days_left <= 0:
                    d['status'] = 'expired'
            except (ValueError, TypeError):
                d['days_left'] = None
        else:
            d['days_left'] = None
        if d['start_date'] and d['expire_date']:
            try:
                start_dt = datetime.strptime(d['start_date'], '%Y-%m-%d')
                exp_dt = datetime.strptime(d['expire_date'], '%Y-%m-%d')
                total_days = max(1, (exp_dt - start_dt).days)
                used_days = min(total_days, (datetime.now() - start_dt).days)
                d['total_days'] = total_days
                d['used_days'] = used_days
                d['progress_percent'] = round((used_days / total_days) * 100, 1)
            except (ValueError, TypeError):
                d['total_days'] = None
                d['used_days'] = None
                d['progress_percent'] = 0
        result.append(d)
    conn.close()
    return jsonify(result)


@app.route('/api/domains', methods=['POST'])
@login_required
@require_permission('domain')
def create_domain():
    data = request.get_json()
    conn = get_db()
    status = 'active'
    if data.get('expire_date'):
        try:
            days_left = (datetime.strptime(data['expire_date'], '%Y-%m-%d') - datetime.now()).days
            if days_left <= 30 and days_left > 0:
                status = 'urgent'
            elif days_left <= 0:
                status = 'expired'
        except (ValueError, TypeError):
            pass
    try:
        cursor = conn.execute('''
            INSERT INTO domain (domain_name, registrar, start_date, expire_date,
                purchase_price, dns_server, status, auto_renew, custodian, remark)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (data['domain_name'], data['registrar'], data['start_date'],
              data['expire_date'], data.get('purchase_price'), data.get('dns_server'),
              status, int(data.get('auto_renew', False)), data.get('custodian'),
              data.get('remark')))
        conn.commit()
    except Exception as e:
        conn.close()
        if 'UNIQUE constraint failed' in str(e):
            return jsonify({'error': '域名已存在'}), 400
        app.logger.error(f"create_domain error: {e}", exc_info=True)
        return jsonify({'error': '操作失败，请检查输入数据'}), 400
    conn.close()
    return jsonify({'id': cursor.lastrowid}), 201


@app.route('/api/domains/<int:did>', methods=['PUT'])
@login_required
@require_permission('domain')
def update_domain(did):
    data = request.get_json()
    conn = get_db()
    fields = ['domain_name', 'registrar', 'start_date', 'expire_date',
              'purchase_price', 'dns_server', 'auto_renew', 'custodian', 'remark']
    set_fields = [f'{f} = ?' for f in fields]
    params = [data.get(f) for f in fields] + [did]
    conn.execute(f'UPDATE domain SET {", ".join(set_fields)}, updated_at=? WHERE id=?',
                 params + [datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
    conn.commit()
    conn.close()
    return jsonify({'message': '更新成功'})


@app.route('/api/domains/<int:did>', methods=['DELETE'])
@login_required
@require_permission('domain')
def delete_domain(did):
    conn = get_db()
    conn.execute('DELETE FROM domain WHERE id = ?', (did,))
    conn.commit()
    conn.close()
    return jsonify({'message': '删除成功'})


@app.route('/api/domains/<int:did>/renew', methods=['POST'])
@login_required
@require_permission('domain')
def renew_domain(did):
    data = request.get_json()
    new_expire = data.get('expire_date')
    if not new_expire:
        return jsonify({'error': '请提供新的到期时间'}), 400
    conn = get_db()
    conn.execute('''UPDATE domain SET expire_date=?, status='active', updated_at=?
                   WHERE id=?''', (new_expire, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), did))
    conn.commit()
    conn.close()
    return jsonify({'message': f'续费成功，新到期时间：{new_expire}'})


# ==================== 设备台账 API ====================

@app.route('/api/equipment', methods=['GET'])
@login_required
@require_permission('equipment')
def get_equipment():
    conn = get_db()
    params = []
    conditions = []
    equip_type = request.args.get('equip_type')
    status = request.args.get('status')
    keyword = request.args.get('keyword')
    if equip_type:
        conditions.append('e.equip_type = ?')
        params.append(equip_type)
    if status:
        conditions.append('e.status = ?')
        params.append(status)
    if keyword:
        conditions.append('(e.name LIKE ? OR e.equip_no LIKE ? OR e.serial_no LIKE ? OR e.ip_addr LIKE ?)')
        params.extend([f'%{keyword}%'] * 4)
    where = ' AND '.join(conditions) if conditions else '1=1'
    rows = conn.execute(f'''
        SELECT e.*, u.real_name as custodian_name
        FROM equipment e
        LEFT JOIN user u ON e.custodian_id = u.id
        WHERE {where}
        ORDER BY e.updated_at DESC
    ''', params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/equipment/<int:eid>', methods=['GET'])
@login_required
@require_permission('equipment')
def get_equipment_detail(eid):
    conn = get_db()
    row = conn.execute('''
        SELECT e.*, u.real_name as custodian_name
        FROM equipment e
        LEFT JOIN user u ON e.custodian_id = u.id
        WHERE e.id = ?
    ''', (eid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': '设备不存在'}), 404
    conn.close()
    return jsonify(dict(row))


@app.route('/api/equipment', methods=['POST'])
@login_required
@require_permission('equipment')
def create_equipment():
    data = request.get_json()
    conn = get_db()
    equip_no = data.get('equip_no') or generate_equip_no(data['equip_type'])
    try:
        cursor = conn.execute('''
            INSERT INTO equipment (equip_no, name, equip_type, brand, model, serial_no,
                ip_addr, mgmt_ip, location, department, custodian_id, specs, status,
                purchase_date, warranty_expire, remark)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (equip_no, data['name'], data['equip_type'], data.get('brand'),
              data.get('model'), data.get('serial_no'), data.get('ip_addr'),
              data.get('mgmt_ip'), data.get('location'), data.get('department'),
              data.get('custodian_id'), data.get('specs'), data.get('status', 'normal'),
              data.get('purchase_date'), data.get('warranty_expire'), data.get('remark')))
        conn.commit()
    except Exception as e:
        conn.close()
        app.logger.error(f"create_equipment error: {e}", exc_info=True)
        return jsonify({'error': '操作失败，请检查输入数据'}), 400
    conn.close()
    return jsonify({'id': cursor.lastrowid, 'equip_no': equip_no}), 201


@app.route('/api/equipment/<int:eid>', methods=['PUT'])
@login_required
@require_permission('equipment')
def update_equipment(eid):
    data = request.get_json()
    conn = get_db()
    fields = []
    params = []
    for f in ['name', 'equip_type', 'brand', 'model', 'serial_no', 'ip_addr', 'mgmt_ip',
              'location', 'department', 'custodian_id', 'specs', 'status',
              'purchase_date', 'warranty_expire', 'remark']:
        if f in data:
            fields.append(f'{f} = ?')
            params.append(data[f])
    if not fields:
        conn.close()
        return jsonify({'error': '无更新内容'}), 400
    fields.append('updated_at = ?')
    params.append(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    params.append(eid)
    conn.execute(f'UPDATE equipment SET {", ".join(fields)} WHERE id = ?', params)
    conn.commit()
    conn.close()
    return jsonify({'message': '更新成功'})


@app.route('/api/equipment/<int:eid>', methods=['DELETE'])
@login_required
@require_permission('equipment')
def delete_equipment(eid):
    conn = get_db()
    conn.execute('DELETE FROM equipment WHERE id = ?', (eid,))
    conn.commit()
    conn.close()
    return jsonify({'message': '删除成功'})


# ==================== 巡检模板 API ====================

@app.route('/api/inspection/templates', methods=['GET'])
@login_required
@require_permission('inspection')
def get_inspection_templates():
    conn = get_db()
    equip_type = request.args.get('equip_type')
    if equip_type:
        rows = conn.execute(
            'SELECT * FROM inspection_template WHERE equip_type = ? ORDER BY sort_order',
            (equip_type,)).fetchall()
    else:
        rows = conn.execute('SELECT * FROM inspection_template ORDER BY equip_type, sort_order').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/inspection/templates', methods=['POST'])
@login_required
@admin_required
def create_inspection_template():
    data = request.get_json()
    conn = get_db()
    try:
        cursor = conn.execute('''
            INSERT INTO inspection_template
            (equip_type, item_name, item_desc, item_type, unit, normal_range, is_required, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (data['equip_type'], data['item_name'], data.get('item_desc', ''),
              data.get('item_type', 'checkbox'), data.get('unit', ''),
              data.get('normal_range', ''), data.get('is_required', 1),
              data.get('sort_order', 0)))
        conn.commit()
    except Exception as e:
        conn.close()
        app.logger.error(f"create error: {e}", exc_info=True)
        return jsonify({'error': '操作失败，请检查输入数据'}), 400
    conn.close()
    return jsonify({'id': cursor.lastrowid}), 201


@app.route('/api/inspection/templates/<int:tid>', methods=['PUT'])
@login_required
@admin_required
def update_inspection_template(tid):
    data = request.get_json()
    conn = get_db()
    fields = []
    params = []
    for f in ['equip_type', 'item_name', 'item_desc', 'item_type', 'unit',
              'normal_range', 'is_required', 'sort_order']:
        if f in data:
            fields.append(f'{f} = ?')
            params.append(data[f])
    if not fields:
        conn.close()
        return jsonify({'error': '无更新内容'}), 400
    params.append(tid)
    conn.execute(f'UPDATE inspection_template SET {", ".join(fields)} WHERE id = ?', params)
    conn.commit()
    conn.close()
    return jsonify({'message': '更新成功'})


@app.route('/api/inspection/templates/<int:tid>', methods=['DELETE'])
@login_required
@admin_required
def delete_inspection_template(tid):
    conn = get_db()
    conn.execute('DELETE FROM inspection_template WHERE id = ?', (tid,))
    conn.commit()
    conn.close()
    return jsonify({'message': '删除成功'})


# ==================== 巡检任务分配 API ====================

def _generate_task_records_for_date(conn, target_date_str=None):
    """为指定日期（默认今天）生成所有活跃任务的当日执行记录"""
    from datetime import date as date_type
    target = target_date_str or datetime.now().strftime('%Y-%m-%d')
    target_dt = datetime.strptime(target, '%Y-%m-%d').date()
    weekday = target_dt.weekday()  # 0=周一, 6=周日
    day_of_month = target_dt.day

    tasks = conn.execute(
        "SELECT * FROM inspection_task WHERE status = 'active'"
    ).fetchall()

    for t in tasks:
        freq = t['frequency']
        # 判断该日期是否需要执行
        should_run = False
        if freq == 'daily':
            should_run = True
        elif freq == 'weekly' and weekday == 0:  # 每周一
            should_run = True
        elif freq == 'monthly' and day_of_month == 1:  # 每月1号
            should_run = True

        if not should_run:
            continue

        # 避免重复创建
        try:
            conn.execute('''
                INSERT OR IGNORE INTO inspection_task_record
                (task_id, plan_date, engineer_id, status)
                VALUES (?, ?, ?, 'pending')
            ''', (t['id'], target, t['engineer_id']))
        except Exception:
            pass

    conn.commit()


@app.route('/api/inspection/tasks', methods=['GET'])
@login_required
@require_permission('inspection')
def get_inspection_tasks():
    conn = get_db()
    params = []
    conditions = []
    engineer_id = request.args.get('engineer_id')
    equipment_id = request.args.get('equipment_id')
    status = request.args.get('status')
    my_tasks = request.args.get('my_tasks')

    if engineer_id:
        conditions.append('t.engineer_id = ?')
        params.append(engineer_id)
    if equipment_id:
        conditions.append('t.equipment_id = ?')
        params.append(equipment_id)
    if status:
        conditions.append('t.status = ?')
        params.append(status)
    if my_tasks == '1':
        conditions.append('t.engineer_id = ?')
        params.append(session['user_id'])

    where = ' AND '.join(conditions) if conditions else '1=1'
    rows = conn.execute(f'''
        SELECT t.*, e.name as equipment_name, e.equip_no, e.equip_type,
               u.real_name as engineer_name, creator.real_name as creator_name
        FROM inspection_task t
        LEFT JOIN equipment e ON t.equipment_id = e.id
        LEFT JOIN user u ON t.engineer_id = u.id
        LEFT JOIN user creator ON t.created_by = creator.id
        WHERE {where}
        ORDER BY t.next_date ASC, t.id DESC
    ''', params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/inspection/tasks', methods=['POST'])
@login_required
@admin_required
def create_inspection_task():
    data = request.get_json()
    conn = get_db()
    try:
        cursor = conn.execute('''
            INSERT INTO inspection_task
            (task_name, equipment_id, equip_type, engineer_id, frequency, next_date,
             reminder_time, status, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
        ''', (data['task_name'], data.get('equipment_id'), data.get('equip_type'),
              data['engineer_id'], data.get('frequency', 'daily'),
              data['next_date'], data.get('reminder_time', '17:00'), session['user_id']))
        task_id = cursor.lastrowid
        conn.commit()
        # 立即为今天生成执行记录
        _generate_task_records_for_date(conn)
    except Exception as e:
        conn.close()
        app.logger.error(f"create_inspection_task error: {e}", exc_info=True)
        return jsonify({'error': '操作失败，请检查输入数据'}), 400
    conn.close()
    return jsonify({'id': task_id}), 201


@app.route('/api/inspection/tasks/<int:tid>', methods=['PUT'])
@login_required
@admin_required
def update_inspection_task(tid):
    data = request.get_json()
    conn = get_db()
    fields = []
    params = []
    for f in ['task_name', 'equipment_id', 'equip_type', 'engineer_id',
              'frequency', 'next_date', 'reminder_time', 'status']:
        if f in data:
            fields.append(f'{f} = ?')
            params.append(data[f])
    if not fields:
        conn.close()
        return jsonify({'error': '无更新内容'}), 400
    params.append(tid)
    conn.execute(f'UPDATE inspection_task SET {", ".join(fields)} WHERE id = ?', params)
    conn.commit()
    conn.close()
    return jsonify({'message': '更新成功'})


@app.route('/api/inspection/tasks/<int:tid>', methods=['DELETE'])
@login_required
@admin_required
def delete_inspection_task(tid):
    conn = get_db()
    conn.execute('DELETE FROM inspection_task_record WHERE task_id = ?', (tid,))
    conn.execute('DELETE FROM inspection_task WHERE id = ?', (tid,))
    conn.commit()
    conn.close()
    return jsonify({'message': '删除成功'})


@app.route('/api/inspection/tasks/today', methods=['GET'])
@login_required
@require_permission('inspection')
def get_today_task_records():
    """获取今日的巡检任务记录（工程师看自己的，管理员看全部）"""
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    # 先生成今日记录
    _generate_task_records_for_date(conn)

    if session.get('role') == 'admin':
        rows = conn.execute('''
            SELECT r.*, t.task_name, t.equipment_id, t.equip_type, t.frequency,
                   t.reminder_time,
                   e.name as equipment_name, e.equip_no,
                   u.real_name as engineer_name
            FROM inspection_task_record r
            JOIN inspection_task t ON r.task_id = t.id
            LEFT JOIN equipment e ON t.equipment_id = e.id
            LEFT JOIN user u ON r.engineer_id = u.id
            WHERE r.plan_date = ?
            ORDER BY r.status, u.real_name
        ''', (today,)).fetchall()
    else:
        rows = conn.execute('''
            SELECT r.*, t.task_name, t.equipment_id, t.equip_type, t.frequency,
                   t.reminder_time,
                   e.name as equipment_name, e.equip_no,
                   u.real_name as engineer_name
            FROM inspection_task_record r
            JOIN inspection_task t ON r.task_id = t.id
            LEFT JOIN equipment e ON t.equipment_id = e.id
            LEFT JOIN user u ON r.engineer_id = u.id
            WHERE r.plan_date = ? AND r.engineer_id = ?
            ORDER BY r.status
        ''', (today, session['user_id'])).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/inspection/tasks/my-devices', methods=['GET'])
@login_required
@require_permission('inspection')
def get_my_task_devices():
    """获取当前用户巡检任务涉及的所有设备（用于工作日志关联）"""
    conn = get_db()
    user_id = session['user_id']
    rows = conn.execute('''
        SELECT DISTINCT t.equipment_id as id,
               e.name as equipment_name,
               e.equip_no,
               e.equip_type,
               t.task_name
        FROM inspection_task t
        LEFT JOIN equipment e ON t.equipment_id = e.id
        WHERE t.engineer_id = ? AND t.status = 'active' AND t.equipment_id IS NOT NULL
        ORDER BY e.equip_type, e.equip_no
    ''', (user_id,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/inspection/tasks/my-records', methods=['GET'])
@login_required
@require_permission('inspection')
def get_my_task_records():
    """获取当前用户的巡检任务记录（用于工作日志关联，不限今日）"""
    conn = get_db()
    user_id = session['user_id']
    date = request.args.get('date')
    params = [user_id]
    extra = ''
    if date:
        extra = 'AND r.plan_date = ?'
        params.append(date)
    rows = conn.execute(f'''
        SELECT r.id, r.task_id, r.plan_date, r.status, r.completed_at,
               t.task_name, t.equip_type,
               e.name as equipment_name, e.equip_no
        FROM inspection_task_record r
        JOIN inspection_task t ON r.task_id = t.id
        LEFT JOIN equipment e ON t.equipment_id = e.id
        WHERE r.engineer_id = ? {extra}
        ORDER BY r.plan_date DESC, t.task_name
    ''', params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/inspection/tasks/records', methods=['GET'])
@login_required
@admin_required
def get_task_records():
    """管理员查看指定日期范围内的任务完成情况"""
    conn = get_db()
    start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    engineer_id = request.args.get('engineer_id')

    params = [start_date, end_date]
    extra = ''
    if engineer_id:
        extra = 'AND r.engineer_id = ?'
        params.append(engineer_id)

    rows = conn.execute(f'''
        SELECT r.*, t.task_name, t.frequency, t.reminder_time,
               t.equipment_id, t.equip_type,
               e.name as equipment_name, e.equip_no,
               u.real_name as engineer_name
        FROM inspection_task_record r
        JOIN inspection_task t ON r.task_id = t.id
        LEFT JOIN equipment e ON t.equipment_id = e.id
        LEFT JOIN user u ON r.engineer_id = u.id
        WHERE r.plan_date BETWEEN ? AND ? {extra}
        ORDER BY r.plan_date DESC, u.real_name
    ''', params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/inspection/tasks/records/<int:rid>', methods=['PUT'])
@login_required
@require_permission('inspection')
def complete_task_record(rid):
    """工程师完成巡检任务记录"""
    data = request.get_json()
    conn = get_db()
    # 工程师只能更新自己的记录
    row = conn.execute('SELECT * FROM inspection_task_record WHERE id = ?', (rid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': '记录不存在'}), 404
    if session.get('role') != 'admin' and row['engineer_id'] != session['user_id']:
        conn.close()
        return jsonify({'error': '无权操作他人记录'}), 403
    conn.execute('''
        UPDATE inspection_task_record
        SET status = 'completed', completed_at = CURRENT_TIMESTAMP,
            inspection_id = ?, remark = ?
        WHERE id = ?
    ''', (data.get('inspection_id'), data.get('remark', ''), rid))
    conn.commit()
    conn.close()
    return jsonify({'message': '已标记完成'})


@app.route('/api/inspection/tasks/stats', methods=['GET'])
@login_required
@admin_required
def get_task_completion_stats():
    """获取巡检任务完成率统计（用于报表）"""
    conn = get_db()
    start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-01'))
    end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))

    # 按日期统计
    daily_stats = conn.execute('''
        SELECT plan_date,
               COUNT(*) as total,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed,
               SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending,
               SUM(CASE WHEN status='overdue' THEN 1 ELSE 0 END) as overdue
        FROM inspection_task_record
        WHERE plan_date BETWEEN ? AND ?
        GROUP BY plan_date
        ORDER BY plan_date
    ''', (start_date, end_date)).fetchall()

    # 按工程师统计
    engineer_stats = conn.execute('''
        SELECT u.real_name as engineer_name, u.id as engineer_id,
               COUNT(*) as total,
               SUM(CASE WHEN r.status='completed' THEN 1 ELSE 0 END) as completed
        FROM inspection_task_record r
        JOIN user u ON r.engineer_id = u.id
        WHERE r.plan_date BETWEEN ? AND ?
        GROUP BY r.engineer_id
        ORDER BY completed DESC
    ''', (start_date, end_date)).fetchall()

    conn.close()
    return jsonify({
        'daily': [dict(r) for r in daily_stats],
        'by_engineer': [dict(r) for r in engineer_stats]
    })


# ==================== 每日巡检 API ====================

@app.route('/api/inspections', methods=['GET'])
@login_required
@require_permission('inspection')
def get_inspections():
    conn = get_db()
    params = []
    conditions = []
    date = request.args.get('date')
    equipment_id = request.args.get('equipment_id')
    engineer_id = request.args.get('engineer_id')
    status = request.args.get('status')
    if date:
        conditions.append('di.inspection_date = ?')
        params.append(date)
    if equipment_id:
        conditions.append('di.equipment_id = ?')
        params.append(equipment_id)
    if engineer_id:
        conditions.append('di.engineer_id = ?')
        params.append(engineer_id)
    if status:
        conditions.append('di.status = ?')
        params.append(status)
    where = ' AND '.join(conditions) if conditions else '1=1'
    rows = conn.execute(f'''
        SELECT di.*, e.name as equipment_name, e.equip_no, e.equip_type,
               u.real_name as engineer_name
        FROM daily_inspection di
        LEFT JOIN equipment e ON di.equipment_id = e.id
        LEFT JOIN user u ON di.engineer_id = u.id
        WHERE {where}
        ORDER BY di.inspection_date DESC, di.id DESC
    ''', params).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d['items'] = json.loads(r['items_json']) if r['items_json'] else []
        result.append(d)
    return jsonify(result)


@app.route('/api/inspections/<int:iid>', methods=['GET'])
@login_required
@require_permission('inspection')
def get_inspection(iid):
    conn = get_db()
    row = conn.execute('''
        SELECT di.*, e.name as equipment_name, e.equip_no, e.equip_type,
               u.real_name as engineer_name
        FROM daily_inspection di
        LEFT JOIN equipment e ON di.equipment_id = e.id
        LEFT JOIN user u ON di.engineer_id = u.id
        WHERE di.id = ?
    ''', (iid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': '巡检记录不存在'}), 404
    result = dict(row)
    result['items'] = json.loads(row['items_json']) if row['items_json'] else []
    conn.close()
    return jsonify(result)


@app.route('/api/inspections', methods=['POST'])
@login_required
@require_permission('inspection')
def create_inspection():
    data = request.get_json()
    conn = get_db()
    items_json = json.dumps(data.get('items', []), ensure_ascii=False)
    status = data.get('status', 'normal')
    abnormal_items = data.get('abnormal_items', '')
    try:
        cursor = conn.execute('''
            INSERT INTO daily_inspection (inspection_date, equipment_id, engineer_id,
                items_json, status, abnormal_items, action_taken, duration_minutes, remark)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (data.get('inspection_date', datetime.now().strftime('%Y-%m-%d')),
              data['equipment_id'], session['user_id'], items_json, status,
              abnormal_items, data.get('action_taken'), data.get('duration_minutes', 0),
              data.get('remark')))
        conn.commit()
    except Exception as e:
        conn.close()
        app.logger.error(f"create error: {e}", exc_info=True)
        return jsonify({'error': '操作失败，请检查输入数据'}), 400
    conn.close()
    return jsonify({'id': cursor.lastrowid}), 201


@app.route('/api/inspections/<int:iid>', methods=['PUT'])
@login_required
@require_permission('inspection')
def update_inspection(iid):
    data = request.get_json()
    conn = get_db()
    fields = []
    params = []
    for f in ['inspection_date', 'equipment_id', 'items_json', 'status',
              'abnormal_items', 'action_taken', 'duration_minutes', 'remark']:
        if f in data:
            fields.append(f'{f} = ?')
            if f == 'items_json':
                params.append(json.dumps(data[f], ensure_ascii=False))
            else:
                params.append(data[f])
    if not fields:
        conn.close()
        return jsonify({'error': '无更新内容'}), 400
    params.append(iid)
    conn.execute(f'UPDATE daily_inspection SET {", ".join(fields)} WHERE id = ?', params)
    conn.commit()
    conn.close()
    return jsonify({'message': '更新成功'})


@app.route('/api/inspections/<int:iid>', methods=['DELETE'])
@login_required
@require_permission('inspection')
def delete_inspection(iid):
    conn = get_db()
    conn.execute('DELETE FROM daily_inspection WHERE id = ?', (iid,))
    conn.commit()
    conn.close()
    return jsonify({'message': '删除成功'})


# ==================== 工作日志 API ====================

@app.route('/api/worklogs', methods=['GET'])
@login_required
@require_permission('worklog')
def get_worklogs():
    conn = get_db()
    params = []
    conditions = []
    date = request.args.get('date')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    user_id = request.args.get('user_id')
    work_type = request.args.get('work_type')
    keyword = request.args.get('keyword')
    if date:
        conditions.append('wl.log_date = ?')
        params.append(date)
    if start_date:
        conditions.append('wl.log_date >= ?')
        params.append(start_date)
    if end_date:
        conditions.append('wl.log_date <= ?')
        params.append(end_date)
    if user_id:
        conditions.append('wl.user_id = ?')
        params.append(user_id)
    if work_type:
        conditions.append('wl.work_type = ?')
        params.append(work_type)
    if keyword:
        conditions.append('(wl.title LIKE ? OR wl.content LIKE ?)')
        params.extend([f'%{keyword}%'] * 2)
    where = ' AND '.join(conditions) if conditions else '1=1'
    rows = conn.execute(f'''
        SELECT wl.*, u.real_name as user_name, u.username
        FROM work_log wl
        LEFT JOIN user u ON wl.user_id = u.id
        WHERE {where}
        ORDER BY wl.log_date DESC, wl.id DESC
    ''', params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/worklogs', methods=['POST'])
@login_required
@require_permission('worklog')
def create_worklog():
    data = request.get_json()
    conn = get_db()
    try:
        cursor = conn.execute('''
            INSERT INTO work_log (log_date, user_id, title, content, work_type,
                equipment_ids, inspection_ids, duration_minutes, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (data.get('log_date', datetime.now().strftime('%Y-%m-%d')),
              session['user_id'], data['title'], data['content'],
              data.get('work_type', 'other'), data.get('equipment_ids', ''),
              data.get('inspection_ids', ''), data.get('duration_minutes', 0),
              data.get('status', 'draft')))
        conn.commit()
    except Exception as e:
        conn.close()
        app.logger.error(f"create error: {e}", exc_info=True)
        return jsonify({'error': '操作失败，请检查输入数据'}), 400
    conn.close()
    return jsonify({'id': cursor.lastrowid}), 201


@app.route('/api/worklogs/<int:wid>', methods=['GET'])
@login_required
@require_permission('worklog')
def get_worklog(wid):
    conn = get_db()
    row = conn.execute('''
        SELECT wl.*, u.real_name as user_name
        FROM work_log wl
        LEFT JOIN user u ON wl.user_id = u.id
        WHERE wl.id = ?
    ''', (wid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': '工作日志不存在'}), 404
    result = dict(row)
    # 解析关联设备
    if result.get('equipment_ids'):
        equip_ids = [int(x) for x in result['equipment_ids'].split(',') if x.strip().isdigit()]
        if equip_ids:
            placeholders = ','.join('?' * len(equip_ids))
            eq_rows = conn.execute(f'SELECT id, equip_no, name, equip_type FROM equipment WHERE id IN ({placeholders})', equip_ids).fetchall()
            result['equipments'] = [dict(r) for r in eq_rows]
    # 解析关联巡检
    if result.get('inspection_ids'):
        insp_ids = [int(x) for x in result['inspection_ids'].split(',') if x.strip().isdigit()]
        if insp_ids:
            placeholders = ','.join('?' * len(insp_ids))
            in_rows = conn.execute(f'''
                SELECT di.id, di.inspection_date, e.name as equipment_name, di.status
                FROM daily_inspection di
                LEFT JOIN equipment e ON di.equipment_id = e.id
                WHERE di.id IN ({placeholders})
            ''', insp_ids).fetchall()
            result['inspections'] = [dict(r) for r in in_rows]
    conn.close()
    return jsonify(result)


@app.route('/api/worklogs/<int:wid>', methods=['PUT'])
@login_required
@require_permission('worklog')
def update_worklog(wid):
    data = request.get_json()
    conn = get_db()
    fields = []
    params = []
    for f in ['log_date', 'title', 'content', 'work_type', 'equipment_ids',
              'inspection_ids', 'duration_minutes', 'status']:
        if f in data:
            fields.append(f'{f} = ?')
            params.append(data[f])
    if not fields:
        conn.close()
        return jsonify({'error': '无更新内容'}), 400
    fields.append('updated_at = ?')
    params.append(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    params.append(wid)
    conn.execute(f'UPDATE work_log SET {", ".join(fields)} WHERE id = ?', params)
    conn.commit()
    conn.close()
    return jsonify({'message': '更新成功'})


@app.route('/api/worklogs/<int:wid>', methods=['DELETE'])
@login_required
@require_permission('worklog')
def delete_worklog(wid):
    conn = get_db()
    conn.execute('DELETE FROM work_log WHERE id = ?', (wid,))
    conn.commit()
    conn.close()
    return jsonify({'message': '删除成功'})


# ==================== 日报/周报/月报 API ====================

@app.route('/api/reports/list', methods=['GET'])
@login_required
def get_reports_list():
    """获取日报/周报/月报列表，根据用户权限过滤"""
    report_type = request.args.get('report_type', 'daily')
    if report_type == 'daily' and not check_permission('report_daily'):
        return jsonify({'error': '无权访问日报模块'}), 403
    if report_type == 'weekly' and not check_permission('report_weekly'):
        return jsonify({'error': '无权访问周报模块'}), 403
    if report_type == 'monthly' and not check_permission('report_monthly'):
        return jsonify({'error': '无权访问月报模块'}), 403

    conn = get_db()
    params = [report_type]
    conditions = ['r.report_type = ?']
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    user_id = request.args.get('user_id')
    if date_from:
        conditions.append('r.report_date >= ?')
        params.append(date_from)
    if date_to:
        conditions.append('r.report_date <= ?')
        params.append(date_to)
    if user_id:
        conditions.append('r.user_id = ?')
        params.append(user_id)
    elif session.get('role') != 'admin':
        conditions.append('r.user_id = ?')
        params.append(session['user_id'])
    where = ' AND '.join(conditions)
    rows = conn.execute(f'''
        SELECT r.*, u.real_name as user_name
        FROM report r
        LEFT JOIN user u ON r.user_id = u.id
        WHERE {where}
        ORDER BY r.report_date DESC, r.id DESC
    ''', params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/reports', methods=['POST'])
@login_required
def create_report():
    data = request.get_json()
    report_type = data.get('report_type', 'daily')
    if report_type == 'daily' and not check_permission('report_daily'):
        return jsonify({'error': '无权访问日报模块'}), 403
    if report_type == 'weekly' and not check_permission('report_weekly'):
        return jsonify({'error': '无权访问周报模块'}), 403
    if report_type == 'monthly' and not check_permission('report_monthly'):
        return jsonify({'error': '无权访问月报模块'}), 403

    conn = get_db()
    try:
        cursor = conn.execute('''
            INSERT INTO report (report_type, report_date, user_id, title, summary,
                completed_tasks, pending_tasks, problems, equipment_ids, inspection_ids,
                work_log_ids, duration_total, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (report_type, data.get('report_date', datetime.now().strftime('%Y-%m-%d')),
              session['user_id'], data['title'], data.get('summary'),
              data.get('completed_tasks'), data.get('pending_tasks'),
              data.get('problems'), data.get('equipment_ids', ''),
              data.get('inspection_ids', ''), data.get('work_log_ids', ''),
              data.get('duration_total', 0), data.get('status', 'draft')))
        conn.commit()
    except Exception as e:
        conn.close()
        app.logger.error(f"create error: {e}", exc_info=True)
        return jsonify({'error': '操作失败，请检查输入数据'}), 400
    conn.close()
    return jsonify({'id': cursor.lastrowid}), 201


@app.route('/api/reports/<int:rid>', methods=['GET'])
@login_required
def get_report(rid):
    conn = get_db()
    row = conn.execute('''
        SELECT r.*, u.real_name as user_name
        FROM report r
        LEFT JOIN user u ON r.user_id = u.id
        WHERE r.id = ?
    ''', (rid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': '报告不存在'}), 404
    report_type = row['report_type']
    if report_type == 'daily' and not check_permission('report_daily'):
        conn.close()
        return jsonify({'error': '无权访问日报模块'}), 403
    if report_type == 'weekly' and not check_permission('report_weekly'):
        conn.close()
        return jsonify({'error': '无权访问周报模块'}), 403
    if report_type == 'monthly' and not check_permission('report_monthly'):
        conn.close()
        return jsonify({'error': '无权访问月报模块'}), 403
    result = dict(row)
    # 解析关联数据
    if result.get('equipment_ids'):
        equip_ids = [int(x) for x in result['equipment_ids'].split(',') if x.strip().isdigit()]
        if equip_ids:
            placeholders = ','.join('?' * len(equip_ids))
            eq_rows = conn.execute(f'SELECT id, equip_no, name FROM equipment WHERE id IN ({placeholders})', equip_ids).fetchall()
            result['equipments'] = [dict(r) for r in eq_rows]
    if result.get('work_log_ids'):
        wl_ids = [int(x) for x in result['work_log_ids'].split(',') if x.strip().isdigit()]
        if wl_ids:
            placeholders = ','.join('?' * len(wl_ids))
            wl_rows = conn.execute(f'''
                SELECT wl.id, wl.log_date, wl.title, wl.work_type, wl.duration_minutes
                FROM work_log wl WHERE wl.id IN ({placeholders})
            ''', wl_ids).fetchall()
            result['work_logs'] = [dict(r) for r in wl_rows]
    conn.close()
    return jsonify(result)


@app.route('/api/reports/<int:rid>', methods=['PUT'])
@login_required
def update_report(rid):
    data = request.get_json()
    conn = get_db()
    # 先查询报告类型，校验权限
    row = conn.execute('SELECT report_type, user_id FROM report WHERE id = ?', (rid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': '报告不存在'}), 404
    report_type = row['report_type']
    if report_type == 'daily' and not check_permission('report_daily'):
        conn.close()
        return jsonify({'error': '无权访问日报模块'}), 403
    if report_type == 'weekly' and not check_permission('report_weekly'):
        conn.close()
        return jsonify({'error': '无权访问周报模块'}), 403
    if report_type == 'monthly' and not check_permission('report_monthly'):
        conn.close()
        return jsonify({'error': '无权访问月报模块'}), 403
    # 非管理员只能修改自己的报告
    if session.get('role') != 'admin' and row['user_id'] != session['user_id']:
        conn.close()
        return jsonify({'error': '无权修改此报告'}), 403
    fields = []
    params = []
    for f in ['report_date', 'title', 'summary', 'completed_tasks', 'pending_tasks',
              'problems', 'equipment_ids', 'inspection_ids', 'work_log_ids',
              'duration_total', 'status']:
        if f in data:
            fields.append(f'{f} = ?')
            params.append(data[f])
    if not fields:
        conn.close()
        return jsonify({'error': '无更新内容'}), 400
    fields.append('updated_at = ?')
    params.append(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    params.append(rid)
    conn.execute(f'UPDATE report SET {", ".join(fields)} WHERE id = ?', params)
    conn.commit()
    conn.close()
    return jsonify({'message': '更新成功'})


@app.route('/api/reports/<int:rid>', methods=['DELETE'])
@login_required
def delete_report(rid):
    conn = get_db()
    # 先查询报告类型，校验权限
    row = conn.execute('SELECT report_type, user_id FROM report WHERE id = ?', (rid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': '报告不存在'}), 404
    report_type = row['report_type']
    if report_type == 'daily' and not check_permission('report_daily'):
        conn.close()
        return jsonify({'error': '无权访问日报模块'}), 403
    if report_type == 'weekly' and not check_permission('report_weekly'):
        conn.close()
        return jsonify({'error': '无权访问周报模块'}), 403
    if report_type == 'monthly' and not check_permission('report_monthly'):
        conn.close()
        return jsonify({'error': '无权访问月报模块'}), 403
    # 非管理员只能删除自己的报告
    if session.get('role') != 'admin' and row['user_id'] != session['user_id']:
        conn.close()
        return jsonify({'error': '无权删除此报告'}), 403
    conn.execute('DELETE FROM report WHERE id = ?', (rid,))
    conn.commit()
    conn.close()
    return jsonify({'message': '删除成功'})


# ==================== 统计查询 API ====================

@app.route('/api/stats/engineer-work', methods=['GET'])
@login_required
@require_permission('report')
def get_engineer_work_stats():
    """查询工程师在某天的所有工作（日志、巡检）"""
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    user_id = request.args.get('user_id')
    # 非管理员只能查看自己的工作统计
    if session.get('role') != 'admin' and user_id and int(user_id) != session['user_id']:
        return jsonify({'error': '无权查看其他用户的工作统计'}), 403
    conn = get_db()
    result = {'date': date, 'work_logs': [], 'inspections': []}
    # 工作日志
    wl_params = [date]
    wl_where = 'wl.log_date = ?'
    if user_id:
        wl_where += ' AND wl.user_id = ?'
        wl_params.append(user_id)
    rows = conn.execute(f'''
        SELECT wl.*, u.real_name as user_name
        FROM work_log wl
        LEFT JOIN user u ON wl.user_id = u.id
        WHERE {wl_where}
        ORDER BY wl.created_at
    ''', wl_params).fetchall()
    result['work_logs'] = [dict(r) for r in rows]
    # 巡检记录
    in_params = [date]
    in_where = 'di.inspection_date = ?'
    if user_id:
        in_where += ' AND di.engineer_id = ?'
        in_params.append(user_id)
    rows = conn.execute(f'''
        SELECT di.*, e.name as equipment_name, e.equip_no, u.real_name as engineer_name
        FROM daily_inspection di
        LEFT JOIN equipment e ON di.equipment_id = e.id
        LEFT JOIN user u ON di.engineer_id = u.id
        WHERE {in_where}
        ORDER BY di.created_at
    ''', in_params).fetchall()
    for r in rows:
        d = dict(r)
        d['items'] = json.loads(r['items_json']) if r['items_json'] else []
        result['inspections'].append(d)
    # 汇总
    total_duration = sum(wl.get('duration_minutes', 0) for wl in result['work_logs'])
    total_duration += sum(insp.get('duration_minutes', 0) for insp in result['inspections'])
    result['total_duration_minutes'] = total_duration
    result['total_duration_hours'] = round(total_duration / 60, 1)
    result['work_log_count'] = len(result['work_logs'])
    result['inspection_count'] = len(result['inspections'])
    conn.close()
    return jsonify(result)


@app.route('/api/stats/equipment-history', methods=['GET'])
@login_required
@require_permission('equipment')
def get_equipment_history():
    """查询某设备的所有维护历史"""
    equipment_id = request.args.get('equipment_id')
    if not equipment_id:
        return jsonify({'error': '请提供设备ID'}), 400
    conn = get_db()
    result = {'equipment_id': equipment_id, 'inspections': [], 'work_logs': []}
    rows = conn.execute('''
        SELECT di.*, u.real_name as engineer_name
        FROM daily_inspection di
        LEFT JOIN user u ON di.engineer_id = u.id
        WHERE di.equipment_id = ?
        ORDER BY di.inspection_date DESC
    ''', (equipment_id,)).fetchall()
    for r in rows:
        d = dict(r)
        d['items'] = json.loads(r['items_json']) if r['items_json'] else []
        result['inspections'].append(d)
    rows = conn.execute('''
        SELECT wl.*, u.real_name as user_name
        FROM work_log wl
        LEFT JOIN user u ON wl.user_id = u.id
        WHERE wl.equipment_ids LIKE ?
        ORDER BY wl.log_date DESC
    ''', (f'%{equipment_id}%',)).fetchall()
    result['work_logs'] = [dict(r) for r in rows]
    conn.close()
    return jsonify(result)


@app.after_request
def add_security_headers(response):
    """添加安全响应头"""
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    # 内容安全策略（逐步收紧）
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
        "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
        "font-src 'self' https://cdn.jsdelivr.net; "
        "img-src 'self' data:"
    )
    return response


if __name__ == '__main__':
    # 生产环境务必使用 Gunicorn 部署，不要直接运行此开发服务器
    # debug=False 防止信息泄露和代码执行
    app.run(host='127.0.0.1', port=5003, debug=False)
