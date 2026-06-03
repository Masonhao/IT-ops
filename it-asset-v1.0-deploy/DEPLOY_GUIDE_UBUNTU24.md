# IT资产管理系统 — Ubuntu 24.04 LTS 部署指南

> **系统要求**：Ubuntu 24.04 LTS（服务器版/桌面版均可）  
> **技术栈**：Python 3 + Flask + SQLite + Nginx  
> **部署模式**：单机部署，内网访问  

---

## 目录

1. [环境准备](#1-环境准备)
2. [安装 Python 环境](#2-安装-python-环境)
3. [上传项目文件](#3-上传项目文件)
4. [配置虚拟环境](#4-配置虚拟环境)
5. [安全加固](#5-安全加固)
6. [Nginx 反向代理](#6-nginx-反向代理)
7. [systemd 服务管理](#7-systemd-服务管理)
8. [防火墙设置](#8-防火墙设置)
9. [备份与恢复](#9-备份与恢复)
10. [日常运维命令](#10-日常运维命令)
11. [常见问题排查](#11-常见问题排查)

---

## 1. 环境准备

### 1.1 硬件要求

| 项目 | 最低配置 | 推荐配置 |
|------|----------|----------|
| CPU | 1 核 | 2 核+ |
| 内存 | 512 MB | 2 GB |
| 硬盘 | 10 GB | 40 GB+ |
| 网络 | 内网可通 | 内网固定 IP |

### 1.2 系统更新

```bash
# 以 root 或 sudo 权限执行
sudo apt update && sudo apt upgrade -y
```

### 1.3 创建专用运行用户（安全建议）

不要用 root 直接运行应用：

```bash
# 创建专门运行应用的用户
sudo adduser --system --group --home /opt/it-asset --shell /usr/sbin/nologin itasset

# 说明：
#   --system    → 系统用户（无登录权限）
#   --group     → 同名组
#   --home      → 指定主目录为项目目录
#   /usr/sbin/nologin → 禁止 SSH 登录
```

---

## 2. 安装 Python 环境

Ubuntu 24.04 默认已带 Python 3.12，无需额外安装。

### 2.1 检查 Python 版本

```bash
python3 --version
# 预期输出：Python 3.12.x
```

### 2.2 安装 pip 和 venv

```bash
sudo apt install -y python3-pip python3-venv python3-dev build-essential
```

### 2.3 安装 Nginx（反向代理）

```bash
sudo apt install -y nginx
```

---

## 3. 上传项目文件

### 3.1 方法一：SCP 上传（从本地 Mac/Linux）

```bash
# 在本地电脑终端执行，将项目打包后上传
cd 你的项目目录
tar czf it-asset-deploy.tar.gz \
    app.py models.py requirements.txt README.md \
    templates/ static/

# 上传到服务器
scp it-asset-deploy.tar.gz 用户名@服务器IP:/tmp/
```

### 3.2 方法二：SFTP 工具上传

使用 FileZilla、WinSCP、MobaXterm 等 SFTP 工具连接服务器，将以下文件上传到 `/opt/it-asset/`：

```
/opt/it-asset/
├── app.py              # Flask 主应用
├── models.py           # 数据模型
├── requirements.txt    # Python 依赖
├── README.md           # 说明文档
├── templates/          # HTML 模板（11个文件）
│   ├── base.html
│   ├── index.html
│   ├── asset.html
│   ├── category.html
│   ├── software.html
│   ├── supplier.html
│   ├── contract.html
│   ├── domain.html
│   ├── inventory.html
│   ├── alert.html
│   └── report.html
└── static/
    ├── css/
    └── js/
```

### 3.3 在服务器上解压并放置文件

```bash
# 在服务器上执行
sudo mkdir -p /opt/it-asset
cd /tmp
sudo tar xzf it-asset-deploy.tar.gz -C /opt/it-asset/

# 或者手动创建目录结构
sudo chown -R root:root /opt/it-asset
chmod -R 755 /opt/it-asset
```

---

## 4. 配置虚拟环境

### 4.1 创建虚拟环境

```bash
cd /opt/it-asset
python3 -m venv venv
source venv/bin/activate
```

激活成功后，终端提示符会显示 `(venv)` 前缀。

### 4.2 安装依赖

```bash
pip install -r requirements.txt
# 或单独安装
pip install flask==3.0.0 gunicorn==21.2.0
```

> **说明**：生产环境推荐使用 Gunicorn 作为 WSGI 服务器，比 Flask 自带的开发服务器更稳定、性能更好。

### 4.3 测试启动

```bash
# 先用 Flask 开发模式测试是否正常
python app.py
```

浏览器访问 `http://服务器IP:5000`，确认页面正常显示后 `Ctrl+C` 停止。

---

## 5. 安全加固

### 5.1 关闭 Flask Debug 模式

**非常重要！** 生产环境必须关闭 debug，否则会暴露代码栈信息。

检查 `app.py` 最后几行，确认是：

```python
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)  # ✅ debug=False
```

如果当前是 `debug=True`，请修改为 `False`。本项目默认已经是 `debug=False`。

### 5.2 设置数据库文件权限

SQLite 数据库文件需要写权限，但要限制访问范围：

```bash
cd /opt/it-asset

# 数据库文件只允许应用用户读写
touch asset.db
chown itasset:itasset asset.db
chmod 640 asset.db
```

### 5.3 使用 Gunicorn 替代开发服务器

创建 Gunicorn 启动脚本 `/opt/it-asset/run.sh`：

```bash
#!/bin/bash
cd /opt/it-asset
source venv/bin/activate
exec gunicorn \
    --workers 2 \
    --bind 127.0.0.1:8000 \
    --timeout 120 \
    --user itasset \
    --group itasset \
    --access-logfile /var/log/it-asset/access.log \
    --error-logfile /var/log/it-asset/error.log \
    app:app
```

参数说明：
| 参数 | 值 | 含义 |
|------|-----|------|
| `--workers` | 2 | 工作进程数（CPU核数×2+1，最低2个） |
| `--bind` | 127.0.0.1:8000 | 仅监听本机，通过 Nginx 转发 |
| `--timeout` | 120 | 超时时间（秒） |
| `--user/group` | itasset | 以低权限用户运行 |
| `app:app` | | 入口模块:Flask实例 |

赋予执行权限：

```bash
chmod +x /opt/it-asset/run.sh

# 创建日志目录
sudo mkdir -p /var/log/it-asset
sudo chown itasset:itasset /var/log/it-asset
```

### 5.4 配置 Nginx 反向代理

创建 Nginx 配置文件 `/etc/nginx/sites-available/it-asset`：

```nginx
server {
    listen 80;
    server_name _;  # 如果有域名，替换为域名或内网IP

    # 安全头设置
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # 隐藏 Nginx 版本号
    server_tokens off;

    # 客户端请求体大小限制
    client_max_body_size 10m;

    # 静态资源缓存
    location ~* \.(css|js|png|jpg|jpeg|gif|ico|svg|woff2?|ttf|eot)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # 反向代理到 Gunicorn
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 超时设置
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 120s;
        
        # 禁用缓冲（适合流式响应）
        proxy_buffering off;
    }

    # 禁止访问隐藏文件（如 .htaccess, .git）
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }
}
```

启用站点配置：

```bash
# 启用站点
sudo ln -sf /etc/nginx/sites-available/it-asset /etc/nginx/sites-enabled/

# 删除默认站点（避免冲突）
sudo rm -f /etc/nginx/sites-enabled/default

# 测试配置语法
sudo nginx -t

# 重载 Nginx
sudo systemctl reload nginx
```

### 5.5 限制直接访问端口

Gunicorn 绑定在 `127.0.0.1:8000`（仅本机），外网无法直接访问。  
所有外部请求必须经过 Nginx（端口 80），实现安全隔离。

---

## 6. systemd 服务管理

创建 systemd 服务文件 `/etc/systemd/system/it-asset.service`：

```ini
[Unit]
Description=IT Asset Management System
Documentation=https://github.com/your-repo
After=network.target nginx.service
Wants=nginx.service

[Service]
Type=simple
User=itasset
Group=itasset
WorkingDirectory=/opt/it-asset
ExecStart=/opt/it-asset/venv/bin/gunicorn \
    --workers 2 \
    --bind 127.0.0.1:8000 \
    --timeout 120 \
    --access-logfile /var/log/it-asset/access.log \
    --error-logfile /var/log/it-asset/error.log \
    app:app

# 自动重启策略
Restart=on-failure
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=3

# 安全限制
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/it-asset /var/log/it-asset

[Install]
WantedBy=multi-user.target
```

### 注册并启动服务

```bash
# 重新加载 systemd 配置
sudo systemctl daemon-reload

# 设置开机自启
sudo systemctl enable it-asset

# 启动服务
sudo systemctl start it-asset

# 查看状态（应该显示 active running）
sudo systemctl status it-asset

# 查看 Nginx 状态
sudo systemctl status nginx
```

### 服务管理快捷命令

```bash
sudo systemctl start it-asset       # 启动
sudo systemctl stop it-asset        # 停止
sudo systemctl restart it-asset     # 重启
sudo systemctl reload it-asset      # 重新加载配置
sudo systemctl status it-asset      # 查看状态
journalctl -u it-asset -f           # 实时查看日志
```

---

## 7. 防火墙设置

### 7.1 UFW 防火墙配置

```bash
# 安装并启用 UFW
sudo apt install -y ufw

# 默认规则：拒绝入站，允许出站
sudo ufw default deny incoming
sudo ufw default allow outgoing

# 允许 SSH（⚠️ 务必先开，否则会被锁在外面！）
sudo ufw allow 22/tcp comment 'SSH'

# 允许 HTTP（IT资产管理系统）
sudo ufw allow 80/tcp comment 'HTTP-ITAsset'

# 如果需要 HTTPS（后续加证书时用到）
sudo ufw allow 443/tcp comment 'HTTPS'

# 允许内网网段访问（可选，限制来源IP更安全）
# 例如只允许 192.168.1.0/24 访问 80 端口：
# sudo ufw allow from 192.168.1.0/24 to any port 80 comment 'Intranet'

# 启用防火墙
sudo ufw enable

# 查看防火墙状态
sudo ufw status verbose
```

### 7.2 防火墙状态示例（正常输出）

```
Status: active

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW IN    Anywhere
80/tcp                     ALLOW IN    Anywhere
443/tcp                    ALLOW IN    Anywhere
22/tcp (v6)                ALLOW IN    Anywhere (v6)
80/tcp (v6)                ALLOW IN    Anywhere (v6)
443/tcp (v6)                ALLOW IN    Anywhere (v6)
```

### 7.3 更安全的方案 — 限制内网 IP 访问

如果知道内网的 IP 段，可以限制只有内网能访问：

```bash
# 删除之前的全开放规则
sudo ufw delete allow 80/tcp

# 只允许内网访问
sudo ufw allow from 192.168.0.0/16 to any port 80 comment 'Intranet-Only'
# 或更精确的网段
sudo ufw allow from 192.168.1.0/24 to any port 80 comment 'Office-Network'
```

---

## 8. 备份与恢复

### 8.1 自动备份脚本

创建备份脚本 `/opt/it-asset/backup.sh`：

```bash
#!/bin/bash
# IT资产管理系统自动备份脚本
# 建议放入 crontab 定时执行

BACKUP_DIR="/opt/backups"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

# 创建备份目录
mkdir -p "$BACKUP_DIR"

# 备份数据库文件（SQLite）
cp /opt/it-asset/asset.db "$BACKUP_DIR/asset_${DATE}.db"

# 备份整个项目代码（可选）
tar czf "$BACKUP_DIR/code_${DATE}.tar.gz" -C /opt it-asset/ --exclude='venv' --exclude='*.pyc' --exclude='__pycache__'

# 清理过期备份（保留最近30天）
find "$BACKUP_DIR" -mtime +$RETENTION_DAYS -type f -delete

echo "[$(date)] 备份完成: ${BACKUP_DIR}/"
```

```bash
chmod +x /opt/it-asset/backup.sh

# 手动测试一次
sudo /opt/it-asset/backup.sh
```

### 8.2 设置定时备份

```bash
# 编辑 crontab（以 root 身份）
sudo crontab -e

# 添加以下行（每天凌晨 2 点自动备份）
0 2 * * * /opt/it-asset/backup.sh >> /var/log/it-asset/backup.log 2>&1
```

### 8.3 恢复数据

```bash
# 停止服务
sudo systemctl stop it-asset

# 恢复数据库
cp /opt/backups/asset_20260428_020000.db /opt/it-asset/asset.db

# 修正权限
chown itasset:itasset /opt/it-asset/asset.db
chmod 640 /opt/it-asset/asset.db

# 重启服务
sudo systemctl start it-asset
```

---

## 9. 日常运维命令

### 9.1 快速参考表

| 操作 | 命令 |
|------|------|
| 查看服务状态 | `sudo systemctl status it-asset` |
| 重启服务 | `sudo systemctl restart it-asset` |
| 查看实时日志 | `journalctl -u it-asset -f` |
| 查看最近100条日志 | `journalctl -u it-asset -n 100` |
| 查看 Nginx 访问日志 | `tail -f /var/log/nginx/access.log` |
| 查看 Nginx 错误日志 | `tail -f /var/log/nginx/error.log` |
| 查看 Gunicorn 日志 | `tail -f /var/log/it-asset/access.log` |
| 检查磁盘空间 | `df -h` |
| 检查数据库大小 | `ls -lh /opt/it-asset/asset.db` |
| 检查端口占用 | `ss -tlnp \| grep :80` |

### 9.2 更新项目代码

当有新版本时：

```bash
# 1. 上传新代码覆盖旧文件
scp 新代码包 用户名@服务器IP:/tmp/

# 2. 在服务器上解压覆盖
cd /opt/it-asset
# （根据实际情况处理文件覆盖）

# 3. 重启服务生效
sudo systemctl restart it-asset
```

### 9.3 升级 Python 依赖

```bash
cd /opt/it-asset
source venv/bin/activate
pip install -r requirements.txt --upgrade
sudo systemctl restart it-asset
```

---

## 10. 完整部署流程速查（一次性执行）

如果你想在全新 Ubuntu 24.04 上快速完成全部部署，按顺序执行以下所有步骤：

```bash
# ==================== 第1步：更新系统 ====================
sudo apt update && sudo apt upgrade -y

# ==================== 第2步：安装软件包 ====================
sudo apt install -y python3 python3-pip python3-venv python3-dev \
                   build-essential nginx ufw

# ==================== 第3步：创建用户和目录 ====================
sudo adduser --system --group --home /opt/it-asset --shell /usr/sbin/nologin itasset
sudo mkdir -p /opt/it-asset /var/log/it-asset /opt/backups
sudo chown -R itasset:itasset /var/log/it-asset /opt/backups

# ==================== 第4步：上传项目文件 ====================
# 【此步需要你手动操作】将项目文件上传到 /opt/it-asset/
# 可以用 scp、FileZilla、WinSCP 等工具
#
# 上传完成后继续：

# ==================== 第5步：配置环境和依赖 ====================
cd /opt/it-asset
python3 -m venv venv
source venv/bin/activate
pip install flask==3.0.0 gunicorn==21.2.0

# ==================== 第6步：数据库权限 ====================
touch asset.db
chown itasset:itasset asset.db
chmod 640 asset.db

# ==================== 第7步：验证能启动 ====================
python3 app.py &
sleep 3
curl http://127.0.0.1:5000 | head -20
kill %1

# ==================== 第8步：配置 Nginx ====================
cat > /tmp/nginx-it-asset.conf << 'NGINX_EOF'
server {
    listen 80;
    server_name _;
    
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    server_tokens off;
    client_max_body_size 10m;
    
    location ~* \.(css|js|png|jpg|jpeg|gif|ico|svg|woff2?)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 120s;
    }
    
    location ~ /\. { deny all; }
}
NGINX_EOF

sudo cp /tmp/nginx-it-asset.conf /etc/nginx/sites-available/it-asset
sudo ln -sf /etc/nginx/sites-available/it-asset /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# ==================== 第9步：配置 systemd 服务 ====================
cat > /tmp/it-asset.service << 'SERVICE_EOF'
[Unit]
Description=IT Asset Management System
After=network.target nginx.service
Wants=nginx.service

[Service]
Type=simple
User=itasset
Group=itasset
WorkingDirectory=/opt/it-asset
ExecStart=/opt/it-asset/venv/bin/gunicorn \
    --workers 2 \
    --bind 127.0.0.1:8000 \
    --timeout 120 \
    --access-logfile /var/log/it-asset/access.log \
    --error-logfile /var/log/it-asset/error.log \
    app:app
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/it-asset /var/log/it-asset

[Install]
WantedBy=multi-user.target
SERVICE_EOF

sudo cp /tmp/it-asset.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable it-asset
sudo systemctl start it-asset

# ==================== 第10步：配置防火墙 ====================
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp comment 'SSH'
sudo ufw allow 80/tcp comment 'HTTP'
echo "y" | sudo ufw enable
sudo ufw status verbose

# ==================== 第11步：配置自动备份 ====================
cat > /opt/it-asset/backup.sh << 'BACKUP_EOF'
#!/bin/bash
BACKUP_DIR="/opt/backups"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"
cp /opt/it-asset/asset.db "$BACKUP_DIR/asset_${DATE}.db"
tar czf "$BACKUP_DIR/code_${DATE}.tar.gz" -C /opt it-asset/ --exclude='venv' --exclude='*.pyc' --exclude='__pycache__'
find "$BACKUP_DIR" -mtime +30 -type f -delete
BACKUP_EOF

sudo chmod +x /opt/it-asset/backup.sh

# 添加每天凌晨2点定时备份
(crontab -l 2>/dev/null; echo "0 2 * * * /opt/it-asset/backup.sh >> /var/log/it-asset/backup.log 2>&1") | sort -u | sudo crontab -

# ==================== 完成！====================
echo ""
echo "========================================="
echo "  🎉 IT资产管理系统部署完成！"
echo "========================================="
echo "  访问地址: http://$(hostname -I | awk '{print $1}')"
echo "  服务状态: $(systemctl is-active it-asset)"
echo "========================================="
```

---

## 11. 常见问题排查

### 问题 1：页面打不开（502 Bad Gateway）

```bash
# 检查 Gunicorn 是否在运行
sudo systemctl status it-asset

# 检查 Nginx 是否正常
sudo systemctl status nginx

# 检查端口是否被占用
ss -tlnp | grep -E ':80|:8000'
```

**常见原因**：Gunicorn 未启动 → `sudo systemctl start it-asset`

---

### 问题 2：数据保存失败

```bash
# 检查数据库文件权限
ls -la /opt/it-asset/asset.db
# 应该是：-rw-r----- 1 itasset itasset ...

# 检查磁盘空间
df -h /opt
```

**常见原因**：数据库权限不对 → `chown itasset:itasset asset.db && chmod 640 asset.db`

---

### 问题 3：端口被占用

```bash
# 查看哪个进程占用了端口
sudo lsof -i :8000
sudo lsof -i :80

# 杀掉占用进程（谨慎操作）
sudo kill -9 <PID>
```

---

### 问题 4：防火墙导致无法访问

```bash
# 检查防火墙状态
sudo ufw status

# 临时关闭防火墙测试
sudo ufw disable

# 确认是防火墙问题后再开启
sudo ufw enable
```

---

### 问题 5：升级 Python 版本后报错

```bash
# 重建虚拟环境
cd /opt/it-asset
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart it-asset
```

---

## 附录：安全检查清单

部署完成后，逐项确认：

- [ ] Flask debug=False（生产环境禁止 debug 模式）
- [ ] 使用 Gunicorn 而非 Flask 开发服务器
- [ ] 应用运行在非 root 用户下
- [ ] 数据库文件权限 640，仅允许应用用户读写
- [ ] Gunicorn 绑定 127.0.0.1（不对外暴露）
- [ ] Nginx 已配置安全响应头
- [ ] 防火墙仅开放必要端口（22、80）
- [ ] SSH 密钥登录已启用（禁用密码登录更佳）
- [ ] 系统自动更新已开启（`sudo apt install unattended-upgrades`）
- [ ] 定期备份已配置（crontab 每日备份）
- [ ] 日志轮转已配置（logrotate）
- [ ] 服务器密码已更改且强度足够

---

*文档版本：2026-04-28*  
*适用系统：Ubuntu 24.04 LTS*
