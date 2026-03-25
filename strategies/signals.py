"""
黄金交易信号引擎
================
基于12种策略回测结果，选择Sharpe最高的3种:
1. 布林带均值回归 (Sharpe 2.56)
2. RSI<5激进均值回归 (Sharpe 2.06)
3. 窄幅突破 (Sharpe 1.53)
"""
import numpy as np
import pandas as pd
from typing import Dict, Optional, List
from datetime import datetime


def calc_rsi(series: pd.Series, period: int = 2) -> pd.Series:
    """Wilder RSI"""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def prepare_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """计算所有技术指标"""
    df = df.copy()
    df['RSI2'] = calc_rsi(df['Close'], 2)
    df['SMA200'] = df['Close'].rolling(200).mean()
    df['SMA50'] = df['Close'].rolling(50).mean()
    df['SMA20'] = df['Close'].rolling(20).mean()
    df['SMA10'] = df['Close'].rolling(10).mean()
    df['SMA5'] = df['Close'].rolling(5).mean()

    # 布林带
    df['BB_mid'] = df['Close'].rolling(20).mean()
    df['BB_std'] = df['Close'].rolling(20).std()
    df['BB_lower'] = df['BB_mid'] - 2 * df['BB_std']
    df['BB_upper'] = df['BB_mid'] + 2 * df['BB_std']

    # ATR & Range
    df['ATR'] = (df['High'] - df['Low']).rolling(14).mean()
    df['Range'] = (df['High'] - df['Low']) / df['Close'] * 100
    df['Range_avg'] = df['Range'].rolling(10).mean()

    # 前N日高点
    df['High5'] = df['High'].rolling(5).max().shift(1)

    return df


def check_bollinger_signal(df: pd.DataFrame) -> Optional[Dict]:
    """
    布林带均值回归信号
    回测: Sharpe 2.56, 胜率 77.3%, 回撤 -8.2%

    入场: MA200上方 + 收盘跌破布林带下轨
    出场: 收盘回到布林带中轨
    """
    if len(df) < 201:
        return None

    latest = df.iloc[-1]
    close = float(latest['Close'])
    sma200 = float(latest['SMA200'])
    bb_lower = float(latest['BB_lower'])
    bb_mid = float(latest['BB_mid'])

    if pd.isna(sma200) or pd.isna(bb_lower):
        return None

    # 入场信号
    if close > sma200 and close < bb_lower:
        return {
            'strategy': 'bollinger',
            'signal': 'BUY',
            'reason': f"布林带买入: 价格{close:.2f} < 下轨{bb_lower:.2f}",
            'close': close,
            'bb_lower': bb_lower,
            'bb_mid': bb_mid,
        }

    return None


def check_rsi_aggressive_signal(df: pd.DataFrame) -> Optional[Dict]:
    """
    RSI<5 激进均值回归信号
    回测: Sharpe 2.06, 胜率 78.8%, 回撤 -10.6%

    入场: MA200上方 + RSI(2) < 5
    出场: 收盘上穿MA10
    """
    if len(df) < 201:
        return None

    latest = df.iloc[-1]
    close = float(latest['Close'])
    rsi2 = float(latest['RSI2'])
    sma200 = float(latest['SMA200'])

    if pd.isna(sma200) or pd.isna(rsi2):
        return None

    if close > sma200 and rsi2 < 5:
        return {
            'strategy': 'rsi_aggressive',
            'signal': 'BUY',
            'reason': f"RSI激进买入: RSI(2)={rsi2:.1f} < 5",
            'close': close,
            'rsi2': rsi2,
        }

    return None


def check_range_breakout_signal(df: pd.DataFrame) -> Optional[Dict]:
    """
    窄幅突破信号
    回测: Sharpe 1.53, 胜率 42.6%, 盈亏比 3.02, 回撤 -9.0%

    入场: MA200上方 + 今日波幅<平均60% + 收盘突破前5日高点
    出场: 收盘跌破MA10
    """
    if len(df) < 201:
        return None

    latest = df.iloc[-1]
    close = float(latest['Close'])
    sma200 = float(latest['SMA200'])
    rng = float(latest['Range'])
    rng_avg = float(latest['Range_avg'])
    high5 = float(latest['High5'])

    if pd.isna(sma200) or pd.isna(rng_avg) or pd.isna(high5):
        return None

    if close > sma200 and rng < rng_avg * 0.6 and close > high5:
        return {
            'strategy': 'range_breakout',
            'signal': 'BUY',
            'reason': f"窄幅突破: 波幅{rng:.2f}%<均值{rng_avg:.2f}%×60%, 破前高{high5:.2f}",
            'close': close,
        }

    return None


def check_exit_signal(df: pd.DataFrame, strategy: str) -> Optional[str]:
    """
    检查出场信号

    布林带: 价格 > BB中轨
    RSI/窄幅突破: 价格 > MA10 或 价格 < MA10 (跌破)
    """
    if len(df) < 20:
        return None

    latest = df.iloc[-1]
    close = float(latest['Close'])

    if strategy == 'bollinger':
        bb_mid = float(latest['BB_mid'])
        if not pd.isna(bb_mid) and close > bb_mid:
            return f"布林带出场: 价格{close:.2f} > 中轨{bb_mid:.2f}"

    elif strategy in ('rsi_aggressive', 'range_breakout'):
        sma10 = float(latest['SMA10'])
        if not pd.isna(sma10):
            if strategy == 'rsi_aggressive' and close > sma10:
                return f"RSI出场: 价格{close:.2f} > MA10 {sma10:.2f}"
            elif strategy == 'range_breakout' and close < sma10:
                return f"突破出场: 价格{close:.2f} < MA10 {sma10:.2f}"

    return None


def scan_all_signals(df: pd.DataFrame) -> List[Dict]:
    """扫描所有策略信号"""
    signals = []

    # 布林带
    sig = check_bollinger_signal(df)
    if sig:
        signals.append(sig)

    # RSI激进
    sig = check_rsi_aggressive_signal(df)
    if sig:
        signals.append(sig)

    # 窄幅突破
    sig = check_range_breakout_signal(df)
    if sig:
        signals.append(sig)

    return signals
