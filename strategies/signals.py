"""
黄金盘中量化交易信号引擎
========================
基于11年XAU/USD H1真实数据(Dukascopy) + 特朗普时期分段验证

策略组合:
1. Keltner通道突破 (全周期Sharpe 0.92, 特朗普2年化+51.7%)
2. MACD+SMA50趋势 (全周期Sharpe 1.14, 特朗普2年化+24.7%, 回撤仅-4.5%)

两个策略都支持做多+做空，双向捕捉趋势
"""
import numpy as np
import pandas as pd
from typing import Dict, Optional, List
from datetime import datetime


def calc_rsi(series: pd.Series, period: int = 2) -> pd.Series:
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
    
    # 均线
    df['SMA50'] = df['Close'].rolling(50).mean()
    df['SMA200'] = df['Close'].rolling(200).mean()
    df['EMA9'] = df['Close'].ewm(span=9).mean()
    df['EMA12'] = df['Close'].ewm(span=12).mean()
    df['EMA21'] = df['Close'].ewm(span=21).mean()
    df['EMA26'] = df['Close'].ewm(span=26).mean()
    
    # Keltner Channel (EMA20 ± 1.5*ATR)
    df['ATR'] = (df['High'] - df['Low']).rolling(14).mean()
    df['KC_mid'] = df['Close'].ewm(span=20).mean()
    df['KC_upper'] = df['KC_mid'] + 1.5 * df['ATR']
    df['KC_lower'] = df['KC_mid'] - 1.5 * df['ATR']
    
    # MACD
    df['MACD'] = df['EMA12'] - df['EMA26']
    df['MACD_signal'] = df['MACD'].ewm(span=9).mean()
    df['MACD_hist'] = df['MACD'] - df['MACD_signal']
    
    # RSI (用于辅助监控)
    df['RSI2'] = calc_rsi(df['Close'], 2)
    df['RSI14'] = calc_rsi(df['Close'], 14)
    
    return df


def check_keltner_signal(df: pd.DataFrame) -> Optional[Dict]:
    """
    Keltner通道突破信号
    回测: 11年Sharpe 0.92, 年均260笔, 特朗普2期年化+51.7%
    
    做多: 价格突破上轨 + 价格>SMA50
    做空: 价格跌破下轨 + 价格<SMA50
    止损$20, 止盈$35
    """
    if len(df) < 55:
        return None
    
    latest = df.iloc[-1]
    close = float(latest['Close'])
    kc_upper = float(latest['KC_upper'])
    kc_lower = float(latest['KC_lower'])
    sma50 = float(latest['SMA50'])
    
    if pd.isna(kc_upper) or pd.isna(sma50):
        return None
    
    # 做多: 突破上轨
    if close > kc_upper and close > sma50:
        return {
            'strategy': 'keltner',
            'signal': 'BUY',
            'reason': f"Keltner做多: 价格{close:.2f} > 上轨{kc_upper:.2f}",
            'close': close,
            'sl': 20,
            'tp': 35,
        }
    
    # 做空: 跌破下轨
    if close < kc_lower and close < sma50:
        return {
            'strategy': 'keltner',
            'signal': 'SELL',
            'reason': f"Keltner做空: 价格{close:.2f} < 下轨{kc_lower:.2f}",
            'close': close,
            'sl': 20,
            'tp': 35,
        }
    
    return None


def check_macd_signal(df: pd.DataFrame) -> Optional[Dict]:
    """
    MACD+SMA50趋势信号
    回测: 11年Sharpe 1.14, 年均123笔, 回撤仅-4.8%, 盈亏比2.46
    特朗普2期年化+24.7%
    
    做多: MACD柱状图由负转正 + 价格>SMA50
    做空: MACD柱状图由正转负 + 价格<SMA50
    止损$20, 止盈$50
    """
    if len(df) < 30:
        return None
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    close = float(latest['Close'])
    macd_hist = float(latest['MACD_hist'])
    macd_hist_prev = float(prev['MACD_hist'])
    sma50 = float(latest['SMA50'])
    
    if pd.isna(macd_hist) or pd.isna(macd_hist_prev) or pd.isna(sma50):
        return None
    
    # 做多: MACD柱由负转正 + 价格在SMA50上方
    if macd_hist > 0 and macd_hist_prev <= 0 and close > sma50:
        return {
            'strategy': 'macd',
            'signal': 'BUY',
            'reason': f"MACD做多: 柱状图转正, 价格{close:.2f} > SMA50",
            'close': close,
            'sl': 20,
            'tp': 50,
        }
    
    # 做空: MACD柱由正转负 + 价格在SMA50下方
    if macd_hist < 0 and macd_hist_prev >= 0 and close < sma50:
        return {
            'strategy': 'macd',
            'signal': 'SELL',
            'reason': f"MACD做空: 柱状图转负, 价格{close:.2f} < SMA50",
            'close': close,
            'sl': 20,
            'tp': 50,
        }
    
    return None


def check_exit_signal(df: pd.DataFrame, strategy: str, direction: str) -> Optional[str]:
    """
    检查出场信号
    
    Keltner: 价格回到通道内 (反向突破)
    MACD: MACD柱状图反向
    """
    if len(df) < 5:
        return None
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    close = float(latest['Close'])
    
    if strategy == 'keltner':
        kc_mid = float(latest['KC_mid'])
        if not pd.isna(kc_mid):
            if direction == 'BUY' and close < kc_mid:
                return f"Keltner多头出场: 价格{close:.2f} < 中轨{kc_mid:.2f}"
            elif direction == 'SELL' and close > kc_mid:
                return f"Keltner空头出场: 价格{close:.2f} > 中轨{kc_mid:.2f}"
    
    elif strategy == 'macd':
        macd_hist = float(latest['MACD_hist'])
        macd_hist_prev = float(prev['MACD_hist'])
        if not pd.isna(macd_hist):
            if direction == 'BUY' and macd_hist < 0 and macd_hist_prev >= 0:
                return f"MACD多头出场: 柱状图转负"
            elif direction == 'SELL' and macd_hist > 0 and macd_hist_prev <= 0:
                return f"MACD空头出场: 柱状图转正"
    
    return None


def scan_all_signals(df: pd.DataFrame) -> List[Dict]:
    """扫描所有策略信号"""
    signals = []
    
    sig = check_keltner_signal(df)
    if sig:
        signals.append(sig)
    
    sig = check_macd_signal(df)
    if sig:
        signals.append(sig)
    
    return signals
