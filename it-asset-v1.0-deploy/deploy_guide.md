# IT运维管理系统 - Linux生产环境部署指南

## 目录
- [1. 部署前准备](#1-部署前准备)
- [2. 快速部署（推荐）](#2-快速部署推荐)
- [3. 手动部署](#3-手动部署)
- [4. 部署后配置](#4-部署后配置)
- [5. 常见问题排查](#5-常见问题排查)
- [6. 性能优化](#6-性能优化)
- [7. 安全加固](#7-安全加固)
- [8. 备份与恢复](#8-备份与恢复)
- [9. 升级指南](#9-升级指南)

---

## 1. 部署前准备

### 1.1 服务器要求

| 项目 | 最低配置 | 推荐配置 |
|------|----------|----------|
| CPU | 2核 | 4核 |
| 内存 | 4GB | 8GB |
| 硬盘 | 40GB | 100GB SSD |
| 操作系统 | Ubuntu 20.04+ / CentOS 7+ | Ubuntu 22.04 LTS |
| 网络 | 固定IP，可访问互联网 | 固定IP，可访问互联网 |

### 1.2 所需软件

- Python 3.8+
- Nginx 1.18+
- Git
- SQLite 3（系统自带）

### 1.3 防火墙端口

确保以下端口已开放：
- **22/tcp** - SSH管理
- **80/tcp** - HTTP访问
- **443/tcp** - HTTPS访问（可选）

### 1.4 域名（可选）

如果需要通过域名访问，请提前准备：
- 注册域名（如 `ops.yourhospital.com`）
- 配置DNS解析指向服务器IP

---

## 2. 快速部署（推荐）

### 2.1 下载部署脚本

```bash
# 方法1：从GitHub下载
wget https://raw.githubusercontent.com/Masonhao/IT-ops/main/deploy.sh

# 方法2：如果服务器已安装Git
git clone https://github.com/Masonhao/IT-ops.git
cd IT-ops
```

### 2.2 执行一键部署

```bash
# 添加执行权限
chmod +x deploy.sh

# 执行部署（需要root权限）
sudo ./deploy.sh
```

### 2.3 部署过程说明

脚本将自动完成以下步骤：
1. ✅ 检测操作系统
2. ✅ 安装依赖软件包（Python3、Nginx、Git等）
3. ✅ 创建应用用户 `itops`
4. ✅ 从GitHub克隆代码到 `/opt/it-ops`
5. ✅ 创建Python虚拟环境并安装依赖
6. ✅ 生成 `.env` 配置文件
7. ✅ 初始化SQLite数据库
8. ✅ 配置Nginx反向代理
9. ✅ 创建Systemd服务
10. ✅ 配置防火墙和Fail2ban

### 2.4 部署后操作

部署完成后，**必须**执行以下操作：

```bash
# 1. 编辑环境变量文件
sudo nano /opt/it-ops/it-asset-v1.0-deploy/.env

# 2. 修改以下配置：
#    - SECRET_KEY: 设置为随机字符串（运行 `openssl rand -hex 32` 生成）
#    - ADMIN_PASSWORD: 设置管理员密码
#    - FLASK_ENV: 保持为 production

# 3. 保存并退出（Ctrl+X，Y，Enter）

# 4. 重启服务使配置生效
sudo systemctl restart it-ops

# 5. 检查服务状态
sudo systemctl status it-ops
```

### 2.5 访问系统

在浏览器中访问：
- `http://服务器IP`
- `http://域名`（如果已配置）

**默认登录账号**：
- 用户名：`admin`
- 密码：`ChangeMe123!`（部署脚本中设置的实际密码）

⚠️ **重要**：首次登录后请立即修改管理员密码！

---

## 3. 手动部署

如果不使用一键脚本，可以按以下步骤手动部署。

### 3.1 安装依赖（Ubuntu/Debian）

```bash
# 更新软件包
sudo apt-get update
sudo apt-get upgrade -y

# 安装依赖
sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    nginx \
    git \
    curl \
    wget \
    ufw \
    fail2ban
```

### 3.2 安装依赖（CentOS/RHEL）

```bash
# 安装EPEL仓库
sudo yum install -y epel-release

# 安装依赖
sudo yum install -y \
    python3 \
    python3-pip \
    nginx \
    git \
    curl \
    wget \
    firewalld \
    fail2ban
```

### 3.3 创建应用用户

```bash
# 创建用户
sudo useradd -r -s /bin/bash -m itops

# 验证
id itops
```

### 3.4 部署代码

```bash
# 克隆代码
sudo git clone https://github.com/Masonhao/IT-ops.git /opt/it-ops

# 设置权限
sudo chown -R itops:itops /opt/it-ops
sudo chmod -R 755 /opt/it-ops
```

### 3.5 配置Python环境

```bash
# 切换到应用目录
cd /opt/it-ops/it-asset-v1.0-deploy

# 创建虚拟环境
sudo -u itops python3 -m venv venv

# 安装依赖
sudo -u itops bash -c "source venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt"
```

### 3.6 配置环境变量

```bash
# 复制示例文件
sudo -u itops cp .env.example .env

# 编辑配置文件
sudo nano .env

# 修改以下关键配置：
# SECRET_KEY=your-random-secret-key
# ADMIN_PASSWORD=YourSecurePassword123!
# FLASK_ENV=production
```

**生成SECRET_KEY**：
```bash
openssl rand -hex 32
```

### 3.7 初始化数据库

```bash
# 初始化数据库
sudo -u itops bash -c "source venv/bin/activate && python3 -c \"
import sys
sys.path.insert(0, '.')
from app import app, init_db
with app.app_context():
    init_db()
    print('数据库初始化完成')
\""
```

### 3.8 配置Systemd服务

```bash
# 复制服务文件
sudo cp it-ops.service /etc/systemd/system/

# 重新加载Systemd
sudo systemctl daemon-reload

# 启用并启动服务
sudo systemctl enable it-ops
sudo systemctl start it-ops

# 检查状态
sudo systemctl status it-ops
```

### 3.9 配置Nginx

```bash
# 复制Nginx配置
sudo cp nginx-it-ops.conf /etc/nginx/sites-available/it-ops

# 编辑配置（修改server_name）
sudo nano /etc/nginx/sites-available/it-ops

# 创建软链接（Ubuntu）
sudo ln -s /etc/nginx/sites-available/it-ops /etc/nginx/sites-enabled/

# 删除默认配置（Ubuntu）
sudo rm -f /etc/nginx/sites-enabled/default

# 测试Nginx配置
sudo nginx -t

# 重启Nginx
sudo systemctl restart nginx
sudo systemctl enable nginx
```

### 3.10 配置防火墙

**Ubuntu (UFW)**：
```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
```

**CentOS (Firewalld)**：
```bash
sudo systemctl start firewalld
sudo systemctl enable firewalld
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

---

## 4. 部署后配置

### 4.1 修改管理员密码

1. 访问 `http://服务器IP`
2. 使用默认账号登录（admin / 部署时设置的密码）
3. 点击右上角用户名 → "修改密码"
4. 输入新密码并保存

### 4.2 配置系统参数

登录后，进入"系统管理" → "系统设置"：
- 设置医院名称
- 配置联系方式
- 设置告警阈值
- 配置备份策略

### 4.3 导入初始数据

如果需要导入现有资产数据：
1. 准备Excel/CSV文件（参考"导入模板"）
2. 进入"资产管理" → "导入"
3. 上传文件并映射字段
4. 确认导入

### 4.4 配置SSL证书（可选）

使用Let's Encrypt免费证书：

```bash
# 安装Certbot
sudo apt-get install certbot python3-certbot-nginx  # Ubuntu
sudo yum install certbot python3-certbot-nginx      # CentOS

# 获取证书
sudo certbot --nginx -d ops.yourhospital.com

# 自动续期（已自动配置cron）
sudo certbot renew --dry-run
```

---

## 5. 常见问题排查

### 5.1 服务无法启动

**检查日志**：
```bash
# 查看Systemd日志
sudo journalctl -u it-ops -n 50 --no-pager

# 查看应用日志
sudo tail -f /opt/it-ops/it-asset-v1.0-deploy/flask.log
```

**常见问题**：
- `.env` 文件配置错误
- 端口5003已被占用
- 数据库文件权限错误

**解决方法**：
```bash
# 检查端口占用
sudo netstat -tlnp | grep 5003

# 修复数据库权限
sudo chown itops:itops /opt/it-ops/it-asset-v1.0-deploy/asset.db
sudo chmod 644 /opt/it-ops/it-asset-v1.0-deploy/asset.db
```

### 5.2 无法访问网页

**检查Nginx状态**：
```bash
sudo systemctl status nginx
sudo nginx -t
```

**检查防火墙**：
```bash
# Ubuntu
sudo ufw status

# CentOS
sudo firewall-cmd --list-all
```

**检查端口监听**：
```bash
sudo netstat -tlnp | grep -E ':(80|5003)'
```

### 5.3 数据库连接错误

**检查数据库文件**：
```bash
ls -la /opt/it-ops/it-asset-v1.0-deploy/asset.db
file /opt/it-ops/it-asset-v1.0-deploy/asset.db
```

**重新初始化数据库**：
```bash
cd /opt/it-ops/it-asset-v1.0-deploy
sudo -u itops bash -c "source venv/bin/activate && python3 -c \"
import sys
sys.path.insert(0, '.')
from app import app, init_db
with app.app_context():
    init_db()
\""
```

### 5.4 性能问题

**检查资源使用**：
```bash
# CPU和内存
top -p $(pgrep -f gunicorn)

# 磁盘空间
df -h

# 数据库连接数
sqlite3 /opt/it-ops/it-asset-v1.0-deploy/asset.db "PRAGMA journal_mode;"
```

---

## 6. 性能优化

### 6.1 Gunicorn配置优化

编辑 `/etc/systemd/system/it-ops.service`：

```ini
ExecStart=/opt/it-ops/it-asset-v1.0-deploy/venv/bin/gunicorn \
    --workers 8 \              # 2 * CPU核心数 + 1
    --threads 2 \              # 每个worker的线程数
    --bind 127.0.0.1:5003 \
    --worker-class gthread \    # 使用线程模式
    --access-logfile - \
    --error-logfile - \
    --log-level warning \
    --timeout 120 \
    --keep-alive 5 \
    --max-requests 1000 \      # 防止内存泄漏
    --max-requests-jitter 50 \
    app:app
```

重新加载配置：
```bash
sudo systemctl daemon-reload
sudo systemctl restart it-ops
```

### 6.2 Nginx缓存优化

在 `nginx-it-ops.conf` 中添加：

```nginx
# 缓存配置
proxy_cache_path /var/cache/nginx/it-ops levels=1:2 keys_zone=itops_cache:10m max_size=1g inactive=60m;

server {
    # ... 其他配置 ...

    location / {
        proxy_cache itops_cache;
        proxy_cache_valid 200 5m;
        proxy_cache_key $request_uri;
        # ... 其他配置 ...
    }
}
```

### 6.3 SQLite优化

编辑 `app.py` 或在 `.env` 中添加：

```python
# SQLite性能优化
app.config['SQLITE_PRAGMA'] = {
    'journal_mode': 'WAL',
    'cache_size': -2000,  # 2MB
    'foreign_keys': 1,
    'synchronous': 'NORMAL'
}
```

### 6.4 启用Gzip压缩

在Nginx配置中启用：

```nginx
gzip on;
gzip_vary on;
gzip_min_length 1024;
gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;
```

---

## 7. 安全加固

### 7.1 防火墙加固

**仅允许特定IP访问管理后台**（可选）：

```nginx
location /user/manage {
    allow 192.168.1.0/24;  # 内网段
    allow 10.0.0.0/8;       # VPN段
    deny all;
    # ... 代理配置 ...
}
```

### 7.2 Fail2ban配置

编辑 `/etc/fail2ban/jail.local`：

```ini
[it-ops-login]
enabled = true
filter = it-ops-login
logpath = /var/log/nginx/it-ops_access.log
maxretry = 5
bantime = 3600
findtime = 600
```

创建过滤器 `/etc/fail2ban/filter.d/it-ops-login.conf`：

```ini
[Definition]
failregex = ^<HOST> - - .*"POST /login" 401
ignoreregex =
```

### 7.3 SSL/TLS强化

在Nginx配置中：

```nginx
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384;
ssl_prefer_server_ciphers on;
ssl_session_cache shared:SSL:10m;
ssl_session_timeout 10m;
add_header Strict-Transport-Security "max-age=63072000" always;
```

### 7.4 定期安全审计

```bash
# 检查异常登录
sudo grep "POST /login" /var/log/nginx/it-ops_access.log | grep 401

# 检查文件完整性
sudo aide --check

# 扫描开放端口
sudo nmap -sT -p 1-65535 localhost
```

---

## 8. 备份与恢复

### 8.1 自动备份脚本

创建 `/opt/it-ops/backup.sh`：

```bash
#!/bin/bash
BACKUP_DIR="/opt/it-ops/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/it-ops_$DATE.tar.gz"

# 创建备份目录
mkdir -p $BACKUP_DIR

# 备份数据库和配置文件
tar -czf $BACKUP_FILE \
    /opt/it-ops/it-asset-v1.0-deploy/asset.db \
    /opt/it-ops/it-asset-v1.0-deploy/.env \
    /opt/it-ops/it-asset-v1.0-deploy/templates \
    /opt/it-ops/it-asset-v1.0-deploy/static

# 删除30天前的备份
find $BACKUP_DIR -name "it-ops_*.tar.gz" -mtime +30 -delete

echo "备份完成: $BACKUP_FILE"
```

添加到crontab：
```bash
# 每天凌晨2点备份
0 2 * * * /opt/it-ops/backup.sh >> /var/log/it-ops-backup.log 2>&1
```

### 8.2 手动备份

```bash
# 备份数据库
sudo cp /opt/it-ops/it-asset-v1.0-deploy/asset.db /backup/asset_$(date +%Y%m%d).db

# 备份整个应用
sudo tar -czf /backup/it-ops_$(date +%Y%m%d).tar.gz /opt/it-ops
```

### 8.3 恢复备份

```bash
# 停止服务
sudo systemctl stop it-ops

# 恢复数据库
sudo cp /backup/asset_20260603.db /opt/it-ops/it-asset-v1.0-deploy/asset.db
sudo chown itops:itops /opt/it-ops/it-asset-v1.0-deploy/asset.db

# 恢复应用
sudo tar -xzf /backup/it-ops_20260603.tar.gz -C /

# 启动服务
sudo systemctl start it-ops
```

---

## 9. 升级指南

### 9.1 升级前准备

```bash
# 1. 备份当前版本
sudo /opt/it-ops/backup.sh

# 2. 检查当前版本
cd /opt/it-ops
git log -1 --oneline

# 3. 查看远程更新
git fetch origin
git log HEAD..origin/main --oneline
```

### 9.2 执行升级

```bash
# 1. 进入应用目录
cd /opt/it-ops

# 2. 拉取最新代码
sudo -u itops git pull origin main

# 3. 更新依赖
sudo -u itops bash -c "cd it-asset-v1.0-deploy && source venv/bin/activate && pip install -r requirements.txt --upgrade"

# 4. 重启服务
sudo systemctl restart it-ops

# 5. 检查状态
sudo systemctl status it-ops
sudo tail -f /opt/it-ops/it-asset-v1.0-deploy/flask.log
```

### 9.3 回滚操作

如果升级后出现问题：

```bash
# 1. 查看历史版本
cd /opt/it-ops
git log --oneline -10

# 2. 回滚到指定版本
sudo -u itops git reset --hard <commit-hash>

# 3. 重启服务
sudo systemctl restart it-ops
```

---

## 附录A：常用命令速查表

| 操作 | 命令 |
|------|------|
| 启动服务 | `sudo systemctl start it-ops` |
| 停止服务 | `sudo systemctl stop it-ops` |
| 重启服务 | `sudo systemctl restart it-ops` |
| 查看状态 | `sudo systemctl status it-ops` |
| 查看日志 | `sudo journalctl -u it-ops -f` |
| 查看错误日志 | `sudo tail -f /opt/it-ops/it-asset-v1.0-deploy/flask.log` |
| 重启Nginx | `sudo systemctl restart nginx` |
| 测试Nginx配置 | `sudo nginx -t` |
| 查看端口监听 | `sudo netstat -tlnp \| grep -E ':(80\|5003)'` |
| 备份数据库 | `sudo cp /opt/it-ops/it-asset-v1.0-deploy/asset.db /backup/` |
| 升级系统 | `cd /opt/it-ops && sudo git pull && sudo systemctl restart it-ops` |

---

## 附录B：文件位置一览表

| 文件/目录 | 路径 | 说明 |
|-----------|------|------|
| 应用目录 | `/opt/it-ops` | 主应用目录 |
| 应用代码 | `/opt/it-ops/it-asset-v1.0-deploy` | Flask应用代码 |
| 配置文件 | `/opt/it-ops/it-asset-v1.0-deploy/.env` | 环境变量配置 |
| 数据库 | `/opt/it-ops/it-asset-v1.0-deploy/asset.db` | SQLite数据库 |
| 应用日志 | `/opt/it-ops/it-asset-v1.0-deploy/flask.log` | Flask应用日志 |
| Systemd服务 | `/etc/systemd/system/it-ops.service` | Systemd服务文件 |
| Nginx配置 | `/etc/nginx/sites-available/it-ops` | Nginx反向代理配置 |
| Nginx日志 | `/var/log/nginx/it-ops_*.log` | Nginx访问和错误日志 |
| 备份目录 | `/opt/it-ops/backups` | 自动备份存储位置 |

---

## 联系支持

如遇问题，请通过以下方式获取支持：

- **GitHub Issues**: https://github.com/Masonhao/IT-ops/issues
- **文档**: 查看项目根目录的 `README.md`
- **日志**: 提供相关日志文件以便快速定位问题

---

**文档版本**: v1.0
**最后更新**: 2026-06-03
**适用版本**: IT运维管理系统 v1.0+
