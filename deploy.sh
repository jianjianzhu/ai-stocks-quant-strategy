#!/bin/bash
# ============================================================
# 一键部署到 Oracle Cloud
# 在本地 Windows (Git Bash) 运行:
#   1. 先配置 .env 中的 TG_BOT_TOKEN 和 TG_CHAT_ID
#   2. 修改下方 SSH_KEY 和 SSH_USER 和 SSH_HOST
#   3. bash deploy.sh
# ============================================================
set -e

# ===== 配置区域 =====
SSH_KEY="C:\\Users\\Administrator\\Desktop\\ssh-key-2026-06-25.key"
SSH_USER="opc"
SSH_HOST="161.153.101.94"
REMOTE_DIR="/home/ubuntu/macd-ema-ai"
# ====================

FILES=(
    "runner.py"
    "notifier.py"
    "run_strategy.sh"
    ".env"
    "ai_stocks_strategy_backtest.py"
)

echo "============================================"
echo "  部署到 Oracle Cloud"
echo "  Host: $SSH_USER@$SSH_HOST"
echo "============================================"

# 检查 SSH_HOST 是否配置
if [ -z "$SSH_HOST" ]; then
    echo "❌ 请在 deploy.sh 中配置 SSH_HOST"
    exit 1
fi

# 检查私钥文件
if [ ! -f "$SSH_KEY" ]; then
    echo "❌ 未找到 SSH 私钥: $SSH_KEY"
    exit 1
fi

# 创建远程目录
echo "[1/3] Creating remote directory..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$SSH_USER@$SSH_HOST" "mkdir -p $REMOTE_DIR"

# 上传文件
echo "[2/3] Uploading files..."
for f in "${FILES[@]}"; do
    if [ -f "$f" ]; then
        echo "   uploading $f..."
        scp -i "$SSH_KEY" -o StrictHostKeyChecking=no "$f" "$SSH_USER@$SSH_HOST:$REMOTE_DIR/"
    fi
done

# 设置执行权限
echo "[3/3] Setting permissions..."
ssh -i "$SSH_KEY" "$SSH_USER@$SSH_HOST" "chmod +x $REMOTE_DIR/run_strategy.sh"

# 运行安装脚本（首次部署）
echo ""
echo "  首次部署? 远程执行安装脚本..."
echo "  ssh -i \"$SSH_KEY\" $SSH_USER@$SSH_HOST \"bash $REMOTE_DIR/install.sh\""

echo ""
echo "✅ 部署完成!"
echo ""
echo "手动测试:"
echo "  ssh -i \"$SSH_KEY\" $SSH_USER@$SSH_HOST"
echo "  cd $REMOTE_DIR && ~/quant_env/bin/python3.11 runner.py"
echo ""
echo "设置定时任务:"
echo "  ssh -i \"$SSH_KEY\" $SSH_USER@$SSH_HOST"
echo "  crontab -e"
echo "  添加:"
echo "  # 美东夏令时 9:25 AM → UTC 13:25, 4:30 PM → UTC 20:30"
echo "  25 13 * * 1-5 cd $REMOTE_DIR && ./run_strategy.sh"
echo "  30 20 * * 1-5 cd $REMOTE_DIR && ./run_strategy.sh"
