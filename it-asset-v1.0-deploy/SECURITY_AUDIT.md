# 安全审计报告：企业运维管理系统

**审计日期**: 2026-06-03
**审计范围**: `/it-asset-v1.0-deploy/` 全部代码、模板、配置文件
**审计框架**: OWASP Top 10 (2021)

---

## 概要

| 等级 | 数量 | 说明 |
|------|------|------|
| 🔴 严重 (Critical) | 3 | 可导致服务器被完全控制或身份伪造 |
| 🟠 高危 (High) | 4 | 可导致越权操作或敏感信息泄露 |
| 🟡 中危 (Medium) | 7 | 纵深防御不足，配合其他漏洞可被利用 |
| 🟢 低危 (Low) | 4 | 信息泄露或最佳实践缺失 |

---

## 🔴 严重问题

### C-1: Flask DEBUG 模式在生产环境开启

**文件**: `app.py` 第 2190 行 | **OWASP**: A05:2021 安全配置错误

```python
app.run(host='0.0.0.0', port=5003, debug=True)
```

**风险**: `debug=True` 暴露 Werkzeug 交互式调试器，攻击者在报错页面可执行任意 Python 代码，获取服务器完全控制权。`flask.log` 中已记录调试器 PIN: `346-709-442`。

**修复**:
```python
app.run(host='127.0.0.1', port=5003, debug=False)
```

---

### C-2: Flask secret_key 硬编码

**文件**: `app.py` 第 13 行 | **OWASP**: A02:2021 加密失败

```python
app.secret_key = 'ops-management-secret-key-2024'
```

**风险**: 密钥已提交 Git 仓库，任何人看到代码都能伪造 Flask session cookie，从而伪造任意用户身份（包括管理员）。

**修复**:
```python
import os
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))
```

---

### C-3: 密码哈希使用无盐 SHA256

**文件**: `models.py` 第 21-23 行 | **OWASP**: A02:2021 加密失败

```python
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()
```

**风险**: 无盐 SHA256 极易受彩虹表攻击。截获数据库文件后，所有弱密码（如 `admin`）可瞬间破解。

**修复**:
```python
from werkzeug.security import generate_password_hash, check_password_hash

def hash_password(password):
    return generate_password_hash(password, method='scrypt')

def verify_password(password, password_hash):
    return check_password_hash(password_hash, password)
```

---

## 🟠 高危问题

### H-1: 报表 PUT/DELETE 路由缺少权限检查

**文件**: `app.py` 第 2069、2094 行 | **OWASP**: A01:2021 访问控制失效

```python
@app.route('/api/reports/<int:rid>', methods=['PUT'])
@login_required          # ← 仅此，无权限检查
def update_report(rid):
    ...

@app.route('/api/reports/<int:rid>', methods=['DELETE'])
@login_required          # ← 仅此，无权限检查
def delete_report(rid):
    ...
```

**对比**: 同组 GET/POST 路由都有 `check_permission('report')` 手动调用，但 PUT/DELETE 遗漏了。

**风险**: 任意登录用户可修改、删除任意人的日报/周报/月报。

**修复**: 添加权限检查：
```python
@app.route('/api/reports/<int:rid>', methods=['PUT'])
@login_required
def update_report(rid):
    if not check_permission('report'):
        return jsonify({'error': '权限不足'}), 403
    ...
```

---

### H-2: 错误信息泄露后端细节

**文件**: `app.py` 多处 | **OWASP**: A05:2021 安全配置错误

| 行号 | 函数 | 返回内容 |
|------|------|----------|
| 467 | `create_asset` | `str(e)` |
| 1108 | `create_domain` | `str(e)` |
| 1229 | `create_equipment` | `str(e)` |
| 1307 | `create_inspection_template` | `str(e)` |
| 1448 | `create_inspection_task` | `str(e)` |
| 1763 | `create_inspection` | `str(e)` |
| 1869 | `create_worklog` | `str(e)` |
| 2020 | `create_report` | `str(e)` |

**风险**: SQLite 异常信息可能泄露数据库路径、表结构、约束条件。

**修复**: 将 `str(e)` 替换为通用错误消息，异常详情仅记录到日志：
```python
except Exception as e:
    import logging
    logging.error(f"create_asset error: {e}", exc_info=True)
    return jsonify({'error': '操作失败，请稍后重试'}), 500
```

---

### H-3: 无登录暴力破解保护

**文件**: `app.py` `/login` 路由 | **OWASP**: A07:2021 身份认证失败

无请求频率限制、无验证码、无账户锁定机制。

**修复**: 使用 Flask-Limiter 或自定义限流：
```python
from flask_limiter import Limiter
limiter = Limiter(app, key_func=lambda: request.remote_addr)

@app.route('/login', methods=['POST'])
@limiter.limit("5 per minute")  # 每分钟最多 5 次
def login():
    ...
```

---

### H-4: 敏感信息暴露

| 位置 | 暴露内容 |
|------|----------|
| `README.md` 第 51 行 | 明文管理员账号 `admin / admin` |
| `login.html` 第 45 行 | 登录页提示默认账号密码 |
| `models.py` 第 44 行 | 硬编码管理员密码 `admin` |
| `flask.log` | Werkzeug 调试器 PIN 码 `346-709-442` |

**修复**: 移除 README 和登录页中的默认凭证信息，在生产环境中首次启动时强制修改密码。

---

## 🟡 中危问题

### M-1: 缺少 CSRF 保护

未启用 CSRF token，无 SameSite cookie 设置。虽然大部分 API 使用 JSON 请求体，但仍建议添加。

**修复**: 使用 Flask-WTF 的 CSRF 保护或手动添加 CSRF token。

### M-2: Session 配置不完善

缺少以下配置：
- `SESSION_COOKIE_SECURE = True`（HTTPS only）
- `SESSION_COOKIE_SAMESITE = 'Lax'`
- `PERMANENT_SESSION_LIFETIME`（无过期时间）
- 修改密码后旧 session 不清除

### M-3: 默认密码过于简单

- 管理员: `admin`
- 新用户: `123456`

两者均为弱密码字典 Top 10。建议首次登录强制修改。

### M-4: 前端 JS 使用 .html() 插入数据库值

| 文件 | 行号 | 数据来源 |
|------|------|----------|
| `domain.html` | 339 | `d.domain_name` |
| `alert.html` | 136 | `a.message` |
| `inspection.html` | 278 | `t.item_name`, `t.item_desc` |
| `inspection_task.html` | 244 | `u.real_name`, `e.equip_no` |

如果管理员在 name/remark 等字段中存储了 `<script>` 标签，会在其他用户浏览器中执行。建议使用 `$(el).text()` 替代 `.html()`，或对数据做 HTML 转义。

### M-5: 无 HTTPS 支持

应用仅在 HTTP 端口 5003 监听，密码和 session cookie 明文传输。

**修复**: 部署时使用 Nginx 反向代理 + Let's Encrypt 证书。

### M-6: SQLite 数据库文件可被直接访问

`asset.db` 在项目目录中。如果 Nginx 未阻止 `.db` 文件访问，攻击者可直接下载数据库。

**修复**: Nginx 配置中添加：
```nginx
location ~* \.(db|sqlite|sqlite3)$ { deny all; }
```
或将数据库文件放在 Web 根目录之外。

### M-7: GET 请求有数据库写入副作用

**文件**: `app.py` 第 1051 行

```python
@app.route('/api/domains', methods=['GET'])
def get_domains():
    conn.execute("UPDATE domain SET status='urgent' WHERE ...")
```

**风险**: 浏览器预加载、搜索引擎爬虫触发意外数据修改。应改为定时任务或 POST 请求。

---

## 🟢 低危问题

### L-1: 依赖版本锁定不完整

`requirements.txt` 仅锁定 `flask==3.0.0`，未锁定 Werkzeug、Jinja2 等传递依赖。

### L-2: 无 Content Security Policy (CSP) 头

未设置 CSP header 来防御 XSS 和数据注入。

### L-3: 部分统计 API 无权限检查

`/api/stats/engineer-work`、`/api/stats/equipment-history`、`/api/categories` 仅需登录即可访问，可能泄露人员工作数据和资产信息。

### L-4: 管理员修改密码无旧密码确认

修改用户密码时不需验证当前密码，管理员 session 被劫持后可直接改密码提权。

---

## ✅ 安全亮点

以下方面做得不错：

1. **所有 SQL 查询均使用参数化查询**（`?` 占位符），无 SQL 注入风险
2. **无 `eval()` / `exec()` / `os.system()` 等危险函数调用**
3. **Jinja2 模板自动转义** — 未使用 `| safe` 过滤器
4. **无文件上传功能** — 减少了文件上传漏洞风险
5. **完整的 RBAC 权限体系** — 大部分路由都有合理的权限检查装饰器

---

## 修复优先级

| 优先级 | 问题 | 预计工作量 | 修复方式 |
|--------|------|:---:|------|
| 🔴 P0 | debug=True | 1 分钟 | `debug=False` |
| 🔴 P0 | secret_key 硬编码 | 5 分钟 | 环境变量 + random key |
| 🔴 P0 | 密码 SHA256 无盐 | 30 分钟 | 迁移到 werkzeug.security |
| 🟠 P1 | 报表 PUT/DELETE 无权限 | 2 分钟 | 加 `check_permission` |
| 🟠 P1 | 错误信息泄露 | 15 分钟 | 替换 `str(e)` → 通用消息 |
| 🟠 P1 | 无登录频率限制 | 20 分钟 | Flask-Limiter |
| 🟠 P1 | README 默认密码 | 1 分钟 | 删除敏感行 |
| 🟡 P2 | CSRF 保护 | 1 小时 | Flask-WTF |
| 🟡 P2 | Session 安全配置 | 10 分钟 | 加配置项 |
| 🟡 P2 | 首次登录改密码 | 30 分钟 | 新字段 + 校验逻辑 |
| 🟡 P2 | .html() → .text() | 1 小时 | 逐文件修改 |
| 🟢 P3 | HTTPS、CSP、依赖锁定 | 1 小时 | Nginx + 配置 |
