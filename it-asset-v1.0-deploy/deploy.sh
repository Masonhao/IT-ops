#!/bin/bash
#
# IT运维管理系统 - Linux生产环境一键部署脚本
# 支持：Ubuntu 20.04+ / CentOS 7+
# 作者：Mason
# 日期：2026-06-03
#

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 配置变量
APP_NAME="it-ops"
APP_PORT=5003
APP_USER="itops"
APP_DIR="/opt/${APP_NAME}"
REPO_URL="https://github.com/Masonhao/IT-ops.git"
NGINX_CONF="/etc/nginx/sites-available/${APP_NAME}"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"

# 打印带颜色的消息
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查是否为root用户
check_root() {
    if [ "$EUID" -ne 0 ]; then
        print_error "请使用root用户运行此脚本"
        exit 1
    fi
}

# 检测操作系统
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$NAME
        VER=$VERSION_ID
    elif type lsb_release >/dev/null 2>&1; then
        OS=$(lsb_release -si)
        VER=$(lsb_release -sr)
    else
        print_error "无法检测操作系统"
        exit 1
    fi
    
    print_info "检测到操作系统: $OS $VER"
}

# 安装依赖（Ubuntu/Debian）
install_deps_ubuntu() {
    print_info "更新软件包列表..."
    apt-get update
    
    print_info "安装依赖软件包..."
    apt-get install -y \
        python3 \
        python3-pip \
        python3-venv \
        nginx \
        supervisor \
        git \
        curl \
        wget \
        ufw \
        fail2ban
}

# 安装依赖（CentOS/RHEL）
install_deps_centos() {
    print_info "安装EPEL仓库..."
    yum install -y epel-release
    
    print_info "安装依赖软件包..."
    yum install -y \
        python3 \
        python3-pip \
        nginx \
        supervisor \
        git \
        curl \
        wget \
        firewalld \
        fail2ban
}

# 创建应用用户
create_user() {
    print_info "创建应用用户: $APP_USER"
    
    if id "$APP_USER" &>/dev/null; then
        print_warn "用户 $APP_USER 已存在"
    else
        useradd -r -s /bin/bash -m $APP_USER
        print_info "用户 $APP_USER 创建成功"
    fi
}

# 克隆/更新代码
deploy_code() {
    print_info "部署代码到 $APP_DIR"
    
    if [ -d "$APP_DIR" ]; then
        print_warn "$APP_DIR 已存在，将更新代码"
        cd $APP_DIR
        git fetch origin
        git reset --hard origin/main
        git pull origin main
    else
        print_info "从GitHub克隆代码..."
        git clone $REPO_URL $APP_DIR
    fi
    
    # 设置权限
    chown -R $APP_USER:$APP_USER $APP_DIR
    chmod -R 755 $APP_DIR
    
    print_info "代码部署完成"
}

# 创建虚拟环境并安装依赖
setup_python() {
    print_info "配置Python环境..."
    
    cd $APP_DIR/it-asset-v1.0-deploy
    
    # 创建虚拟环境
    if [ ! -d "venv" ]; then
        print_info "创建Python虚拟环境..."
        sudo -u $APP_USER python3 -m venv venv
    fi
    
    # 激活虚拟环境并安装依赖
    print_info "安装Python依赖包..."
    sudo -u $APP_USER bash -c "source venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt"
    
    print_info "Python环境配置完成"
}

# 配置环境变量
setup_env() {
    print_info "配置环境变量..."
    
    cd $APP_DIR/it-asset-v1.0-deploy
    
    if [ ! -f ".env" ]; then
        print_warn ".env文件不存在，将创建示例文件"
        cat > .env << 'EOF'
# Flask配置
SECRET_KEY=your-secret-key-here-change-this-in-production
FLASK_ENV=production

# 数据库配置
DATABASE_PATH=asset.db

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=flask.log

# 安全配置
SESSION_COOKIE_SECURE=True
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE=Lax

# 管理员初始密码（首次登录后请立即修改）
ADMIN_PASSWORD=ChangeMe123!
EOF
        
        chown $APP_USER:$APP_USER .env
        chmod 600 .env
        
        print_warn "请编辑 .env 文件并设置安全的 SECRET_KEY 和 ADMIN_PASSWORD"
        print_warn "路径: $APP_DIR/it-asset-v1.0-deploy/.env"
    else
        print_info ".env文件已存在"
    fi
}

# 初始化数据库
init_database() {
    print_info "初始化数据库..."
    
    cd $APP_DIR/it-asset-v1.0-deploy
    
    sudo -u $APP_USER bash -c "source venv/bin/activate && python3 -c \"
import sys
sys.path.insert(0, '.')
from app import app, init_db
with app.app_context():
    init_db()
    print('数据库初始化完成')
\""
    
    print_info "数据库初始化完成"
}

# 配置Nginx
setup_nginx() {
    print_info "配置Nginx反向代理..."
    
    # 创建Nginx配置文件
    cat > $NGINX_CONF << 'EOF'
server {
    listen 80;
    server_name _;  # 修改为你的域名或IP
    
    # 安全头
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    
    # 限制请求大小
    client_max_body_size 10M;
    
    # 静态文件
    location /static {
        alias /opt/it-ops/it-asset-v1.0-deploy/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
    
    # 主应用
    location / {
        proxy_pass http://127.0.0.1:5003;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket支持（如果需要）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # 超时设置
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
    
    # 健康检查
    location /health {
        access_log off;
        return 200 "OK\n";
        add_header Content-Type text/plain;
    }
}
EOF
    
    # 启用配置（Ubuntu）
    if [ -d "/etc/nginx/sites-enabled" ]; then
        ln -sf $NGINX_CONF /etc/nginx/sites-enabled/$APP_NAME
        # 删除默认配置
        rm -f /etc/nginx/sites-enabled/default
    fi
    
    # 测试Nginx配置
    nginx -t
    
    # 重启Nginx
    systemctl restart nginx
    systemctl enable nginx
    
    print_info "Nginx配置完成"
}

# 配置Systemd服务
setup_systemd() {
    print_info "配置Systemd服务..."
    
    cat > $SERVICE_FILE << EOF
[Unit]
Description=IT Operations Management System
After=network.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR/it-asset-v1.0-deploy
Environment="PATH=$APP_DIR/it-asset-v1.0-deploy/venv/bin"
ExecStart=$APP_DIR/it-asset-v1.0-deploy/venv/bin/gunicorn -w 4 -b 127.0.0.1:5003 app:app
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
    
    # 重新加载Systemd
    systemctl daemon-reload
    
    # 启用并启动服务
    systemctl enable $APP_NAME
    systemctl start $APP_NAME
    
    print_info "Systemd服务配置完成"
}

# 配置防火墙
setup_firewall() {
    print_info "配置防火墙..."
    
    if command -v ufw &> /dev/null; then
        # Ubuntu使用UFW
        ufw allow 22/tcp    # SSH
        ufw allow 80/tcp    # HTTP
        ufw allow 443/tcp   # HTTPS
        ufw --force enable
        print_info "UFW防火墙配置完成"
    elif command -v firewall-cmd &> /dev/null; then
        # CentOS使用Firewalld
        systemctl start firewalld
        systemctl enable firewalld
        firewall-cmd --permanent --add-service=ssh
        firewall-cmd --permanent --add-service=http
        firewall-cmd --permanent --add-service=https
        firewall-cmd --reload
        print_info "Firewalld防火墙配置完成"
    else
        print_warn "未检测到防火墙管理工具，请手动配置防火墙"
    fi
}

# 配置Fail2ban
setup_fail2ban() {
    print_info "配置Fail2ban防暴力破解..."
    
    cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true

[nginx-limit-req]
enabled = true
EOF
    
    systemctl restart fail2ban
    systemctl enable fail2ban
    
    print_info "Fail2ban配置完成"
}

# 检查服务状态
check_services() {
    print_info "检查服务状态..."
    
    echo ""
    echo "=== Nginx 状态 ==="
    systemctl status nginx --no-pager || true
    
    echo ""
    echo "=== IT-Ops 服务状态 ==="
    systemctl status $APP_NAME --no-pager || true
    
    echo ""
    echo "=== 端口监听状态 ==="
    netstat -tlnp | grep -E ':(80|5003)' || true
    
    echo ""
    echo "=== 健康检查 ==="
    curl -s http://127.0.0.1/health || print_warn "健康检查失败，请检查服务日志"
}

# 打印部署信息
print_deploy_info() {
    local server_ip=$(hostname -I | awk '{print $1}')
    
    echo ""
    echo "=========================================="
    echo "  IT运维管理系统部署完成"
    echo "=========================================="
    echo ""
    echo "访问地址:"
    echo "  http://${server_ip}"
    echo "  http://$(curl -s ifconfig.me 2>/dev/null || echo '你的公网IP')"
    echo ""
    echo "默认管理员账号:"
    echo "  用户名: admin"
    echo "  密码: ChangeMe123! (请立即修改)"
    echo ""
    echo "重要文件位置:"
    echo "  应用目录: $APP_DIR"
    echo "  配置文件: $APP_DIR/it-asset-v1.0-deploy/.env"
    echo "  Nginx配置: $NGINX_CONF"
    echo "  Systemd服务: $SERVICE_FILE"
    echo "  日志目录: $APP_DIR/it-asset-v1.0-deploy/flask.log"
    echo ""
    echo "常用命令:"
    echo "  启动服务: systemctl start $APP_NAME"
    echo "  停止服务: systemctl stop $APP_NAME"
    echo "  重启服务: systemctl restart $APP_NAME"
    echo "  查看日志: journalctl -u $APP_NAME -f"
    echo "  检查状态: systemctl status $APP_NAME"
    echo ""
    echo "=========================================="
    echo "  请立即执行以下操作:"
    echo "  1. 编辑 $APP_DIR/it-asset-v1.0-deploy/.env"
    echo "  2. 修改 SECRET_KEY 和 ADMIN_PASSWORD"
    echo "  3. 重启服务: systemctl restart $APP_NAME"
    echo "=========================================="
    echo ""
}

# 主函数
main() {
    print_info "开始部署 IT运维管理系统..."
    echo ""
    
    # 检查root权限
    check_root
    
    # 检测操作系统
    detect_os
    
    # 安装依赖
    if [[ "$OS" == *"Ubuntu"* ]] || [[ "$OS" == *"Debian"* ]]; then
        install_deps_ubuntu
    elif [[ "$OS" == *"CentOS"* ]] || [[ "$OS" == *"Red Hat"* ]]; then
        install_deps_centos
    else
        print_error "不支持的操作系统: $OS"
        exit 1
    fi
    
    # 创建用户
    create_user
    
    # 部署代码
    deploy_code
    
    # 配置Python环境
    setup_python
    
    # 配置环境变量
    setup_env
    
    # 初始化数据库
    init_database
    
    # 配置Nginx
    setup_nginx
    
    # 配置Systemd服务
    setup_systemd
    
    # 配置防火墙
    setup_firewall
    
    # 配置Fail2ban
    setup_fail2ban
    
    # 检查服务状态
    check_services
    
    # 打印部署信息
    print_deploy_info
}

# 执行主函数
main "$@"
