# AI Stocks Quant Trading Strategy

美股 AI 股量化交易策略 — MACD + EMA 金字塔加仓 + ATR 风控

## 📌 概述

一个专注于美股 AI 相关股票（NVDA、AMD、AVGO、MU、TSM 等）的量化交易策略，使用 **MACD(3,11,27)** 配合 **EMA(3/11/18) 三级金字塔加仓** 和 **ATR 动态止损/移动止盈**。

### 策略核心

- **买入信号**: MACD 金叉 + EMA 多头排列确认
- **加仓策略**: 金字塔式三级加仓，逐步放大止损
- **出场规则**: ATR 动态止损 + 移动止盈（追踪高点回撤）

## 🗂️ 项目结构

```
├── ai_stocks_strategy.pine          # TradingView Pine Script v5 策略
├── ai_stocks_strategy_backtest.py   # Python 本地回测（支持 Alpaca 数据源）
├── live_trader.py                   # 实盘交易脚本
├── runner.py                        # 策略运行器
├── runner_combined.py               # 组合策略运行器
├── bt_macd_ema.py                   # 回测引擎（MACD+EMA 版本）
├── bt_bb_rsi.py                     # 回测引擎（布林带+RSI 版本）
├── deploy.sh                        # 部署脚本
├── deploy_oracle.sh                 # Oracle Cloud 部署脚本
├── run_strategy.sh                  # 策略启动脚本
├── notifier.py                      # 微信通知推送
├── push_wechat.py                   # 微信消息接口
├── install.sh                       # 环境安装脚本
├── requirements.txt                 # Python 依赖
├── .env.example                     # 环境变量模板
├── reports/                         # 回测报告存放目录
└── *.png                            # 策略回测曲线图
```

## 🚀 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/jianjianzhu/ai-stocks-quant-strategy.git
cd ai-stocks-quant-strategy
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 API 密钥

复制 `.env.example` 为 `.env`，填入你的 Alpaca API 密钥：

```
APCA_API_KEY_ID=your_paper_key
APCA_API_SECRET_KEY=your_paper_secret
APCA_BASE_URL=https://paper-api.alpaca.markets
```

### 4. 运行回测

```bash
# MACD+EMA 策略回测
python ai_stocks_strategy_backtest.py

# 布林带+RSI 策略回测
python bt_bb_rsi.py

# 组合策略运行
python runner_combined.py
```

### 5. 实盘运行

```bash
# 运行实盘交易
python live_trader.py
```

## 📊 策略参数

### MACD(3,11,27)
- **快线周期**: 3（敏锐捕捉短期动量）
- **慢线周期**: 11
- **信号周期**: 27（过滤假信号）

### EMA 三级加仓
| 级别 | EMA 周期 | 仓位比例 |
|------|---------|---------|
| 初始 | EMA 3   | 40%     |
| 加仓 | EMA 11  | 30%     |
| 加仓 | EMA 18  | 30%     |

### ATR 风控
- **初始止损**: 2.5 × ATR
- **移动止盈**: 追踪最高点回撤 3 × ATR

## 🖥️ 部署到云服务器

支持一键部署到 Oracle Cloud / AWS EC2：

```bash
# Oracle Cloud 部署
bash deploy_oracle.sh

# 通用部署
bash deploy.sh
```

## 📝 技术栈

- **策略语言**: TradingView Pine Script v5
- **回测引擎**: Python (pandas, numpy, backtrader)
- **数据源**: Alpaca Markets API
- **部署环境**: Oracle Linux 9, AWS EC2
- **通知**: 微信推送

## 📄 许可

本项目采用 MIT 许可证 — 详见 [LICENSE](LICENSE) 文件。

## ⚠️ 免责声明

**量化交易存在重大亏损风险。** 本策略仅供学习和研究参考，不构成投资建议。在使用前请充分测试并根据自身情况调整参数。过往表现不代表未来收益。