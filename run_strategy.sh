#!/bin/bash
# ============================================================
# MACD+EMA AI Stocks — Strategy Runner
# 用法: ./run_strategy.sh
# 先运行 runner.py 生成信号，再发送 Telegram 通知
# ============================================================
set -e

cd "$(dirname "$0")"

# 加载 .env 中的环境变量
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# 日志
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
LOG_FILE="$LOG_DIR/run_$TIMESTAMP.log"

echo "============================================" | tee -a "$LOG_FILE"
echo "  MACD+EMA AI Stocks Runner" | tee -a "$LOG_FILE"
echo "  $(date)" | tee -a "$LOG_FILE"
echo "============================================" | tee -a "$LOG_FILE"

# Step 1: 运行策略生成信号
echo "" | tee -a "$LOG_FILE"
echo "[1/2] Running strategy..." | tee -a "$LOG_FILE"
~/quant_env/bin/python3.11 runner.py 2>&1 | tee -a "$LOG_FILE"
STRATEGY_EXIT=${PIPESTATUS[0]}

if [ $STRATEGY_EXIT -ne 0 ]; then
    echo "❌ Strategy failed (exit $STRATEGY_EXIT)" | tee -a "$LOG_FILE"
    # 仍尝试发送告警
    ~/quant_env/bin/python3.11 notifier.py --message "⚠️ *Strategy Error* — check log: $LOG_FILE" 2>&1 | tee -a "$LOG_FILE"
    exit $STRATEGY_EXIT
fi

# Step 2: 发送 Telegram 通知
echo "" | tee -a "$LOG_FILE"
echo "[2/2] Sending Telegram notification..." | tee -a "$LOG_FILE"
~/quant_env/bin/python3.11 notifier.py 2>&1 | tee -a "$LOG_FILE"
NOTIFY_EXIT=$?

echo "" | tee -a "$LOG_FILE"
echo "✅ Done (strategy=$STRATEGY_EXIT, notify=$NOTIFY_EXIT)" | tee -a "$LOG_FILE"

# 保留最近 30 天日志
find "$LOG_DIR" -name "*.log" -mtime +30 -delete 2>/dev/null || true
