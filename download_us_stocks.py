#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美股历史数据下载工具
支持: yfinance (免费)
标的: 标普500、苹果、特斯拉、镁光(Micron)
特性: 分批下载、延迟、重试、限流保护
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# ========== 配置区域 ==========
CONFIG = {
    # 保存路径 (Linux服务器路径，Windows下会自动回退到当前目录)
    "save_dir": "/home/ubuntu/historical_data/",

    # 回退路径 (当主路径不可写时使用)
    "fallback_dir": "./historical_data/",

    # 下载标的配置
    "tickers": {
        "^GSPC": {  # 标普500指数
            "name": "标普500",
            "start": "2000-01-01",
            "end": None,  # None表示下载到最新
            "interval": "1d",
        },
        "AAPL": {   # 苹果
            "name": "苹果",
            "start": "2000-01-01",
            "end": None,
            "interval": "1d",
        },
        "TSLA": {   # 特斯拉
            "name": "特斯拉",
            "start": "2010-06-29",  # 特斯拉IPO日期
            "end": None,
            "interval": "1d",
        },
        "MU": {     # 镁光/Micron
            "name": "镁光",
            "start": "2000-01-01",
            "end": None,
            "interval": "1d",
        },
    },

    # 下载控制参数
    "delay_seconds": 2.0,          # 每只股票下载间隔(秒)
    "max_retries": 3,              # 最大重试次数
    "retry_delay": 5.0,            # 重试间隔(秒)
    "auto_adjust": True,           # 自动复权

    # 日志配置
    "log_level": "INFO",
}

# ========== 日志设置 ==========
def setup_logging():
    log_format = "%(asctime)s [%(levelname)s] %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    logging.basicConfig(
        level=getattr(logging, CONFIG["log_level"]),
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ========== 路径处理 ==========
def resolve_save_dir():
    """解析并确定数据保存目录"""
    primary = CONFIG["save_dir"]
    fallback = CONFIG["fallback_dir"]

    # 尝试主路径
    try:
        path = Path(primary)
        path.mkdir(parents=True, exist_ok=True)
        # 测试写入权限
        test_file = path / ".write_test"
        test_file.write_text("test")
        test_file.unlink()
        logger.info(f"[OK] 使用主保存路径: {path.absolute()}")
        return str(path.absolute())
    except Exception as e:
        logger.warning(f"[WARN] 主路径不可用 ({primary}): {e}")

    # 回退路径
    try:
        path = Path(fallback)
        path.mkdir(parents=True, exist_ok=True)
        logger.info(f"[OK] 使用回退保存路径: {path.absolute()}")
        return str(path.absolute())
    except Exception as e:
        logger.error(f"[FAIL] 回退路径也不可用 ({fallback}): {e}")
        raise RuntimeError("无法确定有效的保存路径")

# ========== 数据下载核心 ==========
def download_with_yfinance(ticker, start, end, interval="1d", auto_adjust=True):
    """使用yfinance下载单只股票数据，带重试机制"""
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("请先安装 yfinance: pip install yfinance")

    # 如果没有指定end，使用昨天（避免未来数据问题）
    if end is None:
        end = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    logger.info(f"  参数: start={start}, end={end}, interval={interval}")

    # yfinance下载
    df = yf.download(
        tickers=ticker,
        start=start,
        end=end,
        interval=interval,
        auto_adjust=auto_adjust,      # 自动复权
        progress=False,               # 关闭进度条，保持日志整洁
        threads=False,                # 单线程，更稳定
    )

    if df.empty:
        raise ValueError(f"返回空数据，请检查股票代码和日期范围")

    # 处理多级列名 (yfinance返回的MultiIndex)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # 标准化列名
    df = df.rename(columns={
        'Open': 'open',
        'High': 'high',
        'Low': 'low',
        'Close': 'close',
        'Adj Close': 'adj_close',
        'Volume': 'volume'
    })

    # 确保索引名为time
    df.index.name = 'time'

    return df

def download_with_retry(ticker, config, max_retries=3, retry_delay=5.0):
    """带重试和延迟的下载包装器"""
    start = config["start"]
    end = config.get("end")
    interval = config.get("interval", "1d")
    name = config.get("name", ticker)

    logger.info(f"[{name}/{ticker}] 开始下载...")

    for attempt in range(1, max_retries + 1):
        try:
            df = download_with_yfinance(ticker, start, end, interval)
            logger.info(f"  [OK] 下载成功: {len(df)} 条记录")
            return df

        except Exception as e:
            logger.warning(f"  [WARN] 第 {attempt}/{max_retries} 次尝试失败: {e}")
            if attempt < max_retries:
                logger.info(f"  等待 {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
            else:
                logger.error(f"  [FAIL] {ticker} 下载失败，已达最大重试次数")
                raise

    return None

# ========== 数据保存 ==========
def save_to_csv(df, save_dir, ticker, name):
    """保存数据到CSV，同时生成元数据"""
    # CSV文件
    filename = f"{ticker.replace('^', '')}_daily.csv"
    filepath = os.path.join(save_dir, filename)

    df.to_csv(filepath)
    logger.info(f"  [SAVE] CSV已保存: {filepath}")

    # 元数据文件
    meta = {
        "ticker": ticker,
        "name": name,
        "download_time": datetime.now().isoformat(),
        "records": len(df),
        "date_range": {
            "start": df.index.min().strftime("%Y-%m-%d"),
            "end": df.index.max().strftime("%Y-%m-%d"),
        },
        "columns": list(df.columns),
        "file": filename,
    }

    meta_filepath = os.path.join(save_dir, f"{ticker.replace('^', '')}_meta.json")
    with open(meta_filepath, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    logger.info(f"  [SAVE] 元数据已保存: {meta_filepath}")

    return filepath, meta

def print_summary(all_results):
    """打印下载汇总"""
    logger.info("\n" + "="*70)
    logger.info("下载汇总")
    logger.info("="*70)
    logger.info(f"{'标的':<15} {'名称':<10} {'记录数':>8} {'起始日期':<12} {'结束日期':<12} {'状态':<6}")
    logger.info("-"*70)

    total_records = 0
    success_count = 0

    for ticker, result in all_results.items():
        if result is None:
            logger.info(f"{ticker:<15} {'N/A':<10} {'0':>8} {'N/A':<12} {'N/A':<12} {'FAIL':<6}")
        else:
            meta = result["meta"]
            total_records += meta["records"]
            success_count += 1
            logger.info(
                f"{ticker:<15} {meta['name']:<10} {meta['records']:>8} "
                f"{meta['date_range']['start']:<12} {meta['date_range']['end']:<12} {'OK':<6}"
            )

    logger.info("-"*70)
    logger.info(f"成功: {success_count}/{len(all_results)} | 总记录: {total_records}")
    logger.info("="*70)

# ========== 主程序 ==========
def main():
    logger.info("="*70)
    logger.info("美股历史数据下载工具 (yfinance)")
    logger.info("="*70)

    # 确定保存路径
    save_dir = resolve_save_dir()

    # 检查yfinance
    try:
        import yfinance as yf
        logger.info(f"[OK] yfinance 版本: {yf.__version__}")
    except ImportError:
        logger.error("[FAIL] 未安装 yfinance，请先运行: pip install yfinance")
        sys.exit(1)

    # 下载每只股票
    tickers_config = CONFIG["tickers"]
    delay = CONFIG["delay_seconds"]
    max_retries = CONFIG["max_retries"]
    retry_delay = CONFIG["retry_delay"]

    results = {}
    total = len(tickers_config)

    for idx, (ticker, cfg) in enumerate(tickers_config.items(), 1):
        logger.info(f"\n[{idx}/{total}] 处理: {cfg['name']} ({ticker})")

        try:
            df = download_with_retry(ticker, cfg, max_retries, retry_delay)
            if df is not None:
                filepath, meta = save_to_csv(df, save_dir, ticker, cfg["name"])
                results[ticker] = {"df": df, "meta": meta, "path": filepath}
        except Exception as e:
            logger.error(f"[FAIL] {ticker} 最终失败: {e}")
            results[ticker] = None

        # 延迟，防止被限流 (最后一只股票不需要延迟)
        if idx < total:
            logger.info(f"等待 {delay} 秒后继续...")
            time.sleep(delay)

    # 汇总
    print_summary(results)

    # 保存下载报告
    report_path = os.path.join(save_dir, "download_report.json")
    report = {
        "download_time": datetime.now().isoformat(),
        "save_dir": save_dir,
        "config": CONFIG,
        "results": {
            k: {
                "records": v["meta"]["records"] if v else 0,
                "date_range": v["meta"]["date_range"] if v else None,
                "file": v["meta"]["file"] if v else None,
            } for k, v in results.items()
        }
    }
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f"\n[SAVE] 下载报告已保存: {report_path}")

    logger.info("\n[OK] 全部完成!")
    return results

if __name__ == "__main__":
    main()
