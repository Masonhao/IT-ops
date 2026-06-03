"""
企业运维管理系统 - 数据库模型
SQLite 数据库，所有模型定义
"""
import sqlite3
import os
import hashlib
from datetime import datetime, timedelta

# 尝试导入 werkzeug 安全模块，如果不可用则回退到内置方法
try:
    from werkzeug.security import generate_password_hash, check_password_hash
    WERKZEUG_AVAILABLE = True
except ImportError:
    WERKZEUG_AVAILABLE = False

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'asset.db')


def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def hash_password(password):
    """密码哈希 - 使用 werkzeug scrypt 算法，自动生成随机盐
    如果 werkzeug 不可用则回退到 SHA256（不建议，仅为降级兼容）
    """
    if WERKZEUG_AVAILABLE:
        return generate_password_hash(password, method='scrypt')
    # 降级方案：不使用
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password, password_hash):
    """验证密码
    1. 先尝试 werkzeug check_password_hash（新哈希格式）
    2. 如果失败再尝试 SHA256（兼容旧密码）
    返回 (is_valid, is_legacy) 元组
    """
    if WERKZEUG_AVAILABLE and password_hash and password_hash.startswith('scrypt:'):
        return check_password_hash(password_hash, password), False
    # 兼容旧 SHA256 哈希
    legacy_hash = hashlib.sha256(password.encode()).hexdigest()
    if password_hash == legacy_hash:
        return True, True
    return False, False


def init_db():
    """初始化数据库表结构"""
    conn = get_db()
    c = conn.cursor()

    # ========== 用户管理 ==========
    c.execute('''CREATE TABLE IF NOT EXISTS user (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        real_name TEXT,
        role TEXT DEFAULT 'engineer' CHECK(role IN ('admin','engineer')),
        permissions TEXT DEFAULT 'report_daily',
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # 插入默认管理员（密码使用新哈希算法，首次登录后应强制修改）
    default_admin_pw = hash_password('admin')
    c.execute('''INSERT OR IGNORE INTO user (id, username, password, real_name, role, permissions, is_active)
        VALUES (1, 'admin', ?, '系统管理员', 'admin', 'all', 1)''', (default_admin_pw,))

    # ========== 资产分类 ==========
    c.execute('''CREATE TABLE IF NOT EXISTS category (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        parent_id INTEGER,
        sort_order INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (parent_id) REFERENCES category(id)
    )''')

    # ========== 供应商 ==========
    c.execute('''CREATE TABLE IF NOT EXISTS supplier (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        contact_person TEXT,
        contact_phone TEXT,
        contact_email TEXT,
        address TEXT,
        remark TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # ========== 资产主表 ==========
    c.execute('''CREATE TABLE IF NOT EXISTS asset (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_no TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        category_id INTEGER NOT NULL,
        brand TEXT,
        model TEXT,
        serial_no TEXT,
        status TEXT DEFAULT 'in_stock' CHECK(status IN ('in_stock','in_use','repair','scrapped','disposed')),
        location TEXT,
        department TEXT,
        custodian TEXT,
        purchase_date DATE,
        purchase_price REAL,
        warranty_expire DATE,
        supplier_id INTEGER,
        depreciation_method TEXT DEFAULT 'straight_line',
        useful_life INTEGER DEFAULT 60,
        residual_rate REAL DEFAULT 5.0,
        current_value REAL,
        remark TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (category_id) REFERENCES category(id),
        FOREIGN KEY (supplier_id) REFERENCES supplier(id)
    )''')

    # ========== 软件授权 ==========
    c.execute('''CREATE TABLE IF NOT EXISTS software (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        version TEXT,
        license_type TEXT DEFAULT 'perpetual' CHECK(license_type IN ('perpetual','subscription','volume')),
        license_count INTEGER DEFAULT 1,
        used_count INTEGER DEFAULT 0,
        license_key TEXT,
        expire_date DATE,
        supplier_id INTEGER,
        purchase_date DATE,
        purchase_price REAL,
        remark TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (supplier_id) REFERENCES supplier(id)
    )''')

    # ========== 合同 ==========
    c.execute('''CREATE TABLE IF NOT EXISTS contract (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contract_no TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        supplier_id INTEGER,
        contract_type TEXT DEFAULT 'purchase' CHECK(contract_type IN ('purchase','maintenance','lease','service')),
        amount REAL,
        start_date DATE,
        end_date DATE,
        status TEXT DEFAULT 'active' CHECK(status IN ('active','expired','terminated')),
        attachment TEXT,
        remark TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (supplier_id) REFERENCES supplier(id)
    )''')

    # ========== 资产操作记录 ==========
    c.execute('''CREATE TABLE IF NOT EXISTS asset_record (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_id INTEGER NOT NULL,
        action TEXT NOT NULL CHECK(action IN ('purchase','stock_in','allocate','transfer','repair','return','scrap','dispose')),
        from_department TEXT,
        to_department TEXT,
        from_location TEXT,
        to_location TEXT,
        from_custodian TEXT,
        to_custodian TEXT,
        operator TEXT,
        action_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        remark TEXT,
        FOREIGN KEY (asset_id) REFERENCES asset(id)
    )''')

    # ========== 盘点任务 ==========
    c.execute('''CREATE TABLE IF NOT EXISTS inventory_task (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_no TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        status TEXT DEFAULT 'pending' CHECK(status IN ('pending','in_progress','completed')),
        created_by TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP,
        remark TEXT
    )''')

    # ========== 盘点明细 ==========
    c.execute('''CREATE TABLE IF NOT EXISTS inventory_item (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        asset_id INTEGER NOT NULL,
        expected_status TEXT,
        actual_status TEXT,
        is_matched INTEGER DEFAULT 1,
        operator TEXT,
        check_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        remark TEXT,
        FOREIGN KEY (task_id) REFERENCES inventory_task(id),
        FOREIGN KEY (asset_id) REFERENCES asset(id)
    )''')

    # ========== 域名管理 ==========
    c.execute('''CREATE TABLE IF NOT EXISTS domain (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain_name TEXT NOT NULL UNIQUE,
        registrar TEXT NOT NULL,
        start_date DATE NOT NULL,
        expire_date DATE NOT NULL,
        purchase_price REAL DEFAULT 0,
        dns_server TEXT,
        status TEXT DEFAULT 'active' CHECK(status IN ('active','expired','urgent','renewing')),
        auto_renew INTEGER DEFAULT 0,
        custodian TEXT,
        remark TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # ========== 设备台账（运维设备） ==========
    c.execute('''CREATE TABLE IF NOT EXISTS equipment (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        equip_no TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        equip_type TEXT NOT NULL CHECK(equip_type IN ('network','security','server','storage','wireless','other')),
        brand TEXT,
        model TEXT,
        serial_no TEXT,
        ip_addr TEXT,
        mgmt_ip TEXT,
        location TEXT,
        department TEXT,
        custodian_id INTEGER,
        specs TEXT,
        status TEXT DEFAULT 'normal' CHECK(status IN ('normal','warning','fault','offline','retired')),
        purchase_date DATE,
        warranty_expire DATE,
        remark TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (custodian_id) REFERENCES user(id)
    )''')

    # ========== 设备巡检检查项模板 ==========
    c.execute('''CREATE TABLE IF NOT EXISTS inspection_template (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        equip_type TEXT NOT NULL,
        item_name TEXT NOT NULL,
        item_desc TEXT,
        item_type TEXT DEFAULT 'checkbox' CHECK(item_type IN ('checkbox','number','text','select')),
        unit TEXT DEFAULT '',
        normal_range TEXT DEFAULT '',
        is_required INTEGER DEFAULT 1,
        sort_order INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # 兼容已有数据库：为旧版 inspection_template 表添加新列
    existing_cols = [row[1] for row in c.execute("PRAGMA table_info(inspection_template)").fetchall()]
    if 'item_type' not in existing_cols:
        c.execute("ALTER TABLE inspection_template ADD COLUMN item_type TEXT DEFAULT 'checkbox' CHECK(item_type IN ('checkbox','number','text','select'))")
    if 'unit' not in existing_cols:
        c.execute("ALTER TABLE inspection_template ADD COLUMN unit TEXT DEFAULT ''")
    if 'normal_range' not in existing_cols:
        c.execute("ALTER TABLE inspection_template ADD COLUMN normal_range TEXT DEFAULT ''")
    if 'is_required' not in existing_cols:
        c.execute("ALTER TABLE inspection_template ADD COLUMN is_required INTEGER DEFAULT 1")

    # ========== 巡检任务分配 ==========
    c.execute('''CREATE TABLE IF NOT EXISTS inspection_task (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_name TEXT NOT NULL,
        equipment_id INTEGER,
        equip_type TEXT,
        engineer_id INTEGER,
        frequency TEXT DEFAULT 'daily' CHECK(frequency IN ('daily','weekly','monthly')),
        next_date DATE NOT NULL,
        reminder_time TEXT DEFAULT '17:00',
        status TEXT DEFAULT 'active' CHECK(status IN ('active','paused')),
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (equipment_id) REFERENCES equipment(id),
        FOREIGN KEY (engineer_id) REFERENCES user(id),
        FOREIGN KEY (created_by) REFERENCES user(id)
    )''')

    # 兼容已有数据库：为 inspection_task 表添加 reminder_time 列；重建表以修正 status CHECK 约束
    itask_cols = [row[1] for row in c.execute("PRAGMA table_info(inspection_task)").fetchall()]
    needs_rebuild = False
    if 'reminder_time' not in itask_cols:
        needs_rebuild = True
    # 检查 CHECK 约束是否需要更新（通过尝试INSERT来判断）
    if not needs_rebuild:
        try:
            c.execute("INSERT INTO inspection_task(task_name,engineer_id,frequency,next_date,status) VALUES('_test_',1,'daily','2099-01-01','active')")
            c.execute("DELETE FROM inspection_task WHERE task_name='_test_'")
        except Exception:
            needs_rebuild = True
    if needs_rebuild:
        # 备份旧数据，重建表
        c.execute('''CREATE TABLE IF NOT EXISTS inspection_task_backup AS SELECT * FROM inspection_task''')
        c.execute('DROP TABLE inspection_task')
        c.execute('''CREATE TABLE inspection_task (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_name TEXT NOT NULL,
            equipment_id INTEGER,
            equip_type TEXT,
            engineer_id INTEGER,
            frequency TEXT DEFAULT 'daily' CHECK(frequency IN ('daily','weekly','monthly')),
            next_date DATE NOT NULL,
            reminder_time TEXT DEFAULT '17:00',
            status TEXT DEFAULT 'active' CHECK(status IN ('active','paused')),
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (equipment_id) REFERENCES equipment(id),
            FOREIGN KEY (engineer_id) REFERENCES user(id),
            FOREIGN KEY (created_by) REFERENCES user(id)
        )''')
        # 恢复数据，旧 status 映射为 active
        c.execute('''INSERT INTO inspection_task(id,task_name,equipment_id,equip_type,engineer_id,frequency,next_date,status,created_by,created_at,updated_at)
            SELECT id,task_name,equipment_id,equip_type,engineer_id,frequency,next_date,'active',created_by,created_at,updated_at
            FROM inspection_task_backup''')
        c.execute('DROP TABLE inspection_task_backup')

    # ========== 巡检任务每日执行记录 ==========
    c.execute('''CREATE TABLE IF NOT EXISTS inspection_task_record (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        plan_date DATE NOT NULL,
        engineer_id INTEGER NOT NULL,
        inspection_id INTEGER,
        status TEXT DEFAULT 'pending' CHECK(status IN ('pending','completed','overdue')),
        completed_at TIMESTAMP,
        remark TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (task_id) REFERENCES inspection_task(id),
        FOREIGN KEY (engineer_id) REFERENCES user(id),
        FOREIGN KEY (inspection_id) REFERENCES daily_inspection(id),
        UNIQUE(task_id, plan_date)
    )''')

    # ========== 每日巡检记录 ==========
    c.execute('''CREATE TABLE IF NOT EXISTS daily_inspection (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inspection_date DATE NOT NULL,
        equipment_id INTEGER NOT NULL,
        engineer_id INTEGER NOT NULL,
        items_json TEXT NOT NULL,
        status TEXT DEFAULT 'normal' CHECK(status IN ('normal','abnormal')),
        abnormal_items TEXT,
        action_taken TEXT,
        duration_minutes INTEGER DEFAULT 0,
        remark TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (equipment_id) REFERENCES equipment(id),
        FOREIGN KEY (engineer_id) REFERENCES user(id)
    )''')

    # ========== 工作日志 ==========
    c.execute('''CREATE TABLE IF NOT EXISTS work_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        log_date DATE NOT NULL,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        work_type TEXT DEFAULT 'inspection' CHECK(work_type IN ('inspection','repair','change','communication','other')),
        equipment_ids TEXT,
        inspection_ids TEXT,
        duration_minutes INTEGER DEFAULT 0,
        status TEXT DEFAULT 'draft' CHECK(status IN ('draft','submitted')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES user(id)
    )''')

    # ========== 日报/周报/月报 ==========
    c.execute('''CREATE TABLE IF NOT EXISTS report (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_type TEXT NOT NULL CHECK(report_type IN ('daily','weekly','monthly')),
        report_date DATE NOT NULL,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        summary TEXT,
        completed_tasks TEXT,
        pending_tasks TEXT,
        problems TEXT,
        equipment_ids TEXT,
        inspection_ids TEXT,
        work_log_ids TEXT,
        duration_total INTEGER DEFAULT 0,
        status TEXT DEFAULT 'draft' CHECK(status IN ('draft','submitted')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES user(id)
    )''')

    # 插入默认分类
    default_categories = [
        ('服务器', None, 1), ('网络设备', None, 2), ('存储设备', None, 3),
        ('终端设备', None, 4), ('安全设备', None, 5), ('外设配件', None, 6),
        ('软件授权', None, 7), ('虚拟资产', None, 8),
        ('交换机', 2, 1), ('路由器', 2, 2), ('防火墙', 2, 3), ('无线AP', 2, 4),
        ('台式机', 4, 1), ('笔记本', 4, 2), ('显示器', 4, 3), ('打印机', 6, 1),
    ]
    for cat in default_categories:
        try:
            c.execute('INSERT OR IGNORE INTO category (name, parent_id, sort_order) VALUES (?, ?, ?)', cat)
        except:
            pass

    # 插入默认巡检模板（详细的设备类型巡检指标）
    # 格式: (equip_type, item_name, item_desc, item_type, unit, normal_range, is_required, sort_order)
    default_templates = [
        # ========== 交换机/路由器 (network) ==========
        ('network', '电源状态', '检查设备电源指示灯是否正常', 'checkbox', '', '正常', 1, 1),
        ('network', '运行状态', '检查设备运行状态指示灯/系统状态', 'checkbox', '', '正常', 1, 2),
        ('network', 'CPU利用率', '检查CPU使用率是否过高', 'number', '%', '<80', 1, 3),
        ('network', '内存利用率', '检查内存使用率是否过高', 'number', '%', '<80', 1, 4),
        ('network', '闪存/硬盘利用率', '检查存储空间使用率', 'number', '%', '<70', 1, 5),
        ('network', '运行时间', '设备已连续运行时长', 'text', '', '', 0, 6),
        ('network', '设备温度', '检查设备内部温度', 'number', '°C', '<65', 1, 7),
        ('network', '端口状态', '检查各端口Up/Down状态', 'text', '', '正常', 1, 8),
        ('network', '光模块功率', '检查光模块Rx/Tx光功率', 'text', 'dBm', '正常范围', 0, 9),
        ('network', 'VLAN状态', '检查VLAN配置是否正常', 'checkbox', '', '正常', 1, 10),
        ('network', '生成树状态', '检查STP/RSTP/MSTP状态', 'checkbox', '', '正常', 1, 11),
        ('network', '路由表状态', '检查路由条目是否正常', 'checkbox', '', '正常', 1, 12),
        ('network', 'ARP/MAC表', '检查地址表项是否正常', 'checkbox', '', '正常', 0, 13),
        ('network', '日志告警', '检查是否有异常日志告警', 'checkbox', '', '无告警', 1, 14),
        ('network', '风扇状态', '检查风扇转速和状态', 'checkbox', '', '正常', 0, 15),

        # ========== 安全设备 (security) ==========
        ('security', '电源状态', '检查设备电源指示灯是否正常', 'checkbox', '', '正常', 1, 1),
        ('security', '运行状态', '检查设备运行状态指示灯', 'checkbox', '', '正常', 1, 2),
        ('security', 'HA状态', '检查高可用集群状态', 'checkbox', '', '正常', 1, 3),
        ('security', '吞吐量', '检查当前网络吞吐量', 'number', 'Mbps', '<额定值', 1, 4),
        ('security', '并发连接数', '当前并发会话连接数量', 'number', '个', '<额定值', 1, 5),
        ('security', '新建连接速率', '每秒新建连接数', 'number', 'CPS', '<额定值', 0, 6),
        ('security', '策略命中数', '检查安全策略命中情况', 'number', '条', '', 0, 7),
        ('security', '攻击事件数', '检测到的攻击/入侵事件', 'number', '次', '0', 1, 8),
        ('security', '病毒拦截数', '检测到的病毒/恶意软件', 'number', '次', '0', 1, 9),
        ('security', '会话数', '当前活跃会话总数', 'number', '个', '<额定值', 0, 10),
        ('security', '日志存储空间', '检查日志存储使用情况', 'number', '%', '<80', 1, 11),
        ('security', '证书有效期', '检查SSL/HTTPS证书剩余天数', 'number', '天', '>30', 0, 12),
        ('security', '固件版本', '检查固件是否为最新版本', 'text', '', '', 0, 13),

        # ========== 服务器 (server) ==========
        ('server', '电源状态', '检查服务器电源状态', 'checkbox', '', '正常', 1, 1),
        ('server', '运行状态', '检查服务器运行状态', 'checkbox', '', '正常', 1, 2),
        ('server', 'CPU利用率', '检查CPU使用率', 'number', '%', '<80', 1, 3),
        ('server', '内存利用率', '检查内存使用率', 'number', '%', '<80', 1, 4),
        ('server', '磁盘空间利用率', '检查各分区磁盘使用情况', 'number', '%', '<85', 1, 5),
        ('server', 'inode使用率', '检查inode使用情况', 'number', '%', '<80', 0, 6),
        ('server', '网络带宽利用率', '检查网卡带宽使用情况', 'number', '%', '<80', 0, 7),
        ('server', '系统负载', 'Load Average (1/5/15min)', 'text', '', '<CPU核数', 1, 8),
        ('server', '活跃进程数', '当前运行的进程总数', 'number', '个', '', 0, 9),
        ('server', '关键服务状态', '检查数据库/Web/中间件等服务', 'checkbox', '', '正常', 1, 10),
        ('server', '系统温度', '检查CPU/主板温度', 'number', '°C', '<75', 1, 11),
        ('server', '僵尸进程', '检查是否存在僵尸进程', 'number', '个', '0', 1, 12),
        ('server', '系统日志', '检查系统日志是否有异常', 'checkbox', '', '无异常', 1, 13),
        ('server', '时钟同步', '检查NTP时间同步状态', 'checkbox', '', '正常', 0, 14),
        ('server', 'RAID状态', '检查磁盘阵列状态', 'checkbox', '', '正常', 1, 15),

        # ========== 存储设备 (storage) ==========
        ('storage', '电源状态', '检查存储设备电源状态', 'checkbox', '', '正常', 1, 1),
        ('storage', '运行状态', '检查存储设备运行状态', 'checkbox', '', '正常', 1, 2),
        ('storage', '总容量利用率', '检查整体存储容量使用', 'number', '%', '<80', 1, 3),
        ('storage', 'LUN利用率', '检查各LUN卷使用情况', 'text', '%', '<80', 0, 4),
        ('storage', '读写IOPS', '检查存储读写IOPS', 'text', '', '', 1, 5),
        ('storage', '读写延迟', '检查存储读写延迟', 'text', 'ms', '<10', 1, 6),
        ('storage', 'RAID状态', '检查磁盘阵列健康状态', 'checkbox', '', '正常', 1, 7),
        ('storage', '磁盘健康状态', '检查各磁盘SMART状态', 'checkbox', '', '正常', 1, 8),
        ('storage', '缓存命中率', '检查存储缓存命中情况', 'number', '%', '>80', 0, 9),
        ('storage', '快照空间利用率', '检查快照空间使用', 'number', '%', '<70', 0, 10),
        ('storage', '复制状态', '检查数据复制/同步状态', 'checkbox', '', '正常', 0, 11),
        ('storage', '控制器状态', '检查双控制器状态', 'checkbox', '', '正常', 1, 12),

        # ========== 无线设备 (wireless) ==========
        ('wireless', 'AP电源状态', '检查AP电源状态', 'checkbox', '', '正常', 1, 1),
        ('wireless', 'AP在线状态', '检查AP是否全部在线', 'checkbox', '', '全部在线', 1, 2),
        ('wireless', '信号强度', '检查各区域信号覆盖强度', 'text', 'dBm', '>-70', 1, 3),
        ('wireless', '在线用户数', '当前接入的无线用户数量', 'number', '人', '<额定值', 1, 4),
        ('wireless', '信道利用率', '检查各信道利用率', 'number', '%', '<70', 0, 5),
        ('wireless', '干扰检测', '检查是否存在无线干扰', 'checkbox', '', '无干扰', 1, 6),
        ('wireless', '漫游成功率', '检查用户漫游切换成功率', 'number', '%', '>95', 0, 7),
        ('wireless', '认证成功率', '检查无线认证成功率', 'number', '%', '>98', 0, 8),
        ('wireless', 'DHCP地址池', '检查可用IP地址池余量', 'number', '%', '>20', 0, 9),
        ('wireless', 'AP固件版本', '检查AP固件是否最新', 'text', '', '', 0, 10),

        # ========== 其他设备 (other) ==========
        ('other', '电源状态', '检查设备电源状态', 'checkbox', '', '正常', 1, 1),
        ('other', '运行状态', '检查设备运行状态', 'checkbox', '', '正常', 1, 2),
        ('other', '温度', '检查设备温度', 'number', '°C', '<65', 0, 3),
        ('other', '日志告警', '检查是否有异常日志', 'checkbox', '', '无告警', 1, 4),
    ]
    for tpl in default_templates:
        try:
            existing = c.execute(
                'SELECT id FROM inspection_template WHERE equip_type=? AND item_name=?',
                (tpl[0], tpl[1])
            ).fetchone()
            if not existing:
                c.execute('''INSERT INTO inspection_template
                    (equip_type, item_name, item_desc, item_type, unit, normal_range, is_required, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', tpl)
        except Exception as e:
            pass

    conn.commit()
    conn.close()


def generate_asset_no(category_id):
    """生成资产编号: ZC-年月-分类ID-序号"""
    conn = get_db()
    now = datetime.now()
    prefix = f"ZC-{now.strftime('%Y%m')}-{category_id:02d}"
    row = conn.execute(
        'SELECT COUNT(*) as cnt FROM asset WHERE asset_no LIKE ?',
        (prefix + '%',)
    ).fetchone()
    seq = (row['cnt'] or 0) + 1
    conn.close()
    return f"{prefix}-{seq:04d}"


def generate_equip_no(equip_type):
    """生成设备编号: SB-年月-类型缩写-序号"""
    type_map = {'network': 'NW', 'security': 'SE', 'server': 'SV', 'storage': 'ST', 'wireless': 'WL', 'other': 'OT'}
    conn = get_db()
    now = datetime.now()
    prefix = f"SB-{now.strftime('%Y%m')}-{type_map.get(equip_type, 'OT')}"
    row = conn.execute(
        'SELECT COUNT(*) as cnt FROM equipment WHERE equip_no LIKE ?',
        (prefix + '%',)
    ).fetchone()
    seq = (row['cnt'] or 0) + 1
    conn.close()
    return f"{prefix}-{seq:04d}"


if __name__ == '__main__':
    init_db()
    print("数据库初始化完成")
