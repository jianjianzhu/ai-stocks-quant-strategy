#!/bin/bash
# ============================================================
# Oracle Cloud 量化交易环境 — 一键安装脚本
# 适用: Ubuntu 22.04 LTS (Oracle Cloud Free Tier)
# 用法: chmod +x install.sh && ./install.sh
# ============================================================
set -e

echo "============================================"
echo "  MACD+EMA AI Stocks — 环境安装"
echo "============================================"

# 1. 系统更新 + 基础工具
echo "[1/6] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3.11 python3.11-venv python3-pip git cron curl > /dev/null

# 2. Python 虚拟环境
echo "[2/6] Setting up Python virtual environment..."
python3.11 -m venv ~/quant_env
source ~/quant_env/bin/activate

# 3. 安装 Python 依赖
echo "[3/6] Installing Python packages..."
pip install --quiet --upgrade pip
pip install --quiet \
    pandas==3.0.3 \
    pandas-ta==0.4.71b0 \
    numpy==2.2.6 \
    alpaca-trade-api==3.2.0 \
    requests==2.32.3

# 4. 创建项目目录
echo "[4/6] Creating project directory..."
mkdir -p ~/macd-ema-ai

# 5. 设置别名（可选）
echo "[5/6] Setting up shell aliases..."
echo "alias python=~/quant_env/bin/python3.11" >> ~/.bashrc
echo "alias pip=~/quant_env/bin/pip" >> ~/.bashrc

# 6. 检查 openssl + cron 状态
echo "[6/6] Checking services..."
sudo systemctl enable cron 2>/dev/null || true
sudo systemctl start cron 2>/dev/null || true

echo ""
echo "============================================"
echo "  安装完成!"
echo "============================================"
echo ""
echo "下一步:"
echo "  1. 上传策略文件到 ~/macd-ema-ai/:"
echo "     scp -i your-key.pem *.py .env run_strategy.sh \\"
echo "         ubuntu@<YOUR_IP>:~/macd-ema-ai/"
echo ""
echo "  2. 配置 Telegram 通知（可选）:"
echo "     echo 'export TELEGRAM_BOT_TOKEN=xxx'  >> ~/macd-ema-ai/.env"
echo "     echo 'export TELEGRAM_CHAT_ID=123'    >> ~/macd-ema-ai/.env"
echo ""
echo "  3. 设置定时任务:"
echo "     crontab -e"
echo "     # 美东 9:25 AM + 4:30 PM (夏令时 UTC-4):"
echo "     # 25 13 * * 1-5 cd ~/macd-ema-ai && ./run_strategy.sh"
echo "     # 30 20 * * 1-5 cd ~/macd-ema-ai && ./run_strategy.sh"
echo ""
echo "  4. 手动测试运行:"
echo "     cd ~/macd-ema-ai && ~/quant_env/bin/python3.11 runner.py"
echo ""
echo "============================================"
