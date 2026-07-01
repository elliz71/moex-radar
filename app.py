import streamlit as st
import requests
import pandas as pd
import feedparser
import time
import sqlite3
import logging
import re
import numpy as np
from datetime import datetime, timedelta
import pytz
import threading
from typing import Optional, Dict, List, Tuple
import json
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==========================================
# ⚙️ КОНФИГУРАЦИЯ
# ==========================================
CONFIG = {
    'ASSETS': {
        'SBER': {'type': 'stock', 'name': 'Сбербанк', 'sector': 'bank', 'keywords': ['сбер', 'банк', 'кредит', 'ипотека', 'дивиденд'], 'volatility': 'medium'},
        'GAZP': {'type': 'stock', 'name': 'Газпром', 'sector': 'energy', 'keywords': ['газпром', 'газ', 'экспорт', 'труба', 'дивиденд'], 'volatility': 'medium'},
        'LKOH': {'type': 'stock', 'name': 'Лукойл', 'sector': 'energy', 'keywords': ['лукойл', 'нефть', 'добыча', 'дивиденд', 'npv'], 'volatility': 'medium'},
        'YNDX': {'type': 'stock', 'name': 'Яндекс', 'sector': 'tech', 'keywords': ['яндекс', 'it', 'технологии', 'регулятор', 'антимонополь'], 'volatility': 'high'},
        'ROSN': {'type': 'stock', 'name': 'Роснефть', 'sector': 'energy', 'keywords': ['роснефть', 'нефть', 'сечин', 'восток', 'дивиденд'], 'volatility': 'medium'},
        'PLZL': {'type': 'stock', 'name': 'Полюс', 'sector': 'metals', 'keywords': ['полюс', 'золото', 'драгметалл', 'добыча'], 'volatility': 'high'},
        'BR0':  {'type': 'futures', 'name': 'Нефть Brent', 'sector': 'commodity', 'keywords': ['нефть', 'brent', 'opec', 'саудов', 'спот'], 'volatility': 'high'},
        'GD0':  {'type': 'futures', 'name': 'Золото', 'sector': 'commodity', 'keywords': ['золото', 'gold', 'fed', 'инфляц', 'убежищ'], 'volatility': 'medium'},
        'Si0':  {'type': 'futures', 'name': 'Доллар/Рубль', 'sector': 'currency', 'keywords': ['доллар', 'рубль', 'цб', 'курс', 'валют', 'санкц'], 'volatility': 'low'}
    },
    'INTERVAL': 10,
    'VOLUME_MULTIPLIER': 2.5,
    'PRICE_CHANGE_THRESHOLD': 1.2,
    'RSI_PERIOD': 14,
    'RSI_OVERSOLD': 30,
    'RSI_OVERBOUGHT': 70,
    'ATR_PERIOD': 14,
    'NEWS_FEED_URL': "https://rssexport.rbc.ru/rbcnews/news/20/full",
    'MSK_TZ': pytz.timezone('Europe/Moscow'),
    'MAX_SIGNALS': 100,
    'CACHE_TTL': 30,
    'FORECAST_HOURS': 2,
    'RISK_PER_TRADE': 0.02,  # 2% риска на сделку
    'MIN_RISK_REWARD': 2.0,   # Минимальное соотношение риск/прибыль 1:2
    'STOP_LOSS_ATR_MULTIPLIER': 1.5,  # Стоп = 1.5 ATR
    'TAKE_PROFIT_LEVELS': [1.0, 2.0, 3.0]  # Множители ATR для целей
}

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# ==========================================
# 🗄️ БАЗА ДАННЫХ
# ==========================================
def init_db():
    conn = sqlite3.connect('signals.db', check_same_thread=False)
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            ticker TEXT,
            name TEXT,
            asset_type TEXT,
            sector TEXT,
            price REAL,
            change_pct REAL,
            volume REAL,
            avg_volume REAL,
            rsi REAL,
            atr REAL,
            signal_strength TEXT,
            news_sentiment REAL,
            forecast_score REAL,
            entry_price REAL,
            stop_loss REAL,
            take_profit_1 REAL,
            take_profit_2 REAL,
            take_profit_3 REAL,
            risk_reward REAL,
            position_size REAL,
            trade_direction TEXT,
            support_level REAL,
            resistance_level REAL
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS news_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            title TEXT,
            url TEXT,
            sentiment_score REAL,
            related_tickers TEXT,
            sector_impact TEXT,
            keywords_found TEXT
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS trade_ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            ticker TEXT,
            name TEXT,
            direction TEXT,
            entry_price REAL,
            stop_loss REAL,
            take_profit_1 REAL,
            take_profit_2 REAL,
            take_profit_3 REAL,
            risk_reward REAL,
            position_size REAL,
            confidence REAL,
            status TEXT,
            exit_signal TEXT,
            exit_timestamp TEXT
        )
    ''')
    
    conn.commit()
    return conn

def save_signal(conn, signal_data: Dict):
    c = conn.cursor()
    c.execute('''
        INSERT INTO signals (timestamp, ticker, name, asset_type, sector, price, change_pct, volume, avg_volume, rsi, atr, signal_strength, news_sentiment, forecast_score, entry_price, stop_loss, take_profit_1, take_profit_2, take_profit_3, risk_reward, position_size, trade_direction, support_level, resistance_level)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        signal_data['timestamp'],
        signal_data['ticker'],
        signal_data['name'],
        signal_data['type'],
        signal_data.get('sector', 'unknown'),
        signal_data['price'],
        signal_data['change_pct'],
        signal_data['volume'],
        signal_data['avg_volume'],
        signal_data.get('rsi', 0),
        signal_data.get('atr', 0),
        signal_data.get('strength', 'medium'),
        signal_data.get('news_sentiment', 0),
        signal_data.get('forecast_score', 0),
        signal_data.get('entry_price', 0),
        signal_data.get('stop_loss', 0),
        signal_data.get('take_profit_1', 0),
        signal_data.get('take_profit_2', 0),
        signal_data.get('take_profit_3', 0),
        signal_data.get('risk_reward', 0),
        signal_data.get('position_size', 0),
        signal_data.get('trade_direction', 'neutral'),
        signal_data.get('support_level', 0),
        signal_data.get('resistance_level', 0)
    ))
    conn.commit()

def save_trade_idea(conn, idea_data: Dict):
    c = conn.cursor()
    c.execute('''
        INSERT INTO trade_ideas (timestamp, ticker, name, direction, entry_price, stop_loss, take_profit_1, take_profit_2, take_profit_3, risk_reward, position_size, confidence, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        idea_data['timestamp'],
        idea_data['ticker'],
        idea_data['name'],
        idea_data['direction'],
        idea_data['entry_price'],
        idea_data['stop_loss'],
        idea_data['take_profit_1'],
        idea_data['take_profit_2'],
        idea_data['take_profit_3'],
        idea_data['risk_reward'],
        idea_data['position_size'],
        idea_data['confidence'],
        idea_data.get('status', 'active')
    ))
    conn.commit()

def save_news_analysis(conn, news_data: Dict):
    c = conn.cursor()
    c.execute('''
        INSERT INTO news_analysis (timestamp, title, url, sentiment_score, related_tickers, sector_impact, keywords_found)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        news_data['timestamp'],
        news_data['title'],
        news_data['url'],
        news_data['sentiment'],
        ','.join(news_data['tickers']),
        news_data.get('sector', 'general'),
        ','.join(news_data['keywords'])
    ))
    conn.commit()

def load_signals(conn, limit: int = 100) -> List[Dict]:
    c = conn.cursor()
    c.execute('SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?', (limit,))
    columns = ['id', 'timestamp', 'ticker', 'name', 'type', 'sector', 'price', 'change_pct', 
               'volume', 'avg_volume', 'rsi', 'atr', 'strength', 'news_sentiment', 'forecast_score',
               'entry_price', 'stop_loss', 'take_profit_1', 'take_profit_2', 'take_profit_3',
               'risk_reward', 'position_size', 'trade_direction', 'support_level', 'resistance_level']
    return [dict(zip(columns, row)) for row in c.fetchall()]

def load_trade_ideas(conn, status: str = 'active') -> List[Dict]:
    c = conn.cursor()
    c.execute('SELECT * FROM trade_ideas WHERE status = ? ORDER BY timestamp DESC', (status,))
    columns = ['id', 'timestamp', 'ticker', 'name', 'direction', 'entry_price', 'stop_loss',
               'take_profit_1', 'take_profit_2', 'take_profit_3', 'risk_reward', 'position_size',
               'confidence', 'status', 'exit_signal', 'exit_timestamp']
    return [dict(zip(columns, row)) for row in c.fetchall()]

def load_news_analysis(conn, limit: int = 20) -> List[Dict]:
    c = conn.cursor()
    c.execute('SELECT * FROM news_analysis ORDER BY timestamp DESC LIMIT ?', (limit,))
    columns = ['id', 'timestamp', 'title', 'url', 'sentiment', 'tickers', 'sector', 'keywords']
    return [dict(zip(columns, row)) for row in c.fetchall()]

# ==========================================
# 📊 ТЕХНИЧЕСКИЙ АНАЛИЗ
# ==========================================
def calculate_atr(df: pd.DataFrame, period: int = None) -> float:
    """Average True Range - мера волатильности"""
    period = period or CONFIG['ATR_PERIOD']
    if len(df) < period:
        return 0.0
    
    high = df['high']
    low = df['low']
    close = df['close']
    
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    
    return float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else 0.0

def find_support_resistance(df: pd.DataFrame, window: int = 20) -> Tuple[float, float]:
    """Поиск уровней поддержки и сопротивления"""
    if len(df) < window:
        current_price = df['close'].iloc[-1]
        return current_price * 0.98, current_price * 1.02
    
    recent_data = df.tail(window)
    
    # Поддержка - минимум последних N свечей
    support = recent_data['low'].min()
    
    # Сопротивление - максимум последних N свечей
    resistance = recent_data['high'].max()
    
    return float(support), float(resistance)

def calculate_rsi(df: pd.DataFrame, period: int = None) -> float:
    period = period or CONFIG['RSI_PERIOD']
    if len(df) < period:
        return 50.0
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0

def calculate_trade_levels(price: float, direction: str, atr: float, support: float, resistance: float, volatility: str) -> Dict:
    """
    Расчет торговых уровней: Entry, Stop Loss, Take Profit
    """
    # Множитель ATR зависит от волатильности актива
    volatility_multipliers = {
        'low': 0.8,
        'medium': 1.0,
        'high': 1.2
    }
    vol_mult = volatility_multipliers.get(volatility, 1.0)
    
    if direction == 'long':
        # Вход: чуть выше текущей цены (на пробое) или на откате к поддержке
        entry = price
        
        # Стоп-лосс: ниже поддержки или на расстоянии ATR * множитель
        stop_distance = atr * CONFIG['STOP_LOSS_ATR_MULTIPLIER'] * vol_mult
        stop_from_support = support * 0.995  # Чуть ниже поддержки
        stop_loss = max(price - stop_distance, stop_from_support)
        
        # Тейк-профиты: на основе Risk/Reward
        risk = entry - stop_loss
        
        tp1 = entry + (risk * CONFIG['TAKE_PROFIT_LEVELS'][0])  # 1:1
        tp2 = entry + (risk * CONFIG['TAKE_PROFIT_LEVELS'][1])  # 1:2
        tp3 = min(entry + (risk * CONFIG['TAKE_PROFIT_LEVELS'][2]), resistance)  # 1:3 или сопротивление
        
        # Risk/Reward ratio
        reward = tp2 - entry
        risk_reward = reward / risk if risk > 0 else 0
        
    elif direction == 'short':
        entry = price
        
        # Стоп-лосс: выше сопротивления
        stop_distance = atr * CONFIG['STOP_LOSS_ATR_MULTIPLIER'] * vol_mult
        stop_from_resistance = resistance * 1.005
        stop_loss = min(price + stop_distance, stop_from_resistance)
        
        risk = stop_loss - entry
        
        tp1 = entry - (risk * CONFIG['TAKE_PROFIT_LEVELS'][0])
        tp2 = entry - (risk * CONFIG['TAKE_PROFIT_LEVELS'][1])
        tp3 = max(entry - (risk * CONFIG['TAKE_PROFIT_LEVELS'][2]), support)
        
        reward = entry - tp2
        risk_reward = reward / risk if risk > 0 else 0
        
    else:  # neutral
        return {
            'entry': price,
            'stop_loss': price,
            'tp1': price,
            'tp2': price,
            'tp3': price,
            'risk_reward': 0
        }
    
    return {
        'entry': round(entry, 2),
        'stop_loss': round(stop_loss, 2),
        'tp1': round(tp1, 2),
        'tp2': round(tp2, 2),
        'tp3': round(tp3, 2),
        'risk_reward': round(risk_reward, 2)
    }

def calculate_position_size(account_balance: float, risk_per_trade: float, entry: float, stop_loss: float) -> int:
    """Расчет размера позиции исходя из риска"""
    if entry <= 0 or stop_loss <= 0 or entry == stop_loss:
        return 0
    
    risk_amount = account_balance * risk_per_trade
    risk_per_share = abs(entry - stop_loss)
    
    shares = int(risk_amount / risk_per_share)
    
    return max(shares, 0)

def determine_trade_direction(rsi: float, price_change: float, sentiment: float, support: float, resistance: float, current_price: float) -> str:
    """Определение направления сделки"""
    score = 0
    
    # RSI
    if rsi < CONFIG['RSI_OVERSOLD']:
        score += 2  # Перепроданность → лонг
    elif rsi > CONFIG['RSI_OVERBOUGHT']:
        score -= 2  # Перекупленность → шорт
    
    # Движение цены
    if price_change > 1.5:
        score += 1  # Сильный рост → лонг
    elif price_change < -1.5:
        score -= 1  # Сильное падение → шорт
    
    # Сентимент
    if sentiment > 0.3:
        score += 1
    elif sentiment < -0.3:
        score -= 1
    
    # Позиция относительно уровней
    if current_price < support * 1.01:  # Около поддержки
        score += 1
    elif current_price > resistance * 0.99:  # Около сопротивления
        score -= 1
    
    if score >= 2:
        return 'long'
    elif score <= -2:
        return 'short'
    else:
        return 'neutral'

def generate_exit_signals(current_price: float, entry: float, stop_loss: float, tp1: float, tp2: float, tp3: float, direction: str, rsi: float) -> List[str]:
    """Генерация сигналов на выход из позиции"""
    signals = []
    
    if direction == 'long':
        if current_price <= stop_loss:
            signals.append("🔴 СТОП-ЛОСС: Цена достигла уровня стопа. Закрывайте позицию для ограничения убытков.")
        
        if current_price >= tp1:
            signals.append(f"🟡 ЦЕЛЬ 1 ДОСТИГНУТА ({tp1:.2f}): Рекомендуется зафиксировать 1/3 позиции и перенести стоп в безубыток.")
        
        if current_price >= tp2:
            signals.append(f"🟢 ЦЕЛЬ 2 ДОСТИГНУТА ({tp2:.2f}): Зафиксируйте еще 1/3 позиции. Оставшуюся часть ведите с трейлинг-стопом.")
        
        if current_price >= tp3:
            signals.append(f"🎯 ЦЕЛЬ 3 ДОСТИГНУТА ({tp3:.2f}): Полностью закрывайте позицию. Отличный результат!")
        
        if rsi > CONFIG['RSI_OVERBOUGHT'] and current_price > entry * 1.05:
            signals.append(f"⚠️ RSI ПЕРЕКУПЛЕННОСТЬ ({rsi:.1f}): Рынок перегрет. Рассмотрите частичную фиксацию прибыли.")
    
    elif direction == 'short':
        if current_price >= stop_loss:
            signals.append("🔴 СТОП-ЛОСС: Цена достигла уровня стопа. Закрывайте позицию.")
        
        if current_price <= tp1:
            signals.append(f"🟡 ЦЕЛЬ 1 ДОСТИГНУТА ({tp1:.2f}): Зафиксируйте 1/3 позиции и перенесите стоп в безубыток.")
        
        if current_price <= tp2:
            signals.append(f"🟢 ЦЕЛЬ 2 ДОСТИГНУТА ({tp2:.2f}): Зафиксируйте еще 1/3. Ведите остаток с трейлинг-стопом.")
        
        if current_price <= tp3:
            signals.append(f"🎯 ЦЕЛЬ 3 ДОСТИГНУТА ({tp3:.2f}): Полностью закрывайте позицию.")
        
        if rsi < CONFIG['RSI_OVERSOLD'] and current_price < entry * 0.95:
            signals.append(f"⚠️ RSI ПЕРЕПРОДАННОСТЬ ({rsi:.1f}): Возможна коррекция. Рассмотрите фиксацию.")
    
    return signals

# ==========================================
# 📰 NLP-АНАЛИЗ НОВОСТЕЙ
# ==========================================
POSITIVE_WORDS = {
    'рост', 'повышен', 'увелич', 'прибыл', 'доход', 'дивиденд', 'покуп', 'оптимизм', 
    'успех', 'рекорд', 'превыш', 'прогноз', 'позитив', 'поддерж', 'развит', 'инвест',
    'сделк', 'партнер', 'экспорт', 'спрос', 'дефицит', 'подорожан', 'укрепл'
}

NEGATIVE_WORDS = {
    'пад', 'снижен', 'убыт', 'потерь', 'рис', 'опас', 'негатив', 'проблем', 
    'криз', 'санкц', 'огранич', 'запрет', 'штраф', 'суд', 'расслед', 'отказ',
    'задерж', 'авар', 'пожар', 'конфликт', 'войн', 'эскал', 'инфляц', 'рецесс',
    'девальв', 'обвал', 'паник', 'распродаж', 'давлен', 'сниж', 'коррекц'
}

MACRO_KEYWORDS = {
    'цб': ['ставк', 'ключев', 'денежн', 'кредит', 'инфляц'],
    'нефть': ['brent', 'urals', 'opec', 'добыч', 'квот', 'спот', 'фьючерс'],
    'золото': ['gold', 'xau', 'драгметалл', 'убежищ', 'fed', 'доллар'],
    'санкции': ['огранич', 'запрет', 'списк', 'блокиров', 'экспорт', 'импорт'],
    'дивиденды': ['выплат', 'реестр', 'отсеч', 'акционер', 'совет', 'рекоменд']
}

def analyze_news_sentiment(title: str, description: str = '') -> Tuple[float, List[str], str]:
    text = (title + ' ' + description).lower()
    pos_count = sum(1 for word in POSITIVE_WORDS if word in text)
    neg_count = sum(1 for word in NEGATIVE_WORDS if word in text)
    total = pos_count + neg_count
    sentiment = (pos_count - neg_count) / max(total, 1)
    
    found_tickers = []
    found_keywords = []
    sector = 'general'
    
    for ticker, info in CONFIG['ASSETS'].items():
        for keyword in info['keywords']:
            if keyword in text:
                found_tickers.append(ticker)
                found_keywords.append(keyword)
                if info['sector'] != 'general':
                    sector = info['sector']
                break
    
    for macro_cat, keywords in MACRO_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            found_keywords.append(f'macro:{macro_cat}')
    
    return round(sentiment, 2), found_tickers, sector, found_keywords

def calculate_forecast_score(signal_data: Dict, news_sentiment: float, historical_data: List[Dict]) -> float:
    score = 50.0
    price_momentum = min(abs(signal_data['change_pct']) * 10, 20)
    score += price_momentum if signal_data['change_pct'] > 0 else -price_momentum
    
    volume_factor = min((signal_data['volume'] / max(signal_data['avg_volume'], 1) - 1) * 15, 25)
    score += volume_factor if signal_data['change_pct'] > 0 else -volume_factor
    
    rsi = signal_data.get('rsi', 50)
    if rsi < CONFIG['RSI_OVERSOLD']:
        score += 15
    elif rsi > CONFIG['RSI_OVERBOUGHT']:
        score -= 15
    
    score += news_sentiment * 20
    
    ticker = signal_data['ticker']
    ticker_history = [s for s in historical_data if s['ticker'] == ticker]
    if len(ticker_history) >= 5:
        success_rate = sum(1 for s in ticker_history[-10:] if s['change_pct'] > 0) / len(ticker_history[-10:])
        score += (success_rate - 0.5) * 20
    
    return max(0, min(100, round(score)))

# ==========================================
# 📊 MOEX API
# ==========================================
@st.cache_data(ttl=CONFIG['CACHE_TTL'])
def get_moex_data(ticker: str, asset_type: str) -> Optional[pd.DataFrame]:
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if asset_type == 'stock':
                url = f"https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/{ticker}/candles.json?interval={CONFIG['INTERVAL']}"
            else:
                url = f"https://iss.moex.com/iss/engines/futures/markets/main/securities/{ticker}/candles.json?interval={CONFIG['INTERVAL']}"
            
            response = requests.get(url, headers=HEADERS, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if 'candles' in data and 'data' in data['candles']:
                return pd.DataFrame(data['candles']['data'], columns=data['candles']['columns'])
                
        except Exception as e:
            logger.warning(f"Попытка {attempt + 1}/{max_retries} для {ticker}: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            continue
    return None

def is_market_open() -> bool:
    now = datetime.now(CONFIG['MSK_TZ'])
    return now.weekday() < 5 and 10 <= now.hour < 24

# ==========================================
# 🤖 ФОНОВЫЙ МОНИТОРИНГ
# ==========================================
def background_monitor():
    conn = init_db()
    alerted_candles = {}
    
    while True:
        try:
            if is_market_open():
                # Парсинг новостей
                try:
                    feed = feedparser.parse(CONFIG['NEWS_FEED_URL'])
                    for entry in feed.entries[:10]:
                        title = entry.get('title', '')
                        desc = entry.get('summary', '')
                        url = entry.get('link', '')
                        sentiment, tickers, sector, keywords = analyze_news_sentiment(title, desc)
                        
                        if tickers or sentiment != 0:
                            news_data = {
                                'timestamp': datetime.now(CONFIG['MSK_TZ']).isoformat(),
                                'title': title,
                                'url': url,
                                'sentiment': sentiment,
                                'tickers': tickers,
                                'sector': sector,
                                'keywords': keywords
                            }
                            save_news_analysis(conn, news_data)
                except Exception as e:
                    logger.error(f"Ошибка парсинга новостей: {e}")
                
                # Мониторинг цен
                for ticker, info in CONFIG['ASSETS'].items():
                    df = get_moex_data(ticker, info['type'])
                    
                    if df is not None and len(df) >= 5:
                        current_volume = df['volume'].iloc[-1]
                        current_close = df['close'].iloc[-1]
                        prev_close = df['close'].iloc[-2]
                        candle_time = df['begin'].iloc[-1]
                        
                        if alerted_candles.get(ticker) == candle_time:
                            continue
                        
                        avg_volume = df['volume'].iloc[:-1].mean()
                        price_change_pct = ((current_close - prev_close) / prev_close) * 100
                        
                        volume_anomaly = current_volume > (avg_volume * CONFIG['VOLUME_MULTIPLIER'])
                        price_anomaly = abs(price_change_pct) >= CONFIG['PRICE_CHANGE_THRESHOLD']
                        
                        if volume_anomaly and price_anomaly:
                            rsi = calculate_rsi(df)
                            atr = calculate_atr(df)
                            support, resistance = find_support_resistance(df)
                            
                            strength = 'strong' if abs(price_change_pct) > 3.0 else 'medium'
                            if rsi < CONFIG['RSI_OVERSOLD'] or rsi > CONFIG['RSI_OVERBOUGHT']:
                                strength = 'strong'
                            
                            # Новостной сентимент
                            recent_news = load_news_analysis(conn, limit=5)
                            ticker_news_sentiment = 0
                            ticker_news = [n for n in recent_news if ticker in n['tickers']]
                            if ticker_news:
                                ticker_news_sentiment = sum(n['sentiment'] for n in ticker_news) / len(ticker_news)
                            
                            # Прогноз
                            historical = load_signals(conn, limit=50)
                            forecast = calculate_forecast_score(
                                {'ticker': ticker, 'change_pct': price_change_pct, 'volume': current_volume, 
                                 'avg_volume': avg_volume, 'rsi': rsi},
                                ticker_news_sentiment,
                                historical
                            )
                            
                            # Направление сделки
                            direction = determine_trade_direction(
                                rsi, price_change_pct, ticker_news_sentiment, 
                                support, resistance, current_close
                            )
                            
                            # Торговые уровни
                            trade_levels = calculate_trade_levels(
                                current_close, direction, atr, support, resistance, 
                                info.get('volatility', 'medium')
                            )
                            
                            # Размер позиции (пример для депозита 100,000 руб)
                            position_size = calculate_position_size(
                                100000, CONFIG['RISK_PER_TRADE'],
                                trade_levels['entry'], trade_levels['stop_loss']
                            )
                            
                            signal = {
                                'timestamp': datetime.now(CONFIG['MSK_TZ']).isoformat(),
                                'ticker': ticker,
                                'name': info['name'],
                                'type': info['type'],
                                'sector': info.get('sector', 'unknown'),
                                'price': float(current_close),
                                'change_pct': float(price_change_pct),
                                'volume': float(current_volume),
                                'avg_volume': float(avg_volume),
                                'rsi': rsi,
                                'atr': atr,
                                'strength': strength,
                                'news_sentiment': ticker_news_sentiment,
                                'forecast_score': forecast,
                                'entry_price': trade_levels['entry'],
                                'stop_loss': trade_levels['stop_loss'],
                                'take_profit_1': trade_levels['tp1'],
                                'take_profit_2': trade_levels['tp2'],
                                'take_profit_3': trade_levels['tp3'],
                                'risk_reward': trade_levels['risk_reward'],
                                'position_size': position_size,
                                'trade_direction': direction,
                                'support_level': support,
                                'resistance_level': resistance
                            }
                            
                            save_signal(conn, signal)
                            
                            # Сохраняем торговую идею
                            if direction != 'neutral' and trade_levels['risk_reward'] >= CONFIG['MIN_RISK_REWARD']:
                                idea = {
                                    'timestamp': signal['timestamp'],
                                    'ticker': ticker,
                                    'name': info['name'],
                                    'direction': direction,
                                    'entry_price': trade_levels['entry'],
                                    'stop_loss': trade_levels['stop_loss'],
                                    'take_profit_1': trade_levels['tp1'],
                                    'take_profit_2': trade_levels['tp2'],
                                    'take_profit_3': trade_levels['tp3'],
                                    'risk_reward': trade_levels['risk_reward'],
                                    'position_size': position_size,
                                    'confidence': forecast,
                                    'status': 'active'
                                }
                                save_trade_idea(conn, idea)
                                logger.info(f"💡 Торговая идея: {ticker} {direction} | R:R = {trade_levels['risk_reward']:.2f}")
                            
                            alerted_candles[ticker] = candle_time
                            logger.info(f"🎯 Сигнал: {ticker} {price_change_pct:+.2f}% | Прогноз: {forecast:.0f}%")
                    
                    time.sleep(1)
                time.sleep(15)
            else:
                time.sleep(60)
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
            time.sleep(30)

# ==========================================
# 🎨 ИНТЕРФЕЙС
# ==========================================
def main():
    st.set_page_config(page_title="Макро-Радар МОЕХ v3.0", page_icon="🎯", layout="wide")
    
    st.markdown("""
    <style>
        .main { background-color: #0e1117; }
        .trade-long { border-left: 4px solid #00ff00; padding: 15px; background: rgba(0,255,0,0.05); }
        .trade-short { border-left: 4px solid #ff4444; padding: 15px; background: rgba(255,68,68,0.05); }
        .exit-signal { background: #262730; padding: 10px; margin: 5px 0; border-radius: 5px; }
    </style>
    """, unsafe_allow_html=True)
    
    if 'monitor_running' not in st.session_state:
        st.session_state.monitor_running = False
        threading.Thread(target=background_monitor, daemon=True).start()
        st.session_state.monitor_running = True
    
    st.title("🎯 Макро-Радар: Торговые Рекомендации")
    st.warning("⚠️ **Дисклеймер:** Это аналитический инструмент. Все торговые решения вы принимаете самостоятельно. Всегда используйте стоп-лоссы и не рискуйте больше 2% капитала на сделку.")
    
    market_status = "🟢 Торги идут" if is_market_open() else "🔴 Рынок закрыт"
    st.caption(f"**Статус:** {market_status} | **Обновлено:** {datetime.now().strftime('%H:%M:%S')}")
    
    with st.sidebar:
        st.header("⚙️ Настройки")
        account_balance = st.number_input("💰 Депозит (руб)", value=100000, step=10000)
        st.metric("Риск на сделку", f"{CONFIG['RISK_PER_TRADE']*100:.1f}%")
        st.metric("Мин. R:R", f"1:{CONFIG['MIN_RISK_REWARD']}")
        
        st.markdown("---")
        if st.button("🔄 Обновить"):
            st.rerun()
    
    conn = init_db()
    signals = load_signals(conn)
    trade_ideas = load_trade_ideas(conn, 'active')
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Всего сигналов", len(signals))
    with col2:
        st.metric("Активных идей", len(trade_ideas))
    with col3:
        long_ideas = len([i for i in trade_ideas if i['direction'] == 'long'])
        st.metric("Лонг идеи", long_ideas)
    with col4:
        short_ideas = len([i for i in trade_ideas if i['direction'] == 'short'])
        st.metric("Шорт идеи", short_ideas)
    
    st.markdown("---")
    
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "💡 Торговые идеи", "🎯 Сигналы с уровнями", "🚨 Активные позиции",
        "📰 Новости", "📊 Аналитика"
    ])
    
    with tab1:
        st.subheader("Готовые торговые планы")
        
        if not trade_ideas:
            st.info("Ожидание торговых идей с хорошим Risk/Reward...")
        else:
            for idea in trade_ideas[:10]:
                direction_emoji = "📈" if idea['direction'] == 'long' else "📉"
                css_class = "trade-long" if idea['direction'] == 'long' else "trade-short"
                
                # Проверка выхода
                df = get_moex_data(idea['ticker'], CONFIG['ASSETS'][idea['ticker']]['type'])
                exit_signals = []
                if df is not None:
                    current_price = df['close'].iloc[-1]
                    rsi = calculate_rsi(df)
                    exit_signals = generate_exit_signals(
                        current_price, idea['entry_price'], idea['stop_loss'],
                        idea['take_profit_1'], idea['take_profit_2'], idea['take_profit_3'],
                        idea['direction'], rsi
                    )
                
                with st.container():
                    st.markdown(f'<div class="{css_class}">', unsafe_allow_html=True)
                    
                    col1, col2, col3 = st.columns([2, 1, 1])
                    with col1:
                        st.markdown(f"**{direction_emoji} {idea['name']} ({idea['ticker']})**")
                        st.caption(f"Направление: **{idea['direction'].upper()}** | Уверенность: {idea['confidence']:.0f}%")
                    with col2:
                        st.metric("Вход", f"{idea['entry_price']:.2f}")
                    with col3:
                        st.metric("R:R", f"1:{idea['risk_reward']:.1f}")
                    
                    st.markdown("---")
                    
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.markdown(f"**🛑 Стоп-лосс**")
                        st.markdown(f"<span style='color:#ff4444; font-size:20px;'>{idea['stop_loss']:.2f}</span>", unsafe_allow_html=True)
                        stop_pct = abs(idea['entry_price'] - idea['stop_loss']) / idea['entry_price'] * 100
                        st.caption(f"Риск: {stop_pct:.2f}%")
                    
                    with col2:
                        st.markdown(f"**🎯 Цель 1**")
                        st.markdown(f"<span style='color:#ffaa00; font-size:20px;'>{idea['take_profit_1']:.2f}</span>", unsafe_allow_html=True)
                        tp1_pct = abs(idea['take_profit_1'] - idea['entry_price']) / idea['entry_price'] * 100
                        st.caption(f"Прибыль: {tp1_pct:.2f}%")
                    
                    with col3:
                        st.markdown(f"**🎯 Цель 2**")
                        st.markdown(f"<span style='color:#00ff00; font-size:20px;'>{idea['take_profit_2']:.2f}</span>", unsafe_allow_html=True)
                        tp2_pct = abs(idea['take_profit_2'] - idea['entry_price']) / idea['entry_price'] * 100
                        st.caption(f"Прибыль: {tp2_pct:.2f}%")
                    
                    with col4:
                        st.markdown(f"**🎯 Цель 3**")
                        st.markdown(f"<span style='color:#00ffff; font-size:20px;'>{idea['take_profit_3']:.2f}</span>", unsafe_allow_html=True)
                        tp3_pct = abs(idea['take_profit_3'] - idea['entry_price']) / idea['entry_price'] * 100
                        st.caption(f"Прибыль: {tp3_pct:.2f}%")
                    
                    st.markdown(f"**📊 Размер позиции:** {idea['position_size']} акций | **Риск:** {account_balance * CONFIG['RISK_PER_TRADE']:,.0f} руб")
                    
                    if exit_signals:
                        st.markdown("---")
                        st.markdown("**⚠️ Сигналы на выход:**")
                        for sig in exit_signals:
                            st.markdown(f'<div class="exit-signal">{sig}</div>', unsafe_allow_html=True)
                    
                    st.markdown('</div>', unsafe_allow_html=True)
                    st.divider()
    
    with tab2:
        st.subheader("Сигналы с торговыми уровнями")
        
        if not signals:
            st.info("Ожидание сигналов...")
        else:
            for sig in signals[:15]:
                direction_emoji = "📈" if sig['trade_direction'] == 'long' else "📉" if sig['trade_direction'] == 'short' else "⚖️"
                
                with st.expander(f"{direction_emoji} {sig['name']} | {sig['change_pct']:+.2f}% | Прогноз: {sig['forecast_score']:.0f}%", expanded=True):
                    col1, col2, col3, col4, col5 = st.columns(5)
                    with col1:
                        st.metric("Цена", f"{sig['price']:.2f}")
                    with col2:
                        st.metric("RSI", f"{sig['rsi']:.1f}")
                    with col3:
                        st.metric("ATR", f"{sig['atr']:.2f}")
                    with col4:
                        st.metric("Направление", sig['trade_direction'].upper())
                    with col5:
                        st.metric("R:R", f"1:{sig['risk_reward']:.1f}")
                    
                    st.markdown("---")
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.markdown("**Точка входа**")
                        st.markdown(f"<span style='font-size:24px; color:#00ffcc;'>{sig['entry_price']:.2f}</span>", unsafe_allow_html=True)
                    
                    with col2:
                        st.markdown("**Стоп-лосс**")
                        st.markdown(f"<span style='font-size:24px; color:#ff4444;'>{sig['stop_loss']:.2f}</span>", unsafe_allow_html=True)
                    
                    with col3:
                        st.markdown("**Размер позиции**")
                        st.markdown(f"<span style='font-size:24px;'>{sig['position_size']} шт</span>", unsafe_allow_html=True)
                    
                    st.markdown("**Цели:**")
                    st.markdown(f"- Цель 1: **{sig['take_profit_1']:.2f}** (консервативная)")
                    st.markdown(f"- Цель 2: **{sig['take_profit_2']:.2f}** (основная)")
                    st.markdown(f"- Цель 3: **{sig['take_profit_3']:.2f}** (агрессивная)")
                    
                    st.caption(f"Поддержка: {sig['support_level']:.2f} | Сопротивление: {sig['resistance_level']:.2f} | Объем: {sig['volume']:,.0f} | Сентимент: {sig['news_sentiment']:+.2f}")
    
    with tab3:
        st.subheader("Мониторинг активных позиций")
        
        if not trade_ideas:
            st.info("Нет активных позиций")
        else:
            st.markdown("Система автоматически отслеживает достижение целей и стопов:")
            
            for idea in trade_ideas:
                df = get_moex_data(idea['ticker'], CONFIG['ASSETS'][idea['ticker']]['type'])
                if df is not None:
                    current_price = df['close'].iloc[-1]
                    rsi = calculate_rsi(df)
                    
                    # Расчет P&L
                    if idea['direction'] == 'long':
                        pnl_pct = (current_price - idea['entry_price']) / idea['entry_price'] * 100
                    else:
                        pnl_pct = (idea['entry_price'] - current_price) / idea['entry_price'] * 100
                    
                    pnl_color = "green" if pnl_pct >= 0 else "red"
                    
                    with st.container():
                        col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                        with col1:
                            st.markdown(f"**{idea['name']}** ({idea['ticker']})")
                            st.caption(f"Вход: {idea['entry_price']:.2f}")
                        with col2:
                            st.markdown(f"**Текущая:**")
                            st.markdown(f"<span style='color:{pnl_color}; font-size:18px;'>{current_price:.2f}</span>", unsafe_allow_html=True)
                        with col3:
                            st.markdown(f"**P&L:**")
                            st.markdown(f"<span style='color:{pnl_color}; font-size:18px;'>{pnl_pct:+.2f}%</span>", unsafe_allow_html=True)
                        with col4:
                            st.markdown(f"**RSI:**")
                            st.markdown(f"{rsi:.1f}")
                        
                        # Проверка уровней
                        status_messages = []
                        if idea['direction'] == 'long':
                            if current_price <= idea['stop_loss']:
                                status_messages.append("🔴 СТОП СРАБОТАЛ")
                            if current_price >= idea['take_profit_1']:
                                status_messages.append("🟡 Цель 1")
                            if current_price >= idea['take_profit_2']:
                                status_messages.append("🟢 Цель 2")
                            if current_price >= idea['take_profit_3']:
                                status_messages.append("🎯 Цель 3")
                        else:
                            if current_price >= idea['stop_loss']:
                                status_messages.append("🔴 СТОП СРАБОТАЛ")
                            if current_price <= idea['take_profit_1']:
                                status_messages.append("🟡 Цель 1")
                            if current_price <= idea['take_profit_2']:
                                status_messages.append("🟢 Цель 2")
                            if current_price <= idea['take_profit_3']:
                                status_messages.append("🎯 Цель 3")
                        
                        if status_messages:
                            st.markdown(" | ".join(status_messages))
                        
                        st.divider()
    
    with tab4:
        st.subheader("Новости с аналитикой")
        news = load_news_analysis(conn)
        
        if not news:
            st.info("Загрузка новостей...")
        else:
            for n in news[:10]:
                sentiment_emoji = "🟢" if n['sentiment'] > 0.2 else "🔴" if n['sentiment'] < -0.2 else "🟡"
                st.markdown(f"{sentiment_emoji} **[{n['title']}]({n['url']})**")
                st.caption(f"Сентимент: {n['sentiment']:+.2f} | Тикеры: {', '.join(n['tickers']) if n['tickers'] else '—'}")
                st.divider()
    
    with tab5:
        st.subheader("Статистика и аналитика")
        
        if len(signals) < 10:
            st.info("Недостаточно данных")
        else:
            df = pd.DataFrame(signals)
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("#### Распределение направлений")
                direction_counts = df['trade_direction'].value_counts()
                st.bar_chart(direction_counts)
            
            with col2:
                st.markdown("#### Risk/Reward по сигналам")
                st.histogram(df['risk_reward'], bins=10)
            
            st.markdown("#### Средняя точность прогнозов")
            avg_forecast = df['forecast_score'].mean()
            st.metric("Средний прогноз", f"{avg_forecast:.1f}%")
            
            if len(df) >= 20:
                corr = df['news_sentiment'].corr(df['change_pct'])
                st.metric("Корреляция новости→цена", f"{corr:.3f}")
    
    time.sleep(30)
    st.rerun()

if __name__ == "__main__":
    main()
