import pandas as pd
import numpy as np
import logging
from typing import Optional, Tuple
from config import CONFIG

logger = logging.getLogger(__name__)


# ==========================================
# 📈 ТЕХНИЧЕСКИЙ АНАЛИЗ
# ==========================================

def calculate_atr(df: pd.DataFrame, period: int = None) -> float:
    """ATR (Average True Range) - средняя истинная волатильность"""
    period = period or CONFIG['ATR_PERIOD']
    if df is None or len(df) < period:
        return 0.0
    try:
        tr = pd.concat([
            df['high'] - df['low'],
            abs(df['high'] - df['close'].shift()),
            abs(df['low'] - df['close'].shift())
        ], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else 0.0
    except Exception:
        return 0.0


def find_support_resistance(df: pd.DataFrame, window: int = 20) -> Tuple[float, float]:
    """Поиск уровней поддержки и сопротивления"""
    if df is None or len(df) < window:
        cp = df['close'].iloc[-1] if df is not None and len(df) > 0 else 100
        return cp * 0.98, cp * 1.02
    try:
        recent = df.tail(window)
        return float(recent['low'].min()), float(recent['high'].max())
    except Exception:
        cp = df['close'].iloc[-1]
        return cp * 0.98, cp * 1.02


def calculate_rsi(df: pd.DataFrame, period: int = None) -> float:
    """RSI (Relative Strength Index) - индекс относительной силы"""
    period = period or CONFIG['RSI_PERIOD']
    if df is None or len(df) < period:
        return 50.0
    try:
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        if loss.iloc[-1] == 0 or pd.isna(loss.iloc[-1]):
            return 100.0 if gain.iloc[-1] > 0 else 50.0
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0
    except Exception:
        return 50.0


def calculate_macd(df: pd.DataFrame) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """MACD (Moving Average Convergence Divergence)"""
    if df is None or len(df) < 26:
        return None, None, None
    try:
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line
        return (float(macd_line.iloc[-1]), 
                float(signal_line.iloc[-1]), 
                float(histogram.iloc[-1]))
    except Exception:
        return None, None, None


def calculate_trade_levels(price, direction, atr, support, resistance, volatility):
    """Расчёт уровней входа, стоп-лосса и тейк-профитов"""
    if price <= 0:
        price = 100
    if atr <= 0:
        atr = price * 0.01
    
    vol_mult = {'low': 0.8, 'medium': 1.0, 'high': 1.2}.get(volatility, 1.0)
    
    try:
        if direction == 'long':
            stop_distance = atr * CONFIG['STOP_LOSS_ATR_MULTIPLIER'] * vol_mult
            stop_loss = max(price - stop_distance, support * 0.995) if support > 0 else price - stop_distance
            risk = price - stop_loss
            if risk <= 0 or risk < price * 0.001:
                risk = price * 0.02
                stop_loss = price - risk
            tp1 = price + risk * CONFIG['TAKE_PROFIT_LEVELS'][0]
            tp2 = price + risk * CONFIG['TAKE_PROFIT_LEVELS'][1]
            tp3 = min(price + risk * CONFIG['TAKE_PROFIT_LEVELS'][2], resistance) if resistance > 0 else price + risk * CONFIG['TAKE_PROFIT_LEVELS'][2]
            risk_reward = (tp2 - price) / risk if risk > 0 else 0
        elif direction == 'short':
            stop_distance = atr * CONFIG['STOP_LOSS_ATR_MULTIPLIER'] * vol_mult
            stop_loss = min(price + stop_distance, resistance * 1.005) if resistance > 0 else price + stop_distance
            risk = stop_loss - price
            if risk <= 0 or risk < price * 0.001:
                risk = price * 0.02
                stop_loss = price + risk
            tp1 = price - risk * CONFIG['TAKE_PROFIT_LEVELS'][0]
            tp2 = price - risk * CONFIG['TAKE_PROFIT_LEVELS'][1]
            tp3 = max(price - risk * CONFIG['TAKE_PROFIT_LEVELS'][2], support) if support > 0 else price - risk * CONFIG['TAKE_PROFIT_LEVELS'][2]
            risk_reward = (price - tp2) / risk if risk > 0 else 0
        else:
            return {'entry': price, 'stop_loss': price, 'tp1': price, 'tp2': price, 'tp3': price, 'risk_reward': 0}
        
        return {
            'entry': round(price, 2), 'stop_loss': round(stop_loss, 2),
            'tp1': round(tp1, 2), 'tp2': round(tp2, 2), 'tp3': round(tp3, 2),
            'risk_reward': round(max(0, risk_reward), 2)
        }
    except Exception as e:
        logger.error(f"Ошибка расчёта уровней: {e}")
        return {'entry': price, 'stop_loss': price * 0.98, 'tp1': price * 1.01, 
                'tp2': price * 1.02, 'tp3': price * 1.03, 'risk_reward': 0}


def calculate_position_size(balance, risk_pct, entry, stop):
    """Расчёт размера позиции (количество акций)"""
    try:
        if entry <= 0 or stop <= 0 or entry == stop:
            return 0
        risk_per_share = abs(entry - stop)
        if risk_per_share <= 0:
            return 0
        return max(int(balance * risk_pct / risk_per_share), 0)
    except Exception:
        return 0


def determine_trade_direction(rsi, price_change, sentiment, support, resistance, price):
    """Определение направления торговли (long/short/neutral)"""
    score = 0
    if rsi < CONFIG['RSI_OVERSOLD']:
        score += 2
    elif rsi > CONFIG['RSI_OVERBOUGHT']:
        score -= 2
    if price_change > 1.5:
        score += 1
    elif price_change < -1.5:
        score -= 1
    if sentiment > 0.3:
        score += 1
    elif sentiment < -0.3:
        score -= 1
    if support > 0 and price < support * 1.01:
        score += 1
    elif resistance > 0 and price > resistance * 0.99:
        score -= 1
    
    if score >= 2:
        return 'long'
    elif score <= -2:
        return 'short'
    return 'neutral'
