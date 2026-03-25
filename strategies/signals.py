"""
黄金多时间框架量化交易信号引擎 v2
====================================
v2 优化:
1. ADX趋势强度过滤 — ADX>25才允许趋势策略开仓
2. ATR自适应止损 — 1.5×ATR替代固定$20
3. 做空条件放宽 — Keltner做空去掉SMA50限制，用ADX过滤

策略组合:
1. H1 Keltner通道突破 (主力) + ADX过滤
2. H1 MACD+SMA50趋势 (补充) + ADX过滤
3. M15 RSI均值回归 (低风险补充)

所有策略支持做多+做空
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


def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """计算ADX (平均趋向指标)"""
    high = df['High']
    low = df['Low']
    close = df['Close']
    
    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    
    plus_dm = pd.Series(0.0, index=df.index)
    minus_dm = pd.Series(0.0, index=df.index)
    
    plus_dm[(up_move > down_move) & (up_move > 0)] = up_move
    minus_dm[(down_move > up_move) & (down_move > 0)] = down_move
    
    # Smoothed averages
    atr = tr.ewm(alpha=1/period, min_periods=period).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr)
    
    # ADX
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
    adx = dx.ewm(alpha=1/period, min_periods=period).mean()
    
    return adx


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
    
    # ATR (用于Keltner通道 + 自适应止损)
    df['ATR'] = (df['High'] - df['Low']).rolling(14).mean()
    
    # Keltner Channel (EMA20 ± 1.5*ATR)
    df['KC_mid'] = df['Close'].ewm(span=20).mean()
    df['KC_upper'] = df['KC_mid'] + 1.5 * df['ATR']
    df['KC_lower'] = df['KC_mid'] - 1.5 * df['ATR']
    
    # MACD
    df['MACD'] = df['EMA12'] - df['EMA26']
    df['MACD_signal'] = df['MACD'].ewm(span=9).mean()
    df['MACD_hist'] = df['MACD'] - df['MACD_signal']
    
    # RSI
    df['RSI2'] = calc_rsi(df['Close'], 2)
    df['RSI14'] = calc_rsi(df['Close'], 14)
    
    # ADX (趋势强度)
    df['ADX'] = calc_adx(df, 14)
    
    return df


# ── ADX 阈值 ──
ADX_TREND_THRESHOLD = 25    # ADX > 25 = 有趋势
ADX_RANGE_THRESHOLD = 20    # ADX < 20 = 震荡市

# ── ATR 止损倍数 ──
ATR_SL_MULTIPLIER = 1.5     # 止损 = 1.5 × ATR
ATR_SL_MIN = 8              # 最小止损 $8 (防止ATR太小)
ATR_SL_MAX = 40             # 最大止损 $40 (防止ATR太大)


def _calc_atr_stop(df: pd.DataFrame) -> float:
    """根据ATR计算自适应止损距离"""
    atr = float(df.iloc[-1]['ATR'])
    if pd.isna(atr) or atr <= 0:
        return 20  # 默认值
    sl = round(atr * ATR_SL_MULTIPLIER, 2)
    return max(ATR_SL_MIN, min(ATR_SL_MAX, sl))


def check_keltner_signal(df: pd.DataFrame) -> Optional[Dict]:
    """
    Keltner通道突破信号 (v2: +ADX过滤 +ATR止损 +放宽做空)
    
    做多: 价格突破上轨 + 价格>SMA50 + ADX>25
    做空: 价格跌破下轨 + ADX>25 (去掉SMA50限制)
    止损: 1.5×ATR (自适应)
    """
    if len(df) < 55:
        return None
    
    latest = df.iloc[-1]
    close = float(latest['Close'])
    kc_upper = float(latest['KC_upper'])
    kc_lower = float(latest['KC_lower'])
    sma50 = float(latest['SMA50'])
    adx = float(latest['ADX'])
    
    if pd.isna(kc_upper) or pd.isna(sma50) or pd.isna(adx):
        return None
    
    # ADX过滤: 趋势不够强就不开仓
    if adx < ADX_TREND_THRESHOLD:
        return None
    
    sl = _calc_atr_stop(df)
    
    # 做多: 突破上轨 + 价格>SMA50 + ADX>25
    if close > kc_upper and close > sma50:
        return {
            'strategy': 'keltner',
            'signal': 'BUY',
            'reason': f"Keltner做多: 价格{close:.2f} > 上轨{kc_upper:.2f} (ADX={adx:.1f})",
            'close': close,
            'sl': sl,
            'tp': round(sl * 1.75, 2),  # 盈亏比 1:1.75
        }
    
    # 做空: 跌破下轨 + ADX>25 (不再要求<SMA50)
    if close < kc_lower:
        return {
            'strategy': 'keltner',
            'signal': 'SELL',
            'reason': f"Keltner做空: 价格{close:.2f} < 下轨{kc_lower:.2f} (ADX={adx:.1f})",
            'close': close,
            'sl': sl,
            'tp': round(sl * 1.75, 2),
        }
    
    return None


def check_macd_signal(df: pd.DataFrame) -> Optional[Dict]:
    """
    MACD+SMA50趋势信号 (v2: +ADX过滤 +ATR止损 +放宽做空)
    
    做多: MACD柱由负转正 + 价格>SMA50 + ADX>25
    做空: MACD柱由正转负 + ADX>25 (放宽SMA50限制)
    止损: 1.5×ATR
    """
    if len(df) < 30:
        return None
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    close = float(latest['Close'])
    macd_hist = float(latest['MACD_hist'])
    macd_hist_prev = float(prev['MACD_hist'])
    sma50 = float(latest['SMA50'])
    adx = float(latest['ADX'])
    
    if pd.isna(macd_hist) or pd.isna(macd_hist_prev) or pd.isna(sma50) or pd.isna(adx):
        return None
    
    # ADX过滤
    if adx < ADX_TREND_THRESHOLD:
        return None
    
    sl = _calc_atr_stop(df)
    
    # 做多: MACD柱由负转正 + 价格在SMA50上方 + ADX>25
    if macd_hist > 0 and macd_hist_prev <= 0 and close > sma50:
        return {
            'strategy': 'macd',
            'signal': 'BUY',
            'reason': f"MACD做多: 柱状图转正, 价格{close:.2f} > SMA50 (ADX={adx:.1f})",
            'close': close,
            'sl': sl,
            'tp': round(sl * 2.5, 2),  # 盈亏比 1:2.5
        }
    
    # 做空: MACD柱由正转负 + ADX>25
    if macd_hist < 0 and macd_hist_prev >= 0 and adx >= ADX_TREND_THRESHOLD:
        return {
            'strategy': 'macd',
            'signal': 'SELL',
            'reason': f"MACD做空: 柱状图转负 (ADX={adx:.1f})",
            'close': close,
            'sl': sl,
            'tp': round(sl * 2.5, 2),
        }
    
    return None


def check_exit_signal(df: pd.DataFrame, strategy: str, direction: str) -> Optional[str]:
    """检查出场信号"""
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
    
    elif strategy in ('m5_rsi', 'm15_rsi'):
        rsi2 = float(latest['RSI2'])
        if not pd.isna(rsi2):
            if direction == 'BUY' and rsi2 > 55:
                return f"M15 RSI多头出场: RSI(2)={rsi2:.1f} > 55"
            elif direction == 'SELL' and rsi2 < 45:
                return f"M15 RSI空头出场: RSI(2)={rsi2:.1f} < 45"
    
    return None


def check_m15_rsi_signal(df: pd.DataFrame) -> Optional[Dict]:
    """
    M15 RSI均值回归信号 (不需要ADX过滤，均值回归在震荡市反而有效)
    """
    if len(df) < 55:
        return None
    
    latest = df.iloc[-1]
    close = float(latest['Close'])
    rsi2 = float(latest['RSI2'])
    sma50 = float(latest['SMA50'])
    
    if pd.isna(rsi2) or pd.isna(sma50):
        return None
    
    sl = _calc_atr_stop(df) if not pd.isna(df.iloc[-1]['ATR']) else 15
    sl = min(sl, 20)  # RSI策略用较紧的止损
    
    # 做多: 超卖反弹
    if rsi2 < 15 and close > sma50:
        return {
            'strategy': 'm15_rsi',
            'signal': 'BUY',
            'reason': f"M15 RSI做多: RSI(2)={rsi2:.1f} < 15, 超卖反弹",
            'close': close,
            'sl': sl,
            'tp': 0,
        }
    
    # 做空: 超买回落
    if rsi2 > 85 and close < sma50:
        return {
            'strategy': 'm15_rsi',
            'signal': 'SELL',
            'reason': f"M15 RSI做空: RSI(2)={rsi2:.1f} > 85, 超买回落",
            'close': close,
            'sl': sl,
            'tp': 0,
        }
    
    return None


def scan_all_signals(df: pd.DataFrame, timeframe: str = 'H1') -> List[Dict]:
    """扫描所有策略信号"""
    signals = []
    
    if timeframe == 'H1':
        sig = check_keltner_signal(df)
        if sig:
            signals.append(sig)
        
        sig = check_macd_signal(df)
        if sig:
            signals.append(sig)
    
    elif timeframe in ('M5', 'M15'):
        sig = check_m15_rsi_signal(df)
        if sig:
            signals.append(sig)
    
    return signals
