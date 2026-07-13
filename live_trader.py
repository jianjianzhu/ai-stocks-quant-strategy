#!/usr/bin/env python3
"""
实盘交易脚本 - MACD+EMA AI Strategy
运行在宝塔 Supervisor 下，持续监控并自动交易

支持 Python 3.9+，不依赖 pandas_ta
"""
import os
import sys
import io
import time
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import pandas as pd
import numpy as np

# ========== 配置 ==========

# 交易标的
TICKERS = ['NVDA', 'AMD', 'TSM', 'MU', 'WDC', 'MRVL', 'QCOM']

# 策略参数（来自回测优化的最佳参数）
PARAMS = {
    'fast_len': 3,
    'slow_len': 14,
    'sig_len': 27,
    'ema_short': 3,
    'ema_mid': 8,
    'ema_long': 18,
    'use_trend_filter': True,
    'use_adx_filter': True,
    'adx_period': 14,
    'atr_period': 14,
    'use_stop': True,
    'atr_stop_mult': 2.0,
    'use_trail': True,
    'trail_activation': 0.015,
    'trail_mult': 3.0,
    'pyramiding': 1,
    'position_size': 0.33,
}

# 检查间隔（秒）—— 每60秒检查一次
CHECK_INTERVAL = 60

# 美东时区
EASTERN = ZoneInfo('America/New_York')

# 数据保留天数（用于计算指标）
LOOKBACK_DAYS = 400

# 日志
LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
STATE_FILE = os.path.join(os.path.dirname(__file__), 'positions.json')


# ========== 手动实现的 TA 函数（替代 pandas_ta） ==========

def calc_atr(df, period=14):
    """计算 ATR（Average True Range）"""
    high = df['high']
    low = df['low']
    close = df['close'].shift(1)

    tr1 = high - low
    tr2 = (high - close).abs()
    tr3 = (low - close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(span=period, adjust=False).mean()
    return atr


def calc_adx(df, period=14):
    """计算 ADX（Average Directional Index）"""
    high = df['high']
    low = df['low']
    close = df['close']

    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()

    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = pd.Series(0.0, index=df.index)
    minus_dm = pd.Series(0.0, index=df.index)

    plus_mask = (up_move > down_move) & (up_move > 0)
    minus_mask = (down_move > up_move) & (down_move > 0)

    plus_dm[plus_mask] = up_move[plus_mask]
    minus_dm[minus_mask] = down_move[minus_mask]

    plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr
    atr.replace(0, np.nan, inplace=True)

    # DX -> ADX
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(span=period, adjust=False).mean()

    return adx.fillna(0)


# ========== 工具函数 ==========

def setup_logging():
    """配置日志"""
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, f'trading_{datetime.now().strftime("%Y%m%d")}.log')

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)


def load_env():
    """从 .env 加载 API 密钥"""
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())


def init_alpaca():
    """初始化 Alpaca 交易和行情客户端"""
    try:
        from alpaca.trading.client import TradingClient
        from alpaca.data.historical import StockHistoricalDataClient
    except ImportError:
        raise ImportError("请安装: pip install alpaca-py")

    # 兼容多种变量名
    api_key = (os.environ.get('APCA_API_KEY_ID')
               or os.environ.get('ALPACA_API_KEY')
               or os.environ.get('APCA_API_KEY'))
    secret_key = (os.environ.get('APCA_API_SECRET_KEY')
                  or os.environ.get('ALPACA_SECRET_KEY')
                  or os.environ.get('APCA_API_SECRET'))

    if not api_key or not secret_key:
        raise ValueError("缺少 Alpaca API 密钥！请在 .env 文件中设置")

    trading_client = TradingClient(api_key, secret_key, paper=True)
    data_client = StockHistoricalDataClient(api_key, secret_key)

    return trading_client, data_client


def load_positions():
    """加载持仓状态"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_positions(positions):
    """保存持仓状态"""
    with open(STATE_FILE, 'w') as f:
        json.dump(positions, f, indent=2)


def fetch_latest_data(data_client, symbol, days=400):
    """从 Alpaca 获取最近 N 天的日线数据"""
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    end = datetime.now()
    start = end - timedelta(days=days)

    try:
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            adjustment='all'
        )
        bars = data_client.get_stock_bars(request)

        if symbol not in bars.data or not bars.data[symbol]:
            logger.warning(f"{symbol}: 没有获取到数据")
            return None

        df = bars.data[symbol].to_frame()
        df = df[['open', 'high', 'low', 'close', 'volume']].copy()
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df = df.sort_index()

        return df
    except Exception as e:
        logger.error(f"{symbol}: 获取数据失败 - {e}")
        return None


def compute_signals(data, params):
    """计算最新交易信号 - 只取最后一行的信号"""
    df = data.copy()

    # === 指标 ===
    df['ema_short'] = df['close'].ewm(span=params['ema_short'], adjust=False).mean()
    df['ema_mid'] = df['close'].ewm(span=params['ema_mid'], adjust=False).mean()
    df['ema_long'] = df['close'].ewm(span=params['ema_long'], adjust=False).mean()

    df['macd_line'] = (
        df['close'].ewm(span=params['fast_len'], adjust=False).mean() -
        df['close'].ewm(span=params['slow_len'], adjust=False).mean()
    )
    df['sig_line'] = df['macd_line'].ewm(span=params['sig_len'], adjust=False).mean()
    df['histogram'] = df['macd_line'] - df['sig_line']
    df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()

    # 自定义 ATR 和 ADX（不依赖 pandas_ta）
    df['atr'] = calc_atr(df, params['atr_period'])
    df['adx'] = calc_adx(df, params['adx_period'])

    # === 信号（最新一行） ===
    last = df.iloc[-1]
    prev = df.iloc[-2]

    macd_golong = (last['histogram'] > 0) and (prev['histogram'] <= 0)
    macd_goshort = (last['histogram'] < 0) and (prev['histogram'] >= 0)

    cross_mid = (last['ema_short'] > last['ema_mid']) and (prev['ema_short'] <= prev['ema_mid'])
    cross_long = (last['ema_short'] > last['ema_long']) and (prev['ema_short'] <= prev['ema_long'])
    death_cross = (last['ema_short'] < last['ema_mid']) and (prev['ema_short'] >= prev['ema_mid'])

    trend_ok = (not params['use_trend_filter']) or (last['close'] > last['ema_200'])
    adx_ok = (not params['use_adx_filter']) or (last['adx'] > 20)
    all_filters_ok = trend_ok and adx_ok

    enter_l1 = macd_golong and all_filters_ok
    enter_l2 = cross_mid and all_filters_ok
    enter_l3 = cross_long and all_filters_ok
    exit_signal = macd_goshort or death_cross

    return {
        'enter_l1': enter_l1,
        'enter_l2': enter_l2,
        'enter_l3': enter_l3,
        'exit_signal': exit_signal,
        'close': last['close'],
        'atr': last['atr'] if not pd.isna(last['atr']) else 0,
        'time': df.index[-1],
        'trend_ok': trend_ok,
        'adx_ok': adx_ok,
        'macd_pos': last['histogram'] > 0,
    }


def check_and_trade(trading_client, symbol, signals, positions):
    """根据信号执行交易"""
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    pos = positions.get(symbol, {})
    current_qty = pos.get('qty', 0)

    # 获取账户信息
    account = trading_client.get_account()
    equity = float(account.equity)

    # 检查是否在交易时间（美东 9:30 ~ 16:00）
    now_et = datetime.now(EASTERN)
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    is_market_open = market_open <= now_et <= market_close and now_et.weekday() < 5

    if not is_market_open:
        return  # 盘外时间不交易

    price = signals['close']
    atr = signals['atr']

    # ========== 卖出逻辑 ==========
    if current_qty > 0:
        # 信号出场
        if signals['exit_signal']:
            try:
                order = MarketOrderRequest(
                    symbol=symbol,
                    qty=abs(current_qty),
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY
                )
                trading_client.submit_order(order)
                positions[symbol] = {}
                logger.info(f"🟢 卖出 {symbol}: {current_qty}股，信号出场")
            except Exception as e:
                logger.error(f"❌ 卖出 {symbol} 失败: {e}")
            return

        # 止损检查
        if atr > 0 and PARAMS['use_stop']:
            avg_entry = pos.get('avg_entry', price)
            stop_price = avg_entry - PARAMS['atr_stop_mult'] * atr
            if price <= stop_price:
                try:
                    order = MarketOrderRequest(
                        symbol=symbol,
                        qty=abs(current_qty),
                        side=OrderSide.SELL,
                        time_in_force=TimeInForce.DAY
                    )
                    trading_client.submit_order(order)
                    positions[symbol] = {}
                    logger.info(f"🛑 卖出 {symbol}: {current_qty}股，止损触发 (${stop_price:.2f})")
                except Exception as e:
                    logger.error(f"❌ 止损卖出 {symbol} 失败: {e}")
                return

        # 移动止盈
        if atr > 0 and PARAMS['use_trail']:
            avg_entry = pos.get('avg_entry', price)
            trail_activation = avg_entry * (1 + PARAMS['trail_activation'])
            if price >= trail_activation:
                trail_stop = price - PARAMS['trail_mult'] * atr
                old_trail = pos.get('trail_stop', 0)
                if trail_stop > old_trail:
                    pos['trail_stop'] = trail_stop
                    pos['trail_active'] = True
                    save_positions(positions)
                elif pos.get('trail_active') and price <= old_trail:
                    # 移动止盈被触发
                    try:
                        order = MarketOrderRequest(
                            symbol=symbol,
                            qty=abs(current_qty),
                            side=OrderSide.SELL,
                            time_in_force=TimeInForce.DAY
                        )
                        trading_client.submit_order(order)
                        positions[symbol] = {}
                        logger.info(f"💰 卖出 {symbol}: {current_qty}股，移动止盈触发")
                    except Exception as e:
                        logger.error(f"❌ 移动止盈卖出 {symbol} 失败: {e}")
                    return

    # ========== 买入逻辑 ==========
    elif current_qty == 0:
        can_buy = signals['enter_l1'] or signals['enter_l2'] or signals['enter_l3']
        if can_buy:
            # 计算仓位大小
            position_value = equity * PARAMS['position_size']
            qty = int(position_value / price)

            if qty < 1:
                logger.info(f"{symbol}: 资金不足以买入至少1股 (需 ${price:.2f})")
                return

            try:
                order = MarketOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY
                )
                trading_client.submit_order(order)

                # 记录持仓
                signal_type = 'L1' if signals['enter_l1'] else ('L2' if signals['enter_l2'] else 'L3')
                positions[symbol] = {
                    'qty': qty,
                    'avg_entry': price,
                    'entry_time': datetime.now().isoformat(),
                    'entry_signal': signal_type,
                    'trail_stop': 0,
                    'trail_active': False,
                }
                save_positions(positions)
                logger.info(f"🟢 买入 {symbol}: {qty}股 @ ${price:.2f}，信号: {signal_type}")
            except Exception as e:
                logger.error(f"❌ 买入 {symbol} 失败: {e}")


def get_trading_status(trading_client, positions):
    """获取当前交易状态并记录"""
    try:
        account = trading_client.get_account()
        logger.info(f"📊 账户: 权益=${float(account.equity):,.0f} 现金=${float(account.cash):,.0f}")

        # 获取 Alpaca 实际持仓
        alpaca_positions = trading_client.get_all_positions()
        for p in alpaca_positions:
            logger.info(f"  持仓: {p.symbol} {p.qty}股 盈亏={p.unrealized_pl_pct}%")

        # 检查本地持仓与 Alpaca 是否一致
        local_symbols = {s for s, v in positions.items() if v.get('qty', 0) > 0}
        alpaca_symbols = {p.symbol for p in alpaca_positions}
        if local_symbols != alpaca_symbols:
            logger.warning(f"⚠️ 本地持仓 {local_symbols} 与 Alpaca {alpaca_symbols} 不一致，已同步")
            for sym in local_symbols - alpaca_symbols:
                positions[sym] = {}
            for p in alpaca_positions:
                if p.symbol not in local_symbols:
                    positions[p.symbol] = {
                        'qty': int(p.qty),
                        'avg_entry': float(p.avg_entry_price)
                    }
            save_positions(positions)
    except Exception as e:
        logger.error(f"获取账户状态失败: {e}")


def is_trading_day():
    """判断今天是否是交易日"""
    now_et = datetime.now(EASTERN)
    if now_et.weekday() >= 5:
        return False
    return True


def main_loop():
    """主循环"""
    global logger

    load_env()
    logger = setup_logging()

    logger.info("=" * 60)
    logger.info("MACD+EMA AI Strategy - 实盘交易启动")
    logger.info("=" * 60)
    logger.info(f"交易标的: {', '.join(TICKERS)}")
    logger.info(f"策略参数: MACD({PARAMS['fast_len']},{PARAMS['slow_len']},{PARAMS['sig_len']})"
                f" EMA({PARAMS['ema_short']}/{PARAMS['ema_mid']}/{PARAMS['ema_long']})")
    logger.info(f"止损: {PARAMS['atr_stop_mult']}x ATR，移动止盈: {PARAMS['trail_activation']*100}%/{PARAMS['trail_mult']}x")
    logger.info(f"检查间隔: {CHECK_INTERVAL}秒")

    # 初始化 Alpaca
    try:
        trading_client, data_client = init_alpaca()
        account = trading_client.get_account()
        logger.info(f"✅ Alpaca Paper Trading 连接成功!")
        logger.info(f"账户: {account.status}, 权益=${float(account.equity):,.0f}")
    except Exception as e:
        logger.error(f"❌ 初始化 Alpaca 失败: {e}")
        sys.exit(1)

    # 加载持仓
    positions = load_positions()
    active_count = sum(1 for v in positions.values() if v.get('qty', 0) > 0)
    logger.info(f"本地持仓记录: {active_count} 只")

    # 主循环
    while True:
        try:
            now_et = datetime.now(EASTERN)

            # 只在交易日执行
            if not is_trading_day():
                logger.debug(f"非交易日 ({now_et.strftime('%A')})，跳过")
                time.sleep(CHECK_INTERVAL * 10)
                continue

            # 同步 Alpaca 持仓
            get_trading_status(trading_client, positions)

            # 逐只股票检查
            for symbol in TICKERS:
                try:
                    data = fetch_latest_data(data_client, symbol, LOOKBACK_DAYS)
                    if data is None or len(data) < 200:
                        logger.warning(f"{symbol}: 数据不足，跳过")
                        continue

                    signals = compute_signals(data, PARAMS)

                    logger.info(f"{symbol}: close=${signals['close']:.2f} "
                                f"trend={'✅' if signals['trend_ok'] else '❌'} "
                                f"adx={'✅' if signals['adx_ok'] else '❌'} "
                                f"macd={'POS' if signals['macd_pos'] else 'NEG'} "
                                f"L1={signals['enter_l1']} L2={signals['enter_l2']} L3={signals['enter_l3']} "
                                f"exit={signals['exit_signal']}")

                    check_and_trade(trading_client, symbol, signals, positions)

                except Exception as e:
                    logger.error(f"处理 {symbol} 时出错: {e}", exc_info=True)
                    continue

            # 保存持仓
            save_positions(positions)

            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            logger.info("收到终止信号，退出...")
            break
        except Exception as e:
            logger.error(f"主循环异常: {e}", exc_info=True)
            time.sleep(CHECK_INTERVAL * 5)


if __name__ == '__main__':
    logger = None
    main_loop()
