import streamlit as st
import requests
import pandas as pd
import feedparser
import time
import sqlite3
import logging
import numpy as np
import matplotlib.pyplot as plt
import mplfinance as mpf
from matplotlib.lines import Line2D
from datetime import datetime
import pytz
import threading
from typing import Optional, Dict, List, Tuple

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
    'CACHE_TTL': 30,
    'RISK_PER_TRADE': 0.02,
    'MIN_RISK_REWARD': 2.0,
    'STOP_LOSS_ATR_MULTIPLIER': 1.5,
    'TAKE_PROFIT_LEVELS': [1.0, 2.0, 3.0],
    'AUTO_LABEL_HOURS': 2
}

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

# ==========================================
# 🔒 БЕЗОПАСНАЯ РАБОТА С SQLITE
# ==========================================
DB_LOCK = threading.Lock()

def get_db_connection():
    """Создание соединения с БД"""
    return sqlite3.connect('signals.db', check_same_thread=False, timeout=10)

def init_db():
    """Инициализация базы данных"""
    with DB_LOCK:
        conn = get_db_connection()
        try:
            c = conn.cursor()
            c.execute('''
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT, ticker TEXT, name TEXT, asset_type TEXT, sector TEXT,
                    price REAL, change_pct REAL, volume REAL, avg_volume REAL,
                    rsi REAL, atr REAL, signal_strength TEXT, news_sentiment REAL,
                    forecast_score REAL, entry_price REAL, stop_loss REAL,
                    take_profit_1 REAL, take_profit_2 REAL, take_profit_3 REAL,
                    risk_reward REAL, position_size REAL, trade_direction TEXT,
                    support_level REAL, resistance_level REAL,
                    outcome TEXT DEFAULT 'pending', pnl_pct REAL DEFAULT 0,
                    max_price REAL DEFAULT 0, min_price REAL DEFAULT 0,
                    hours_elapsed REAL DEFAULT 0, checked INTEGER DEFAULT 0,
                    exit_reason TEXT DEFAULT ''
                )
            ''')
            c.execute("PRAGMA table_info(signals)")
            columns = [col[1] for col in c.fetchall()]
            for col in ['outcome', 'pnl_pct', 'max_price', 'min_price', 'hours_elapsed', 'checked', 'exit_reason']:
                if col not in columns:
                    try:
                        if col in ['pnl_pct', 'max_price', 'min_price', 'hours_elapsed']:
                            c.execute(f'ALTER TABLE signals ADD COLUMN {col} REAL DEFAULT 0')
                        elif col == 'checked':
                            c.execute(f'ALTER TABLE signals ADD COLUMN {col} INTEGER DEFAULT 0')
                        else:
                            c.execute(f'ALTER TABLE signals ADD COLUMN {col} TEXT DEFAULT ""')
                    except Exception as e:
                        logger.warning(f"Migration {col}: {e}")
            c.execute('''CREATE TABLE IF NOT EXISTS news_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, title TEXT, url TEXT,
                sentiment_score REAL, related_tickers TEXT, sector_impact TEXT, keywords_found TEXT)''')
            c.execute('''CREATE TABLE IF NOT EXISTS trade_ideas (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, ticker TEXT, name TEXT, direction TEXT,
                entry_price REAL, stop_loss REAL, take_profit_1 REAL, take_profit_2 REAL, take_profit_3 REAL,
                risk_reward REAL, position_size REAL, confidence REAL, status TEXT,
                exit_signal TEXT, exit_timestamp TEXT)''')
            conn.commit()
        except Exception as e:
            logger.error(f"Ошибка инициализации БД: {e}")
        finally:
            conn.close()

def execute_db_query(query, params=None, fetch=False):
    """Безопасное выполнение SQL-запросов"""
    with DB_LOCK:
        conn = get_db_connection()
        try:
            c = conn.cursor()
            if params:
                c.execute(query, params)
            else:
                c.execute(query)
            result = c.fetchall() if fetch else None
            conn.commit()
            return result
        except Exception as e:
            logger.error(f"Ошибка SQL: {e}")
            return [] if fetch else None
        finally:
            conn.close()

# ==========================================
# 📊 MOEX API
# ==========================================
def fetch_moex_data_raw(ticker: str, asset_type: str) -> Optional[pd.DataFrame]:
    """Сырая функция получения данных (для фонового потока)"""
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
            logger.warning(f"Попытка {attempt+1}/{max_retries} для {ticker}: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            continue
    return None

@st.cache_data(ttl=CONFIG['CACHE_TTL'])
def get_moex_data(ticker: str, asset_type: str) -> Optional[pd.DataFrame]:
    """Кэшированная версия для UI"""
    return fetch_moex_data_raw(ticker, asset_type)

# ==========================================
# 📈 ТЕХНИЧЕСКИЙ АНАЛИЗ
# ==========================================
def calculate_atr(df: pd.DataFrame, period: int = None) -> float:
    """Average True Range"""
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
    """Уровни поддержки и сопротивления"""
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
    """RSI индикатор"""
    period = period or CONFIG['RSI_PERIOD']
    if df is None or len(df) < period:
        return 50.0
    try:
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        # Защита от деления на ноль
        if loss.iloc[-1] == 0 or pd.isna(loss.iloc[-1]):
            return 100.0 if gain.iloc[-1] > 0 else 50.0
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0
    except Exception:
        return 50.0

def calculate_macd(df: pd.DataFrame) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """MACD индикатор"""
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
    """Расчёт торговых уровней (с защитой от деления на ноль)"""
    # Базовая защита
    if price <= 0:
        price = 100
    if atr <= 0:
        atr = price * 0.01  # 1% от цены как fallback
    
    vol_mult = {'low': 0.8, 'medium': 1.0, 'high': 1.2}.get(volatility, 1.0)
    
    try:
        if direction == 'long':
            stop_distance = atr * CONFIG['STOP_LOSS_ATR_MULTIPLIER'] * vol_mult
            stop_loss = max(price - stop_distance, support * 0.995) if support > 0 else price - stop_distance
            risk = price - stop_loss
            if risk <= 0 or risk < price * 0.001:
                risk = price * 0.02  # Минимум 2% риска
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
    """Расчёт размера позиции"""
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
    """Определение направления сделки"""
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

# ==========================================
# 📰 NLP-АНАЛИЗ
# ==========================================
POSITIVE_WORDS = {'рост', 'повышен', 'увелич', 'прибыл', 'доход', 'дивиденд', 'покуп', 'оптимизм',
    'успех', 'рекорд', 'превыш', 'прогноз', 'позитив', 'поддерж', 'развит', 'инвест',
    'сделк', 'партнер', 'экспорт', 'спрос', 'дефицит', 'подорожан', 'укрепл'}

NEGATIVE_WORDS = {'пад', 'снижен', 'убыт', 'потерь', 'рис', 'опас', 'негатив', 'проблем',
    'криз', 'санкц', 'огранич', 'запрет', 'штраф', 'суд', 'расслед', 'отказ',
    'задерж', 'авар', 'пожар', 'конфликт', 'войн', 'эскал', 'инфляц', 'рецесс',
    'девальв', 'обвал', 'паник', 'распродаж', 'давлен', 'сниж', 'коррекц'}

def analyze_news_sentiment(title, description=''):
    """Анализ тональности новости"""
    try:
        text = (title + ' ' + description).lower()
        pos_count = sum(1 for w in POSITIVE_WORDS if w in text)
        neg_count = sum(1 for w in NEGATIVE_WORDS if w in text)
        total = pos_count + neg_count
        sentiment = (pos_count - neg_count) / max(total, 1)
        
        found_tickers, found_keywords, sector = [], [], 'general'
        for ticker, info in CONFIG['ASSETS'].items():
            for kw in info.get('keywords', []):
                if kw in text:
                    found_tickers.append(ticker)
                    found_keywords.append(kw)
                    if info.get('sector') != 'general':
                        sector = info['sector']
                    break
        
        return round(sentiment, 2), found_tickers, sector, found_keywords
    except Exception as e:
        logger.error(f"Ошибка анализа новости: {e}")
        return 0.0, [], 'general', []

def calculate_forecast_score(signal_data, news_sentiment, historical_data):
    """Расчёт прогнозного скора"""
    try:
        score = 50.0
        price_change = signal_data.get('change_pct', 0)
        price_momentum = min(abs(price_change) * 10, 20)
        score += price_momentum if price_change > 0 else -price_momentum
        
        volume = signal_data.get('volume', 0)
        avg_volume = signal_data.get('avg_volume', 1)
        if avg_volume > 0:
            volume_factor = min((volume / avg_volume - 1) * 15, 25)
            score += volume_factor if price_change > 0 else -volume_factor
        
        rsi = signal_data.get('rsi', 50)
        if rsi < CONFIG['RSI_OVERSOLD']:
            score += 15
        elif rsi > CONFIG['RSI_OVERBOUGHT']:
            score -= 15
        
        score += (news_sentiment or 0) * 20
        
        ticker = signal_data.get('ticker')
        if ticker and historical_data:
            ticker_history = [s for s in historical_data if s.get('ticker') == ticker]
            if len(ticker_history) >= 5:
                success_count = sum(1 for s in ticker_history[-10:] if s.get('change_pct', 0) > 0)
                success_rate = success_count / len(ticker_history[-10:])
                score += (success_rate - 0.5) * 20
        
        return max(0, min(100, round(score)))
    except Exception as e:
        logger.error(f"Ошибка прогноза: {e}")
        return 50

# ==========================================
# 🤖 АВТОРАЗМЕТКА
# ==========================================
def auto_label_signals():
    """Автоматическая проверка сигналов"""
    unchecked = execute_db_query(
        'SELECT * FROM signals WHERE checked = 0 AND trade_direction != "neutral" ORDER BY timestamp ASC LIMIT 10',
        fetch=True)
    if not unchecked:
        return
    
    columns = ['id', 'timestamp', 'ticker', 'name', 'type', 'sector', 'price', 'change_pct',
               'volume', 'avg_volume', 'rsi', 'atr', 'strength', 'news_sentiment', 'forecast_score',
               'entry_price', 'stop_loss', 'take_profit_1', 'take_profit_2', 'take_profit_3',
               'risk_reward', 'position_size', 'trade_direction', 'support_level', 'resistance_level',
               'outcome', 'pnl_pct', 'max_price', 'min_price', 'hours_elapsed', 'checked', 'exit_reason']
    
    now = datetime.now(CONFIG['MSK_TZ'])
    
    for row in unchecked:
        if len(row) < len(columns):
            continue
        signal = dict(zip(columns, row))
        try:
            try:
                signal_time = datetime.fromisoformat(signal['timestamp'])
                if signal_time.tzinfo is None:
                    signal_time = CONFIG['MSK_TZ'].localize(signal_time)
            except (ValueError, TypeError):
                continue
            
            hours_elapsed = (now - signal_time).total_seconds() / 3600
            if hours_elapsed < CONFIG['AUTO_LABEL_HOURS']:
                continue
            
            df = fetch_moex_data_raw(signal['ticker'], signal['type'])
            if df is None or len(df) < 5:
                continue
            
            df['time'] = pd.to_datetime(df['begin'])
            try:
                df['time'] = df['time'].dt.tz_localize(CONFIG['MSK_TZ'])
            except Exception:
                pass
            
            df_after = df[df['time'] > signal_time]
            if len(df_after) == 0:
                df_after = df.tail(20)
            
            entry_price = signal.get('entry_price') or signal['price']
            stop_loss = signal.get('stop_loss') or 0
            tp1 = signal.get('take_profit_1') or 0
            tp2 = signal.get('take_profit_2') or 0
            tp3 = signal.get('take_profit_3') or 0
            direction = signal.get('trade_direction', 'neutral')
            
            if entry_price <= 0:
                continue
            
            max_price = df_after['high'].max()
            min_price = df_after['low'].min()
            final_price = df_after['close'].iloc[-1]
            
            outcome, exit_reason, pnl_pct = 'neutral', '', 0.0
            
            if direction == 'long':
                if stop_loss > 0 and min_price <= stop_loss:
                    outcome, exit_reason = 'loss', 'stop_loss'
                    pnl_pct = (stop_loss - entry_price) / entry_price * 100
                elif tp3 > 0 and max_price >= tp3:
                    outcome, exit_reason = 'win', 'target_3'
                    pnl_pct = (tp3 - entry_price) / entry_price * 100
                elif tp2 > 0 and max_price >= tp2:
                    outcome, exit_reason = 'win', 'target_2'
                    pnl_pct = (tp2 - entry_price) / entry_price * 100
                elif tp1 > 0 and max_price >= tp1:
                    outcome, exit_reason = 'win', 'target_1'
                    pnl_pct = (tp1 - entry_price) / entry_price * 100
                else:
                    pnl_pct = (final_price - entry_price) / entry_price * 100
                    if pnl_pct > 1.0:
                        outcome, exit_reason = 'partial_win', 'in_profit'
                    elif pnl_pct < -1.0:
                        outcome, exit_reason = 'partial_loss', 'in_loss'
                    else:
                        outcome, exit_reason = 'neutral', 'sideways'
            elif direction == 'short':
                if stop_loss > 0 and max_price >= stop_loss:
                    outcome, exit_reason = 'loss', 'stop_loss'
                    pnl_pct = (entry_price - stop_loss) / entry_price * 100
                elif tp3 > 0 and min_price <= tp3:
                    outcome, exit_reason = 'win', 'target_3'
                    pnl_pct = (entry_price - tp3) / entry_price * 100
                elif tp2 > 0 and min_price <= tp2:
                    outcome, exit_reason = 'win', 'target_2'
                    pnl_pct = (entry_price - tp2) / entry_price * 100
                elif tp1 > 0 and min_price <= tp1:
                    outcome, exit_reason = 'win', 'target_1'
                    pnl_pct = (entry_price - tp1) / entry_price * 100
                else:
                    pnl_pct = (entry_price - final_price) / entry_price * 100
                    if pnl_pct > 1.0:
                        outcome, exit_reason = 'partial_win', 'in_profit'
                    elif pnl_pct < -1.0:
                        outcome, exit_reason = 'partial_loss', 'in_loss'
                    else:
                        outcome, exit_reason = 'neutral', 'sideways'
            
            execute_db_query(
                '''UPDATE signals SET outcome=?, pnl_pct=?, max_price=?, min_price=?,
                   hours_elapsed=?, checked=1, exit_reason=? WHERE id=?''',
                (outcome, round(pnl_pct, 2), float(max_price), float(min_price),
                 round(hours_elapsed, 1), exit_reason, signal['id']))
            logger.info(f"✅ Размечен {signal['ticker']}: {outcome} ({pnl_pct:+.2f}%)")
            time.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка разметки {signal.get('ticker', '?')}: {e}")
            continue

# ==========================================
# 🤖 ФОНОВЫЙ МОНИТОРИНГ
# ==========================================
def background_monitor():
    """Основной фоновый процесс"""
    init_db()
    alerted_candles = {}
    last_label_check = 0
    last_news_check = 0
    
    while True:
        try:
            current_time = time.time()
            
            # Авторазметка каждые 10 минут
            if current_time - last_label_check > 600:
                try:
                    auto_label_signals()
                    last_label_check = current_time
                except Exception as e:
                    logger.error(f"Ошибка авторазметки: {e}")
            
            # Парсинг новостей каждые 5 минут
            if current_time - last_news_check > 300:
                try:
                    feed = feedparser.parse(CONFIG['NEWS_FEED_URL'], request_headers=HEADERS)
                    if hasattr(feed, 'entries') and feed.entries:
                        saved_count = 0
                        for entry in feed.entries[:10]:
                            title = entry.get('title', '')
                            desc = entry.get('summary', '')
                            url = entry.get('link', '')
                            sentiment, tickers, sector, keywords = analyze_news_sentiment(title, desc)
                            macro_words = ['цб', 'ставк', 'нефть', 'доллар', 'рубль', 'санкц', 'инфляц']
                            is_macro = any(w in (title + ' ' + desc).lower() for w in macro_words)
                            if tickers or (is_macro and abs(sentiment) > 0.1):
                                execute_db_query(
                                    '''INSERT INTO news_analysis (timestamp, title, url, sentiment_score,
                                       related_tickers, sector_impact, keywords_found) VALUES (?, ?, ?, ?, ?, ?, ?)''',
                                    (datetime.now(CONFIG['MSK_TZ']).isoformat(), title, url, sentiment,
                                     ','.join(tickers), sector, ','.join(keywords)))
                                saved_count += 1
                        last_news_check = current_time
                        logger.info(f"📰 Новости: {saved_count}")
                except Exception as e:
                    logger.error(f"Ошибка новостей: {e}")
            
            # Торговый мониторинг
            now = datetime.now(CONFIG['MSK_TZ'])
            is_open = now.weekday() < 5 and 10 <= now.hour < 24
            
            if is_open:
                for ticker, info in CONFIG['ASSETS'].items():
                    try:
                        df = fetch_moex_data_raw(ticker, info['type'])
                        if df is None or len(df) < 5:
                            continue
                        
                        current_volume = df['volume'].iloc[-1]
                        current_close = df['close'].iloc[-1]
                        prev_close = df['close'].iloc[-2]
                        candle_time = df['begin'].iloc[-1]
                        
                        if alerted_candles.get(ticker) == candle_time:
                            continue
                        
                        if prev_close <= 0:
                            continue
                        
                        avg_volume = df['volume'].iloc[:-1].mean()
                        price_change_pct = ((current_close - prev_close) / prev_close) * 100
                        
                        if avg_volume > 0 and current_volume > avg_volume * CONFIG['VOLUME_MULTIPLIER'] and abs(price_change_pct) >= CONFIG['PRICE_CHANGE_THRESHOLD']:
                            rsi = calculate_rsi(df)
                            atr = calculate_atr(df)
                            support, resistance = find_support_resistance(df)
                            strength = 'strong' if abs(price_change_pct) > 3.0 or rsi < CONFIG['RSI_OVERSOLD'] or rsi > CONFIG['RSI_OVERBOUGHT'] else 'medium'
                            
                            recent_news = execute_db_query('SELECT sentiment_score, related_tickers FROM news_analysis ORDER BY timestamp DESC LIMIT 5', fetch=True) or []
                            ticker_sent, news_count = 0.0, 0
                            for row in recent_news:
                                if row and len(row) >= 2 and ticker in (row[1] or ''):
                                    ticker_sent += (row[0] or 0)
                                    news_count += 1
                            ticker_sent = ticker_sent / max(news_count, 1)
                            
                            hist_rows = execute_db_query('SELECT ticker, change_pct FROM signals ORDER BY timestamp DESC LIMIT 50', fetch=True) or []
                            historical = [{'ticker': r[0], 'change_pct': r[1]} for r in hist_rows if r and len(r) >= 2]
                            
                            forecast = calculate_forecast_score(
                                {'ticker': ticker, 'change_pct': price_change_pct, 'volume': current_volume,
                                 'avg_volume': avg_volume, 'rsi': rsi}, ticker_sent, historical)
                            
                            direction = determine_trade_direction(rsi, price_change_pct, ticker_sent, support, resistance, current_close)
                            trade_levels = calculate_trade_levels(current_close, direction, atr, support, resistance, info.get('volatility', 'medium'))
                            position_size = calculate_position_size(100000, CONFIG['RISK_PER_TRADE'], trade_levels['entry'], trade_levels['stop_loss'])
                            
                            timestamp = datetime.now(CONFIG['MSK_TZ']).isoformat()
                            execute_db_query(
                                '''INSERT INTO signals (timestamp, ticker, name, asset_type, sector, price, change_pct,
                                   volume, avg_volume, rsi, atr, signal_strength, news_sentiment, forecast_score,
                                   entry_price, stop_loss, take_profit_1, take_profit_2, take_profit_3,
                                   risk_reward, position_size, trade_direction, support_level, resistance_level)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                (timestamp, ticker, info['name'], info['type'], info.get('sector', 'unknown'),
                                 float(current_close), float(price_change_pct), float(current_volume),
                                 float(avg_volume), rsi, atr, strength, ticker_sent, forecast,
                                 trade_levels['entry'], trade_levels['stop_loss'],
                                 trade_levels['tp1'], trade_levels['tp2'], trade_levels['tp3'],
                                 trade_levels['risk_reward'], position_size, direction, support, resistance))
                            
                            if direction != 'neutral' and trade_levels['risk_reward'] >= CONFIG['MIN_RISK_REWARD']:
                                execute_db_query(
                                    '''INSERT INTO trade_ideas (timestamp, ticker, name, direction, entry_price,
                                       stop_loss, take_profit_1, take_profit_2, take_profit_3, risk_reward,
                                       position_size, confidence, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                    (timestamp, ticker, info['name'], direction, trade_levels['entry'],
                                     trade_levels['stop_loss'], trade_levels['tp1'], trade_levels['tp2'],
                                     trade_levels['tp3'], trade_levels['risk_reward'], position_size, forecast, 'active'))
                                logger.info(f"💡 Идея: {ticker} {direction} | R:R={trade_levels['risk_reward']:.2f}")
                            
                            alerted_candles[ticker] = candle_time
                            logger.info(f"🎯 Сигнал: {ticker} {price_change_pct:+.2f}%")
                    except Exception as e:
                        logger.error(f"Ошибка мониторинга {ticker}: {e}")
                        continue
                    
                    time.sleep(1)
                time.sleep(15)
            else:
                time.sleep(60)
        except Exception as e:
            logger.error(f"Критическая ошибка фона: {e}")
            time.sleep(30)

# ==========================================
# 🎨 ПРОФЕССИОНАЛЬНЫЕ ГРАФИКИ
# ==========================================
def generate_candlestick_chart(df, ticker, name, trade_levels=None):
    """Профессиональный свечной график с уровнями"""
    try:
        df_plot = df.copy()
        df_plot['begin'] = pd.to_datetime(df_plot['begin'])
        df_plot = df_plot.set_index('begin')
        df_plot = df_plot.rename(columns={
            'open': 'Open', 'high': 'High', 'low': 'Low',
            'close': 'Close', 'volume': 'Volume'
        })
        df_plot = df_plot.tail(50)
        
        mc = mpf.make_marketcolors(
            up='#26a69a', down='#ef5350',
            edge='inherit', wick='inherit', volume='in'
        )
        s = mpf.make_mpf_style(
            marketcolors=mc,
            base_mpf_style='nightclouds',
            gridstyle='-', gridcolor='#2a2a2a',
            facecolor='#0e1117', edgecolor='#0e1117',
            figcolor='#0e1117'
        )
        
        # Горизонтальные линии
        hlines_config = None
        add_plots = []
        
        if trade_levels and trade_levels.get('risk_reward', 0) > 0:
            entry = trade_levels.get('entry', 0)
            stop = trade_levels.get('stop_loss', 0)
            tp1 = trade_levels.get('tp1', 0)
            tp2 = trade_levels.get('tp2', 0)
            tp3 = trade_levels.get('tp3', 0)
            
            # Проверяем, что все уровни положительные
            if all(v > 0 for v in [entry, stop, tp1, tp2, tp3]):
                hlines_config = {
                    'hlines': [entry, stop, tp1, tp2, tp3],
                    'colors': ['#00ffcc', '#ff4444', '#ffaa00', '#00ff00', '#00ffff'],
                    'linestyle': ['-', '--', '-', '-', '-'],
                    'linewidths': [1.5, 1.5, 1, 1, 1]
                }
        
        # SMA 20
        if len(df_plot) >= 20:
            sma20 = df_plot['Close'].rolling(window=20).mean()
            add_plots.append(mpf.make_addplot(sma20, color='#ffaa00', width=1, linestyle='--'))
        
        fig, axes = mpf.plot(
            df_plot,
            type='candle',
            style=s,
            volume=True,
            figsize=(12, 6),
            returnfig=True,
            hlines=hlines_config,
            addplot=add_plots if add_plots else None,
            tight_layout=True
        )
        
        axes[0].set_title(f'{name} ({ticker}) - 10min', color='white', fontsize=14, pad=10)
        
        # Легенда уровней
        if hlines_config and trade_levels:
            legend_elements = [
                Line2D([0], [0], color='#00ffcc', linewidth=2, label=f'Entry: {trade_levels["entry"]:.2f}'),
                Line2D([0], [0], color='#ff4444', linewidth=2, linestyle='--', label=f'Stop: {trade_levels["stop_loss"]:.2f}'),
                Line2D([0], [0], color='#ffaa00', linewidth=1.5, label=f'TP1: {trade_levels["tp1"]:.2f}'),
                Line2D([0], [0], color='#00ff00', linewidth=1.5, label=f'TP2: {trade_levels["tp2"]:.2f}'),
                Line2D([0], [0], color='#00ffff', linewidth=1.5, label=f'TP3: {trade_levels["tp3"]:.2f}')
            ]
            axes[0].legend(handles=legend_elements, loc='upper left',
                          fontsize=8, facecolor='#262730',
                          edgecolor='#262730', labelcolor='white')
        
        return fig
    except Exception as e:
        logger.error(f"Ошибка графика {ticker}: {e}")
        return generate_simple_chart(df, ticker, name)

def generate_simple_chart(df, ticker, name):
    """Fallback простой график"""
    try:
        with plt.style.context('dark_background'):
            fig, ax = plt.subplots(figsize=(12, 5))
            fig.patch.set_facecolor('#0e1117')
            ax.set_facecolor('#0e1117')
            ax.plot(range(len(df)), df['close'], color='#00ffcc', linewidth=2)
            ax.set_title(f'{name} ({ticker})', color='white', fontsize=14)
            ax.grid(True, alpha=0.2)
            plt.tight_layout()
            return fig
    except Exception:
        # Последний fallback - пустая фигура
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.text(0.5, 0.5, 'Ошибка графика', ha='center', va='center')
        return fig

# ==========================================
# 🔥 HEATMAP КОРРЕЛЯЦИЙ
# ==========================================
def render_heatmap_correlation():
    """Тепловая карта корреляций"""
    st.subheader("🔥 Корреляция доходностей активов")
    st.caption("Как активы движутся относительно друг друга")
    
    with st.spinner("Загрузка данных..."):
        prices_data = {}
        for ticker, info in CONFIG['ASSETS'].items():
            df = fetch_moex_data_raw(ticker, info['type'])
            if df is not None and len(df) > 20:
                try:
                    returns = df['close'].pct_change().dropna()
                    if len(returns) > 10:
                        prices_data[ticker] = returns
                except Exception:
                    continue
        
        if len(prices_data) < 3:
            st.warning("⚠️ Недостаточно данных (нужно минимум 3 актива)")
            return
        
        returns_df = pd.DataFrame(prices_data)
        corr_matrix = returns_df.corr()
    
    with plt.style.context('dark_background'):
        fig, ax = plt.subplots(figsize=(10, 8))
        fig.patch.set_facecolor('#0e1117')
        ax.set_facecolor('#0e1117')
        
        im = ax.imshow(corr_matrix.values, cmap='RdYlGn', aspect='auto', vmin=-1, vmax=1)
        
        ax.set_xticks(range(len(corr_matrix.columns)))
        ax.set_yticks(range(len(corr_matrix.columns)))
        ax.set_xticklabels(corr_matrix.columns, rotation=45, ha='right', color='white')
        ax.set_yticklabels(corr_matrix.columns, color='white')
        
        for i in range(len(corr_matrix)):
            for j in range(len(corr_matrix)):
                val = corr_matrix.values[i, j]
                color = 'white' if abs(val) < 0.5 else 'black'
                ax.text(j, i, f'{val:.2f}', ha="center", va="center",
                       color=color, fontsize=9, fontweight='bold')
        
        plt.colorbar(im, label='Корреляция', ax=ax)
        ax.set_title('Корреляция доходностей', color='white', fontsize=14, pad=20)
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)
    
    st.markdown("### 📖 Как читать")
    c1, c2, c3 = st.columns(3)
    with c1: st.success("🟢 **Зелёный (>0.5)**\nДвижутся вместе")
    with c2: st.error("🔴 **Красный (<-0.3)**\nПротивоположно")
    with c3: st.info("⚪ **Белый (~0)**\nНет связи")
    
    # Топ связей
    pairs = []
    for i in range(len(corr_matrix)):
        for j in range(i+1, len(corr_matrix)):
            pairs.append({
                'pair': f"{corr_matrix.columns[i]} ↔ {corr_matrix.columns[j]}",
                'correlation': corr_matrix.values[i, j]
            })
    pairs.sort(key=lambda x: abs(x['correlation']), reverse=True)
    
    st.markdown("### 🔗 Топ связи")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🟢 Сильнейшая положительная:**")
        for p in pairs[:3]:
            if p['correlation'] > 0:
                st.markdown(f"- `{p['pair']}`: **{p['correlation']:+.2f}**")
    with c2:
        st.markdown("**🔴 Сильнейшая отрицательная:**")
        for p in pairs[-3:]:
            if p['correlation'] < 0:
                st.markdown(f"- `{p['pair']}`: **{p['correlation']:+.2f}**")
    
    st.info("💡 Для диверсификации выбирайте активы с низкой корреляцией (< 0.3)")

# ==========================================
# ⭐ ДАШБОРД ЛУЧШИХ ИДЕЙ
# ==========================================
def render_best_ideas_dashboard():
    """Топ сигналов по разным критериям"""
    st.subheader("⭐ Лучшие торговые идеи")
    st.caption("Автоматический отбор топ-сигналов")
    
    signals_rows = execute_db_query(
        'SELECT * FROM signals WHERE trade_direction != "neutral" ORDER BY timestamp DESC LIMIT 50',
        fetch=True) or []
    
    if not signals_rows:
        st.info("🔍 Пока нет торговых идей. Радар продолжает мониторинг...")
        return
    
    sig_cols = ['id', 'timestamp', 'ticker', 'name', 'type', 'sector', 'price', 'change_pct',
              'volume', 'avg_volume', 'rsi', 'atr', 'strength', 'news_sentiment', 'forecast_score',
              'entry_price', 'stop_loss', 'take_profit_1', 'take_profit_2', 'take_profit_3',
              'risk_reward', 'position_size', 'trade_direction', 'support_level', 'resistance_level',
              'outcome', 'pnl_pct', 'max_price', 'min_price', 'hours_elapsed', 'checked', 'exit_reason']
    
    signals = []
    for r in signals_rows:
        if len(r) >= len(sig_cols):
            signals.append(dict(zip(sig_cols, r)))
    
    if not signals:
        st.info("🔍 Нет данных для отображения")
        return
    
    # === ТОП-3 ПО ПРОГНОЗУ ===
    st.markdown("### 🎯 Топ-3 по вероятности успеха")
    top_forecast = sorted(signals, key=lambda x: x.get('forecast_score', 0) or 0, reverse=True)[:3]
    cols = st.columns(3)
    for i, sig in enumerate(top_forecast):
        with cols[i]:
            emoji = "📈" if sig.get('trade_direction') == 'long' else "📉"
            css = "trade-long" if sig.get('trade_direction') == 'long' else "trade-short"
            with st.container():
                st.markdown(f'<div class="{css}">', unsafe_allow_html=True)
                st.markdown(f"#### {emoji} {sig.get('name', '')}")
                forecast = sig.get('forecast_score', 0) or 0
                st.metric("🎯 Прогноз", f"{forecast:.0f}%")
                rr = sig.get('risk_reward', 0) or 0
                st.metric("R:R", f"1:{rr:.1f}" if rr > 0 else "N/A")
                rsi = sig.get('rsi', 50) or 50
                st.metric("RSI", f"{rsi:.1f}")
                change = sig.get('change_pct', 0) or 0
                st.caption(f"{change:+.2f}% | **{sig.get('trade_direction', '').upper()}** | {sig.get('sector', '')}")
                st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("---")
    
    # === ТОП-3 ПО RISK/REWARD ===
    st.markdown("### 💰 Топ-3 по Risk/Reward")
    valid_rr = [s for s in signals if (s.get('risk_reward', 0) or 0) > 0]
    top_rr = sorted(valid_rr, key=lambda x: x.get('risk_reward', 0), reverse=True)[:3]
    
    if top_rr:
        cols = st.columns(3)
        for i, sig in enumerate(top_rr):
            with cols[i]:
                emoji = "📈" if sig.get('trade_direction') == 'long' else "📉"
                st.markdown(f"#### {emoji} {sig.get('name', '')}")
                rr = sig.get('risk_reward', 0) or 0
                st.metric("💎 R:R", f"1:{rr:.1f}")
                c1, c2 = st.columns(2)
                entry = sig.get('entry_price', 0) or 0
                stop = sig.get('stop_loss', 0) or 0
                with c1: st.markdown(f"**Вход:** {entry:.2f}")
                with c2: st.markdown(f"**Стоп:** <span style='color:#ff4444;'>{stop:.2f}</span>", unsafe_allow_html=True)
                tp1 = sig.get('take_profit_1', 0) or 0
                tp2 = sig.get('take_profit_2', 0) or 0
                tp3 = sig.get('take_profit_3', 0) or 0
                st.caption(f"Цели: {tp1:.2f} → {tp2:.2f} → {tp3:.2f}")
    else:
        st.info("Пока нет сигналов с хорошим R:R")
    
    st.markdown("---")
    
    # === ТОП-3 ПО СИЛЕ СИГНАЛА ===
    st.markdown("### 💪 Топ-3 по силе импульса")
    
    def sort_key_strength(s):
        strength_score = 1 if s.get('strength') == 'strong' else 0
        change = abs(s.get('change_pct', 0) or 0)
        avg_vol = s.get('avg_volume', 1) or 1
        vol_ratio = (s.get('volume', 0) or 0) / avg_vol
        return (strength_score, change, vol_ratio)
    
    top_strength = sorted(signals, key=sort_key_strength, reverse=True)[:3]
    
    cols = st.columns(3)
    for i, sig in enumerate(top_strength):
        with cols[i]:
            emoji = "📈" if sig.get('trade_direction') == 'long' else "📉"
            st.markdown(f"#### {emoji} {sig.get('name', '')}")
            change = sig.get('change_pct', 0) or 0
            st.metric("⚡ Импульс", f"{change:+.2f}%")
            avg_vol = sig.get('avg_volume', 1) or 1
            vol = sig.get('volume', 0) or 0
            vol_ratio = vol / avg_vol if avg_vol > 0 else 0
            st.metric("📊 Объём", f"x{vol_ratio:.1f}")
            strength = sig.get('strength', 'medium')
            strength_label = "💥 СИЛЬНЫЙ" if strength == 'strong' else "⚖️ Средний"
            sent = sig.get('news_sentiment', 0) or 0
            st.caption(f"{strength_label} | Сентимент: {sent:+.2f}")
    
    st.markdown("---")
    
    # === СВОДНАЯ ТАБЛИЦА ===
    st.markdown("### 📋 Все активные идеи")
    table_data = []
    for sig in signals[:20]:
        emoji = "📈" if sig.get('trade_direction') == 'long' else "📉"
        timestamp = sig.get('timestamp', '')
        time_str = timestamp[11:16] if len(timestamp) > 16 else ''
        forecast = sig.get('forecast_score', 0) or 0
        rr = sig.get('risk_reward', 0) or 0
        entry = sig.get('entry_price', 0) or 0
        stop = sig.get('stop_loss', 0) or 0
        rsi = sig.get('rsi', 50) or 50
        strength = '💥' if sig.get('strength') == 'strong' else '⚖️'
        
        table_data.append({
            '': emoji,
            'Актив': f"{sig.get('name', '')} ({sig.get('ticker', '')})",
            'Напр.': sig.get('trade_direction', '').upper(),
            'Прогноз': f"{forecast:.0f}%",
            'R:R': f"1:{rr:.1f}" if rr > 0 else "-",
            'Вход': f"{entry:.2f}",
            'Стоп': f"{stop:.2f}",
            'RSI': f"{rsi:.0f}",
            'Сила': strength,
            'Время': time_str
        })
    
    if table_data:
        st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)

# ==========================================
# 📊 СРАВНЕНИЕ СЕКТОРОВ
# ==========================================
def render_sector_comparison():
    """Сравнительный график секторов"""
    st.subheader("📊 Сравнение секторов рынка")
    st.caption("Относительная сила секторов за последние 100 минут")
    
    with st.spinner("Загрузка данных..."):
        sectors = {}
        for ticker, info in CONFIG['ASSETS'].items():
            sector = info.get('sector', 'unknown')
            if sector not in sectors:
                sectors[sector] = []
            sectors[sector].append(ticker)
        
        sector_performance = {}
        sector_details = {}
        
        for sector, tickers in sectors.items():
            performances = []
            details = []
            for ticker in tickers:
                df = fetch_moex_data_raw(ticker, CONFIG['ASSETS'][ticker]['type'])
                if df is not None and len(df) > 10:
                    try:
                        prev_price = df['close'].iloc[-10]
                        curr_price = df['close'].iloc[-1]
                        if prev_price > 0:
                            price_change = (curr_price - prev_price) / prev_price * 100
                            performances.append(price_change)
                            details.append({'ticker': ticker, 'change': price_change})
                    except Exception:
                        continue
            if performances:
                sector_performance[sector] = sum(performances) / len(performances)
                sector_details[sector] = details
    
    if not sector_performance:
        st.warning("⚠️ Недостаточно данных")
        return
    
    with plt.style.context('dark_background'):
        fig, ax = plt.subplots(figsize=(10, 6))
        fig.patch.set_facecolor('#0e1117')
        ax.set_facecolor('#0e1117')
        
        sectors_list = list(sector_performance.keys())
        performance_list = list(sector_performance.values())
        colors = ['#26a69a' if p >= 0 else '#ef5350' for p in performance_list]
        
        bars = ax.barh(sectors_list, performance_list, color=colors, alpha=0.8, edgecolor='none')
        
        # Безопасные границы
        max_abs = max(abs(p) for p in performance_list) if performance_list else 1
        max_abs = max(max_abs, 0.1)  # Минимум 0.1 для избежания нулевых границ
        text_offset = max_abs * 0.15
        ax.set_xlim(-max_abs - text_offset * 2, max_abs + text_offset * 2)
        
        for bar, perf in zip(bars, performance_list):
            width = bar.get_width()
            x_pos = width + text_offset if width >= 0 else width - text_offset
            ax.text(x_pos, bar.get_y() + bar.get_height()/2,
                   f'{perf:+.2f}%',
                   ha='left' if width >= 0 else 'right',
                   va='center', color='white', fontweight='bold', fontsize=11)
        
        ax.axvline(x=0, color='white', linestyle='-', linewidth=1, alpha=0.5)
        ax.set_xlabel('Доходность (%)', color='white', fontsize=11)
        ax.set_title('Сила секторов (последние 100 минут)',
                    color='white', fontsize=14, pad=20)
        ax.tick_params(colors='white', labelsize=11)
        for spine in ['bottom', 'left']:
            ax.spines[spine].set_color('white')
        for spine in ['top', 'right']:
            ax.spines[spine].set_visible(False)
        ax.grid(True, axis='x', alpha=0.2, color='white')
        
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)
    
    best_sector = max(sector_performance.items(), key=lambda x: x[1])
    worst_sector = min(sector_performance.items(), key=lambda x: x[1])
    
    st.markdown("### 💡 Анализ")
    c1, c2 = st.columns(2)
    with c1:
        st.success(f"🏆 **Сильнейший:** {best_sector[0]}\n\n{best_sector[1]:+.2f}%")
        if best_sector[0] in sector_details:
            for d in sector_details[best_sector[0]]:
                emoji = "🚀" if d['change'] > 0 else "🩸"
                st.caption(f"{emoji} `{d['ticker']}`: {d['change']:+.2f}%")
    with c2:
        st.error(f"📉 **Слабейший:** {worst_sector[0]}\n\n{worst_sector[1]:+.2f}%")
        if worst_sector[0] in sector_details:
            for d in sector_details[worst_sector[0]]:
                emoji = "🚀" if d['change'] > 0 else "🩸"
                st.caption(f"{emoji} `{d['ticker']}`: {d['change']:+.2f}%")
    
    st.markdown("### 🎯 Рекомендации")
    if best_sector[1] > 1.0:
        st.success(f"✅ Сектор **{best_sector[0]}** показывает силу — рассмотрите лонг")
    if worst_sector[1] < -1.0:
        st.warning(f"⚠️ Сектор **{worst_sector[0]}** под давлением — осторожнее с лонгами")
    
    with st.expander("📋 Детальная статистика"):
        all_data = []
        for sector, details in sector_details.items():
            for d in details:
                all_data.append({
                    'Сектор': sector,
                    'Тикер': d['ticker'],
                    'Изм. %': f"{d['change']:+.2f}%"
                })
        if all_data:
            df_table = pd.DataFrame(all_data)
            try:
                df_table['sort_key'] = df_table['Изм. %'].str.replace('%', '').str.replace('+', '').astype(float)
                df_table = df_table.sort_values('sort_key', ascending=False).drop('sort_key', axis=1)
            except Exception:
                pass
            st.dataframe(df_table, use_container_width=True, hide_index=True)

# ==========================================
# 📈 ВКЛАДКА КОТИРОВОК
# ==========================================
@st.cache_data(ttl=60)
def get_all_assets_data():
    """Получение данных по всем активам с кэшированием"""
    assets = []
    for ticker, info in CONFIG['ASSETS'].items():
        df = get_moex_data(ticker, info['type'])  # Используем кэшированную версию
        if df is not None and len(df) > 0:
            try:
                current = df['close'].iloc[-1]
                prev = df['close'].iloc[-2] if len(df) > 1 else current
                change = ((current - prev) / prev) * 100 if prev > 0 else 0
                assets.append({
                    'ticker': ticker, 'name': info['name'], 'type': info['type'],
                    'sector': info.get('sector', 'unknown'), 'price': current,
                    'change_pct': change, 'volume': df['volume'].iloc[-1], 'df': df
                })
            except Exception as e:
                logger.error(f"Ошибка обработки {ticker}: {e}")
                continue
    return assets

def get_latest_trade_levels(ticker):
    """Получить последние торговые уровни (безопасная версия)"""
    try:
        row = execute_db_query(
            'SELECT entry_price, stop_loss, take_profit_1, take_profit_2, take_profit_3, risk_reward FROM signals WHERE ticker=? ORDER BY timestamp DESC LIMIT 1',
            (ticker,),
            fetch=True
        )
        if row and row[0] and row[0][0] is not None:
            return {
                'entry': row[0][0] or 0,
                'stop_loss': row[0][1] or 0,
                'tp1': row[0][2] or 0,
                'tp2': row[0][3] or 0,
                'tp3': row[0][4] or 0,
                'risk_reward': row[0][5] or 0
            }
    except Exception as e:
        logger.error(f"Ошибка получения уровней {ticker}: {e}")
    return None

def render_quotes_tab():
    """Вкладка с котировками и графиками"""
    st.subheader("📈 Котировки и графики")
    
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        show_type = st.selectbox("Показать", ["Все", "Только акции", "Только фьючерсы"], key="qt_type")
    with c2:
        sort_by = st.selectbox("Сортировка", ["По имени", "По изменению %", "По объему"], key="qt_sort")
    with c3:
        if st.button("🔄 Обновить", key="refresh_quotes"):
            st.cache_data.clear()
            st.rerun()
    
    st.markdown("---")
    
    with st.spinner("Загрузка..."):
        assets = get_all_assets_data()
    
    if show_type == "Только акции":
        assets = [a for a in assets if a['type'] == 'stock']
    elif show_type == "Только фьючерсы":
        assets = [a for a in assets if a['type'] == 'futures']
    
    if sort_by == "По изменению %":
        assets.sort(key=lambda x: x.get('change_pct', 0), reverse=True)
    elif sort_by == "По объему":
        assets.sort(key=lambda x: x.get('volume', 0), reverse=True)
    else:
        assets.sort(key=lambda x: x.get('name', ''))
    
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.metric("Активов", len(assets))
    with c2: st.metric("Растущих", f"{len([a for a in assets if a.get('change_pct', 0) > 0])} 🚀")
    with c3: st.metric("Падающих", f"{len([a for a in assets if a.get('change_pct', 0) < 0])} 🩸")
    with c4:
        avg = sum(a.get('change_pct', 0) for a in assets) / max(len(assets), 1)
        color = "green" if avg >= 0 else "red"
        st.markdown(f"**Среднее:** <span style='color:{color}; font-size:20px;'>{avg:+.2f}%</span>", unsafe_allow_html=True)
    
    st.markdown("---")
    
    stocks = [a for a in assets if a['type'] == 'stock']
    futures = [a for a in assets if a['type'] == 'futures']
    
    def render_asset_block(asset_list, title):
        if not asset_list:
            return
        st.markdown(f"### {title}")
        for asset in asset_list:
            with st.container():
                c1, c2, c3 = st.columns([1, 2, 1])
                with c1:
                    change = asset.get('change_pct', 0)
                    emoji = "🚀" if change > 0 else "🩸" if change < 0 else "⚖️"
                    st.markdown(f"## {emoji} {asset.get('name', '')}")
                    st.markdown(f"**{asset.get('ticker', '')}** | {asset.get('sector', '')}")
                    color = "green" if change >= 0 else "red"
                    st.markdown(f"<span style='color:{color}; font-size:28px; font-weight:bold;'>{asset.get('price', 0):.2f}</span>", unsafe_allow_html=True)
                    st.markdown(f"<span style='color:{color}; font-size:20px;'>{change:+.2f}%</span>", unsafe_allow_html=True)
                    st.markdown(f"**Объем:** {asset.get('volume', 0):,.0f}")
                
                with c2:
                    try:
                        trade_levels = get_latest_trade_levels(asset.get('ticker', ''))
                        fig = generate_candlestick_chart(asset.get('df'), asset.get('ticker', ''), asset.get('name', ''), trade_levels)
                        st.pyplot(fig)
                        plt.close(fig)
                    except Exception as e:
                        st.error(f"Ошибка графика: {e}")
                
                with c3:
                    df = asset.get('df')
                    if df is not None:
                        rsi = calculate_rsi(df)
                        atr = calculate_atr(df)
                        macd_line, signal_line, hist = calculate_macd(df)
                        
                        if rsi < CONFIG['RSI_OVERSOLD']:
                            st.success(f"📉 **RSI: {rsi:.1f}**\nПерепроданность")
                        elif rsi > CONFIG['RSI_OVERBOUGHT']:
                            st.error(f"📈 **RSI: {rsi:.1f}**\nПерекупленность")
                        else:
                            st.info(f"⚖️ **RSI: {rsi:.1f}**")
                        
                        st.metric("ATR", f"{atr:.2f}")
                        
                        if macd_line is not None and signal_line is not None:
                            macd_signal = "🟢 Бычий" if macd_line > signal_line else "🔴 Медвежий"
                            st.markdown(f"**MACD:** {macd_signal}")
                            st.caption(f"Line: {macd_line:.2f}\nSignal: {signal_line:.2f}")
                        
                        if len(df) >= 20:
                            r = df.tail(20)
                            st.markdown(f"**S:** {r['low'].min():.2f}")
                            st.markdown(f"**R:** {r['high'].max():.2f}")
                        
                        if trade_levels and trade_levels.get('risk_reward', 0) > 0:
                            st.markdown("---")
                            st.markdown("**🎯 Торговые уровни:**")
                            st.caption(f"Entry: {trade_levels['entry']:.2f}\nStop: {trade_levels['stop_loss']:.2f}\nTP1/2/3: {trade_levels['tp1']:.2f}/{trade_levels['tp2']:.2f}/{trade_levels['tp3']:.2f}")
                
                st.markdown("---")
    
    if show_type != "Только фьючерсы":
        render_asset_block(stocks, "🏭 Акции РФ")
    if show_type != "Только акции":
        render_asset_block(futures, "🌍 Сырье и Валюта")
    
    if not assets:
        st.warning("⚠️ Нет данных. Проверьте подключение.")

# ==========================================
# 📰 ВКЛАДКА НОВОСТЕЙ
# ==========================================
def render_news_tab():
    """Вкладка новостей с аналитикой"""
    st.subheader("📰 Новости с аналитикой")
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        news_filter = st.selectbox("Фильтр",
            ["Все новости", "Только с тикерами", "Только позитивные", "Только негативные"], key="news_filter")
    with c2:
        news_source = st.selectbox("Источник", ["РБК (свежие)", "Из базы (история)"], key="news_source")
    with c3:
        if st.button("🔄 Обновить", key="refresh_news"):
            st.cache_data.clear()
            st.rerun()
    st.markdown("---")
    news_list = []
    
    if news_source == "РБК (свежие)":
        with st.spinner("Загрузка..."):
            try:
                feed = feedparser.parse(CONFIG['NEWS_FEED_URL'], request_headers=HEADERS)
                if hasattr(feed, 'entries') and feed.entries:
                    for entry in feed.entries[:30]:
                        title = entry.get('title', '')
                        desc = entry.get('summary', entry.get('description', ''))
                        url = entry.get('link', '#')
                        published = entry.get('published', '')
                        sentiment, tickers, sector, keywords = analyze_news_sentiment(title, desc)
                        macro_keywords = ['цб', 'ставк', 'нефть', 'brent', 'золото', 'gold',
                                        'доллар', 'рубль', 'санкц', 'инфляц', 'ввп', 'бирж',
                                        'moex', 'мосбир', 'газпром', 'лукойл', 'сбер', 'яндекс',
                                        'роснефть', 'полюс', 'opec', 'фрс', 'fed']
                        is_macro = any(kw in (title + ' ' + desc).lower() for kw in macro_keywords)
                        if is_macro or tickers or abs(sentiment) > 0.2:
                            news_list.append({
                                'title': title, 'url': url, 'published': published,
                                'sentiment': sentiment, 'tickers': tickers,
                                'sector': sector, 'keywords': keywords, 'source': 'live'
                            })
                    st.success(f"✅ Загружено: {len(news_list)}")
                    st.caption(f"🕒 {datetime.now().strftime('%H:%M:%S')}")
                else:
                    st.warning("⚠️ RSS недоступен")
            except Exception as e:
                st.error(f"❌ Ошибка: {e}")
    else:
        news_rows = execute_db_query('SELECT * FROM news_analysis ORDER BY timestamp DESC LIMIT 50', fetch=True) or []
        news_cols = ['id', 'timestamp', 'title', 'url', 'sentiment', 'tickers', 'sector', 'keywords']
        for row in news_rows:
            if len(row) < len(news_cols):
                continue
            n = dict(zip(news_cols, row))
            tickers_str = n.get('tickers', '') if isinstance(n.get('tickers'), str) else ''
            keywords_str = n.get('keywords', '') if isinstance(n.get('keywords'), str) else ''
            news_list.append({
                'title': n.get('title', ''),
                'url': n.get('url', ''),
                'published': n.get('timestamp', ''),
                'sentiment': n.get('sentiment', 0) or 0,
                'tickers': tickers_str.split(',') if tickers_str else [],
                'sector': n.get('sector', 'general'),
                'keywords': keywords_str.split(',') if keywords_str else [],
                'source': 'db'
            })
        if news_list:
            st.info(f"📊 {len(news_list)} из базы")
        else:
            st.warning("⚠️ База пуста")
    
    if news_filter == "Только с тикерами":
        news_list = [n for n in news_list if n.get('tickers')]
    elif news_filter == "Только позитивные":
        news_list = [n for n in news_list if (n.get('sentiment', 0) or 0) > 0.2]
    elif news_filter == "Только негативные":
        news_list = [n for n in news_list if (n.get('sentiment', 0) or 0) < -0.2]
    
    st.markdown("---")
    if not news_list:
        st.info("📭 Нет новостей")
    else:
        c1, c2, c3, c4 = st.columns(4)
        with c1: st.metric("Всего", len(news_list))
        with c2: st.metric("🟢 Позитив", len([n for n in news_list if (n.get('sentiment', 0) or 0) > 0.2]))
        with c3: st.metric("🔴 Негатив", len([n for n in news_list if (n.get('sentiment', 0) or 0) < -0.2]))
        with c4: st.metric("🟡 Нейтрал", len(news_list) - len([n for n in news_list if abs(n.get('sentiment', 0) or 0) > 0.2]))
def render_news_tab():
    """Вкладка новостей с несколькими источниками и fallback"""
    st.subheader("📰 Новости с аналитикой")
    
    # Список источников
    NEWS_SOURCES = [
        {'name': 'Прайм', 'url': 'https://1prime.ru/export/rss2/'},
        {'name': 'Финанз.ру', 'url': 'https://www.finanz.ru/rss'},
        {'name': 'Investing.com RU', 'url': 'https://ru.investing.com/rss/news.rss'},
        {'name': 'РБК', 'url': 'https://rssexport.rbc.ru/rbcnews/news/20/full'},
        {'name': 'Ведомости', 'url': 'https://www.vedomosti.ru/rss/rubric/finance'},
    ]
    
    # Фильтры
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        news_filter = st.selectbox("Фильтр",
            ["Все новости", "Только с тикерами", "Только позитивные", "Только негативные"], 
            key="news_filter")
    with c2:
        # Выбор конкретного источника или "Авто"
        source_names = ["🤖 Авто (все источники)"] + [s['name'] for s in NEWS_SOURCES]
        selected_source = st.selectbox("Источник", source_names, key="news_source")
    with c3:
        if st.button("🔄 Обновить", key="refresh_news"):
            st.cache_data.clear()
            st.rerun()
    
    st.markdown("---")
    news_list = []
    source_status = {}  # Статус каждого источника
    
    # Функция загрузки одного источника
    def load_from_source(source):
        """Загрузка новостей из одного источника"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/rss+xml, application/xml, text/xml, */*',
                'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8'
            }
            
            # feedparser с таймаутом через requests
            import requests
            response = requests.get(source['url'], headers=headers, timeout=10)
            
            if response.status_code != 200:
                return [], f"❌ HTTP {response.status_code}"
            
            feed = feedparser.parse(response.content)
            
            if not hasattr(feed, 'entries') or not feed.entries:
                return [], "❌ Пустой фид"
            
            results = []
            macro_keywords = ['цб', 'ставк', 'нефть', 'brent', 'золото', 'gold',
                            'доллар', 'рубль', 'санкц', 'инфляц', 'ввп', 'бирж',
                            'moex', 'мосбир', 'газпром', 'лукойл', 'сбер', 'яндекс',
                            'роснефть', 'полюс', 'opec', 'фрс', 'fed']
            
            for entry in feed.entries[:20]:
                title = entry.get('title', '')
                desc = entry.get('summary', entry.get('description', ''))
                url = entry.get('link', '#')
                published = entry.get('published', '')
                
                sentiment, tickers, sector, keywords = analyze_news_sentiment(title, desc)
                is_macro = any(kw in (title + ' ' + desc).lower() for kw in macro_keywords)
                
                if is_macro or tickers or abs(sentiment) > 0.2:
                    results.append({
                        'title': title,
                        'url': url,
                        'published': published,
                        'sentiment': sentiment,
                        'tickers': tickers,
                        'sector': sector,
                        'keywords': keywords,
                        'source': source['name']
                    })
            
            return results, f"✅ {len(results)} новостей"
        except requests.exceptions.Timeout:
            return [], "⏱ Таймаут"
        except requests.exceptions.ConnectionError:
            return [], "🔌 Нет соединения"
        except Exception as e:
            return [], f"❌ {str(e)[:50]}"
    
    # Загрузка новостей
    with st.spinner("Загрузка новостей..."):
        if selected_source == "🤖 Авто (все источники)":
            # Пробуем все источники
            for source in NEWS_SOURCES:
                results, status = load_from_source(source)
                source_status[source['name']] = status
                news_list.extend(results)
        else:
            # Конкретный источник
            source = next((s for s in NEWS_SOURCES if s['name'] == selected_source), None)
            if source:
                results, status = load_from_source(source)
                source_status[source['name']] = status
                news_list.extend(results)
    
    # Статус источников
    with st.expander("📡 Статус источников", expanded=False):
        for name, status in source_status.items():
            st.markdown(f"**{name}:** {status}")
        
        st.info("""
        💡 **Если все источники недоступны:**
        - Streamlit Cloud сервер может быть заблокирован
        - Попробуйте переключиться на "Из базы (история)" 
        - Или запустите приложение локально
        """)
    
    # Удаляем дубликаты по заголовку
    seen_titles = set()
    unique_news = []
    for n in news_list:
        if n['title'] not in seen_titles:
            seen_titles.add(n['title'])
            unique_news.append(n)
    news_list = unique_news
    
    # Фильтры
    if news_filter == "Только с тикерами":
        news_list = [n for n in news_list if n.get('tickers')]
    elif news_filter == "Только позитивные":
        news_list = [n for n in news_list if (n.get('sentiment', 0) or 0) > 0.2]
    elif news_filter == "Только негативные":
        news_list = [n for n in news_list if (n.get('sentiment', 0) or 0) < -0.2]
    
    st.markdown("---")
    
    # Отображение
    if not news_list:
        st.warning("📭 **Новости не удалось загрузить ни из одного источника**")
        st.markdown("""
        ### 🔧 Что можно сделать:
        
        1. **Проверьте статус источников** (развёрнутый блок выше)
        2. **Переключитесь на конкретный источник** — возможно, один из них работает
        3. **Запустите локально** — если проблема в блокировке иностранных IP
        4. **Используйте NewsAPI** — я могу добавить интеграцию с бесплатным API новостей
        
        ### 🚀 Хотите NewsAPI?
        Зарегистрируйтесь на [newsapi.org](https://newsapi.org) (бесплатно, 100 запросов/день) 
        и получите ключ. Я добавлю интеграцию за 5 минут.
        """)
    else:
        # Метрики
        c1, c2, c3, c4 = st.columns(4)
        with c1: st.metric("Всего", len(news_list))
        with c2: st.metric("🟢 Позитив", len([n for n in news_list if (n.get('sentiment', 0) or 0) > 0.2]))
        with c3: st.metric("🔴 Негатив", len([n for n in news_list if (n.get('sentiment', 0) or 0) < -0.2]))
        with c4: 
            sources_used = len(set(n.get('source', '') for n in news_list))
            st.metric("Источников", sources_used)
        
        avg_sent = sum(n.get('sentiment', 0) or 0 for n in news_list) / max(len(news_list), 1)
        mood = "🟢 ПОЗИТИВНО" if avg_sent > 0.2 else "🔴 НЕГАТИВНО" if avg_sent < -0.2 else "🟡 НЕЙТРАЛЬНО"
        mood_color = "green" if avg_sent > 0.2 else "red" if avg_sent < -0.2 else "orange"
        st.markdown(f"**Настроение:** <span style='color:{mood_color}; font-size:18px;'>{mood} ({avg_sent:+.2f})</span>", unsafe_allow_html=True)
        st.markdown("---")
        
        # Список новостей
        for n in news_list:
            sent = n.get('sentiment', 0) or 0
            if sent > 0.2:
                sent_emoji, sent_text = "🟢", f"Позитив ({sent:+.2f})"
            elif sent < -0.2:
                sent_emoji, sent_text = "🔴", f"Негатив ({sent:+.2f})"
            else:
                sent_emoji, sent_text = "🟡", f"Нейтрально ({sent:+.2f})"
            
            with st.container():
                source_badge = f"`{n.get('source', '')}`" if n.get('source') else ""
                st.markdown(f"### {sent_emoji} [{n.get('title', '')}]({n.get('url', '#')}) {source_badge}")
                
                meta = [f"**Сентимент:** {sent_text}"]
                tickers = n.get('tickers', [])
                if tickers:
                    meta.append(f"**Тикеры:** {' '.join(['`'+t+'`' for t in tickers])}")
                sector = n.get('sector', 'general')
                if sector != 'general':
                    meta.append(f"**Сектор:** {sector}")
                st.caption(" • ".join(meta))
                st.divider()

# ==========================================
# 💡 СИГНАЛЫ НА ВЫХОД
# ==========================================
def generate_exit_signals(price, entry, stop, tp1, tp2, tp3, direction, rsi):
    """Генерация сигналов на выход"""
    signals = []
    try:
        if direction == 'long':
            if stop > 0 and price <= stop:
                signals.append("🔴 СТОП-ЛОСС")
            if tp1 > 0 and price >= tp1:
                signals.append(f"🟡 Цель 1 ({tp1:.2f})")
            if tp2 > 0 and price >= tp2:
                signals.append(f"🟢 Цель 2 ({tp2:.2f})")
            if tp3 > 0 and price >= tp3:
                signals.append(f"🎯 Цель 3 ({tp3:.2f})")
            if entry > 0 and rsi > CONFIG['RSI_OVERBOUGHT'] and price > entry * 1.05:
                signals.append(f"⚠️ RSI перекуплен ({rsi:.1f})")
        elif direction == 'short':
            if stop > 0 and price >= stop:
                signals.append("🔴 СТОП-ЛОСС")
            if tp1 > 0 and price <= tp1:
                signals.append(f"🟡 Цель 1 ({tp1:.2f})")
            if tp2 > 0 and price <= tp2:
                signals.append(f"🟢 Цель 2 ({tp2:.2f})")
            if tp3 > 0 and price <= tp3:
                signals.append(f"🎯 Цель 3 ({tp3:.2f})")
            if entry > 0 and rsi < CONFIG['RSI_OVERSOLD'] and price < entry * 0.95:
                signals.append(f"⚠️ RSI перепродан ({rsi:.1f})")
    except Exception:
        pass
    return signals

# ==========================================
# 🎨 ГЛАВНЫЙ ИНТЕРФЕЙС
# ==========================================
def main():
    st.set_page_config(page_title="Макро-Радар МОЕХ v6.1", page_icon="📈", layout="wide")
    st.markdown("""
    <style>
        .main { background-color: #0e1117; }
        .trade-long { border-left: 4px solid #00ff00; padding: 15px; background: rgba(0,255,0,0.05); border-radius: 5px; }
        .trade-short { border-left: 4px solid #ff4444; padding: 15px; background: rgba(255,68,68,0.05); border-radius: 5px; }
        .exit-signal { background: #262730; padding: 10px; margin: 5px 0; border-radius: 5px; }
        .outcome-win { background: rgba(0,255,0,0.1); padding: 10px; border-radius: 3px; }
        .outcome-loss { background: rgba(255,68,68,0.1); padding: 10px; border-radius: 3px; }
    </style>
    """, unsafe_allow_html=True)
    
    if 'monitor_running' not in st.session_state:
        st.session_state.monitor_running = True
        threading.Thread(target=background_monitor, daemon=True).start()
    
    init_db()
    
    st.title("📈 Макро-Радар МОЕХ v6.1")
    st.caption("**Профессиональный трейдинг-терминал с AI-аналитикой**")
    st.warning("⚠️ Аналитический инструмент. Все решения принимаете самостоятельно.")
    
    now = datetime.now(CONFIG['MSK_TZ'])
    is_open = now.weekday() < 5 and 10 <= now.hour < 24
    st.caption(f"**Статус:** {'🟢 Торги' if is_open else '🔴 Закрыт'} | **Время:** {now.strftime('%H:%M:%S')}")
    
    # Загрузка данных
    signals_rows = execute_db_query('SELECT * FROM signals ORDER BY timestamp DESC LIMIT 200', fetch=True) or []
    sig_cols = ['id', 'timestamp', 'ticker', 'name', 'type', 'sector', 'price', 'change_pct',
              'volume', 'avg_volume', 'rsi', 'atr', 'strength', 'news_sentiment', 'forecast_score',
              'entry_price', 'stop_loss', 'take_profit_1', 'take_profit_2', 'take_profit_3',
              'risk_reward', 'position_size', 'trade_direction', 'support_level', 'resistance_level',
              'outcome', 'pnl_pct', 'max_price', 'min_price', 'hours_elapsed', 'checked', 'exit_reason']
    signals = []
    for r in signals_rows:
        if len(r) >= len(sig_cols):
            signals.append(dict(zip(sig_cols, r)))
    
    ideas_rows = execute_db_query('SELECT * FROM trade_ideas WHERE status="active" ORDER BY timestamp DESC', fetch=True) or []
    idea_cols = ['id', 'timestamp', 'ticker', 'name', 'direction', 'entry_price', 'stop_loss',
                 'take_profit_1', 'take_profit_2', 'take_profit_3', 'risk_reward', 'position_size',
                 'confidence', 'status', 'exit_signal', 'exit_timestamp']
    trade_ideas = []
    for r in ideas_rows:
        if len(r) >= len(idea_cols):
            trade_ideas.append(dict(zip(idea_cols, r)))
    
    checked = [s for s in signals if s.get('checked') == 1]
    wins = [s for s in checked if s.get('outcome') == 'win']
    losses = [s for s in checked if s.get('outcome') == 'loss']
    
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: st.metric("Сигналов", len(signals))
    with c2: st.metric("Проверено", len(checked))
    with c3:
        wr = len(wins) / max(len(checked), 1) * 100
        st.metric("Win Rate", f"{wr:.1f}%")
    with c4: st.metric("Идей", len(trade_ideas))
    with c5:
        avg_pnl = sum(s.get('pnl_pct', 0) or 0 for s in checked) / max(len(checked), 1)
        c = "green" if avg_pnl >= 0 else "red"
        st.markdown(f"**P&L:** <span style='color:{c}; font-size:20px;'>{avg_pnl:+.2f}%</span>", unsafe_allow_html=True)
    
    st.markdown("---")
    
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=30000, key="auto_refresh")
    except ImportError:
        if st.button("🔄 Обновить"):
            st.rerun()
    
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10 = st.tabs([
        "⭐ Лучшие идеи", "🔥 Корреляции", "📊 Секторы",
        "📈 Котировки", "💡 Идеи", "🎯 Сигналы",
        "🚨 Позиции", "📊 Эффективность", "📰 Новости", "📜 История"
    ])
    
    with tab1:
        render_best_ideas_dashboard()
    with tab2:
        render_heatmap_correlation()
    with tab3:
        render_sector_comparison()
    with tab4:
        render_quotes_tab()
    
    with tab5:
        st.subheader("Готовые торговые планы")
        if not trade_ideas:
            st.info("Ожидание идей с R:R ≥ 1:2...")
        else:
            for idea in trade_ideas[:10]:
                direction = idea.get('direction', 'long')
                dir_emoji = "📈" if direction == 'long' else "📉"
                css = "trade-long" if direction == 'long' else "trade-short"
                
                df = get_moex_data(idea.get('ticker', ''), CONFIG['ASSETS'].get(idea.get('ticker', ''), {}).get('type', 'stock'))
                exit_sigs = []
                if df is not None:
                    cp = df['close'].iloc[-1]
                    rsi = calculate_rsi(df)
                    exit_sigs = generate_exit_signals(
                        cp,
                        idea.get('entry_price', 0),
                        idea.get('stop_loss', 0),
                        idea.get('take_profit_1', 0),
                        idea.get('take_profit_2', 0),
                        idea.get('take_profit_3', 0),
                        direction, rsi
                    )
                
                st.markdown(f'<div class="{css}">', unsafe_allow_html=True)
                c1, c2, c3 = st.columns([2, 1, 1])
                with c1:
                    st.markdown(f"**{dir_emoji} {idea.get('name', '')} ({idea.get('ticker', '')})**")
                    st.caption(f"**{direction.upper()}** | Уверенность: {idea.get('confidence', 0):.0f}%")
                with c2: st.metric("Вход", f"{idea.get('entry_price', 0):.2f}")
                with c3: st.metric("R:R", f"1:{idea.get('risk_reward', 0):.1f}")
                
                st.markdown("---")
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.markdown("**🛑 Стоп**")
                    st.markdown(f"<span style='color:#ff4444; font-size:20px;'>{idea.get('stop_loss', 0):.2f}</span>", unsafe_allow_html=True)
                with c2:
                    st.markdown("**🎯 Цель 1**")
                    st.markdown(f"<span style='color:#ffaa00; font-size:20px;'>{idea.get('take_profit_1', 0):.2f}</span>", unsafe_allow_html=True)
                with c3:
                    st.markdown("**🎯 Цель 2**")
                    st.markdown(f"<span style='color:#00ff00; font-size:20px;'>{idea.get('take_profit_2', 0):.2f}</span>", unsafe_allow_html=True)
                with c4:
                    st.markdown("**🎯 Цель 3**")
                    st.markdown(f"<span style='color:#00ffff; font-size:20px;'>{idea.get('take_profit_3', 0):.2f}</span>", unsafe_allow_html=True)
                
                if exit_sigs:
                    st.markdown("**⚠️ Выходы:**")
                    for s in exit_sigs:
                        st.markdown(f'<div class="exit-signal">{s}</div>', unsafe_allow_html=True)
                
                st.markdown('</div>', unsafe_allow_html=True)
                st.divider()
    
    with tab6:
        st.subheader("Сигналы с уровнями")
        if not signals:
            st.info("Ожидание...")
        else:
            for sig in signals[:15]:
                direction = sig.get('trade_direction', 'neutral')
                de = "📈" if direction == 'long' else "📉" if direction == 'short' else "⚖️"
                change = sig.get('change_pct', 0) or 0
                forecast = sig.get('forecast_score', 0) or 0
                with st.expander(f"{de} {sig.get('name', '')} | {change:+.2f}% | Прогноз: {forecast:.0f}%", expanded=False):
                    c1, c2, c3, c4, c5 = st.columns(5)
                    with c1: st.metric("Цена", f"{sig.get('price', 0):.2f}")
                    with c2: st.metric("RSI", f"{sig.get('rsi', 0):.1f}")
                    with c3: st.metric("ATR", f"{sig.get('atr', 0):.2f}")
                    with c4: st.metric("Направление", direction.upper())
                    with c5: st.metric("R:R", f"1:{sig.get('risk_reward', 0):.1f}")
                    st.markdown(f"**Вход:** {sig.get('entry_price', 0):.2f} | **Стоп:** {sig.get('stop_loss', 0):.2f}")
                    st.markdown(f"**Цели:** {sig.get('take_profit_1', 0):.2f} / {sig.get('take_profit_2', 0):.2f} / {sig.get('take_profit_3', 0):.2f}")
    
    with tab7:
        st.subheader("Активные позиции")
        if not trade_ideas:
            st.info("Нет позиций")
        else:
            for idea in trade_ideas:
                ticker = idea.get('ticker', '')
                asset_info = CONFIG['ASSETS'].get(ticker, {})
                df = get_moex_data(ticker, asset_info.get('type', 'stock'))
                if df is not None:
                    cp = df['close'].iloc[-1]
                    entry = idea.get('entry_price', 0) or 1
                    direction = idea.get('direction', 'long')
                    if direction == 'long':
                        pnl = (cp - entry) / entry * 100
                    else:
                        pnl = (entry - cp) / entry * 100
                    color = "green" if pnl >= 0 else "red"
                    css_class = "outcome-win" if pnl >= 0 else "outcome-loss"
                    st.markdown(f'<div class="{css_class}">', unsafe_allow_html=True)
                    c1, c2, c3 = st.columns([2, 1, 1])
                    with c1:
                        st.markdown(f"**{idea.get('name', '')}** ({ticker})")
                        st.caption(f"Вход: {entry:.2f}")
                    with c2:
                        st.markdown(f"<span style='color:{color}; font-size:18px;'>{cp:.2f}</span>", unsafe_allow_html=True)
                    with c3:
                        st.markdown(f"<span style='color:{color}; font-size:18px;'>{pnl:+.2f}%</span>", unsafe_allow_html=True)
                    st.markdown('</div>', unsafe_allow_html=True)
                    st.divider()
    
    with tab8:
        st.subheader("📊 Эффективность")
        if len(checked) < 5:
            st.info(f"Мало данных: {len(checked)}. Нужно 5+.")
        else:
            c1, c2, c3, c4 = st.columns(4)
            with c1: st.metric("Win Rate", f"{wr:.1f}%")
            with c2:
                avg_win = sum(s.get('pnl_pct', 0) or 0 for s in wins) / max(len(wins), 1)
                st.metric("Ср. прибыль", f"{avg_win:+.2f}%")
            with c3:
                avg_loss = sum(s.get('pnl_pct', 0) or 0 for s in losses) / max(len(losses), 1)
                st.metric("Ср. убыток", f"{avg_loss:+.2f}%")
            with c4:
                tw = sum(s.get('pnl_pct', 0) or 0 for s in wins)
                tl = sum(s.get('pnl_pct', 0) or 0 for s in losses)
                if abs(tl) < 0.01:
                    pf = float('inf') if tw > 0 else 0
                    st.metric("Profit Factor", "∞" if pf == float('inf') else f"{pf:.2f}")
                else:
                    st.metric("Profit Factor", f"{abs(tw / tl):.2f}")
            
            df_checked = pd.DataFrame(checked)
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### Исходы")
                st.bar_chart(df_checked['outcome'].value_counts())
            with c2:
                st.markdown("#### P&L")
                st.bar_chart(df_checked['pnl_pct'])
            
            st.markdown("#### По тикерам")
            try:
                stats = df_checked.groupby('ticker').agg({
                    'outcome': lambda x: (x == 'win').sum() / len(x) * 100,
                    'pnl_pct': 'mean', 'id': 'count'
                }).round(2)
                stats.columns = ['Win Rate %', 'Ср. P&L %', 'Кол-во']
                st.dataframe(stats.sort_values('Win Rate %', ascending=False), use_container_width=True)
            except Exception as e:
                st.error(f"Ошибка статистики: {e}")
    
    with tab9:
        render_news_tab()
    
    with tab10:
        st.subheader("📜 История")
        if not signals:
            st.info("Пусто")
        else:
            c1, c2, c3 = st.columns(3)
            with c1:
                fo = st.selectbox("Исход", ["Все", "win", "loss", "neutral", "pending"], key="h_out")
            with c2:
                tickers_list = list(set(s.get('ticker', '') for s in signals))
                ft = st.selectbox("Тикер", ["Все"] + tickers_list, key="h_tick")
            with c3:
                fd = st.selectbox("Направление", ["Все", "long", "short", "neutral"], key="h_dir")
            
            filtered = signals
            if fo != "Все":
                filtered = [s for s in filtered if s.get('outcome') == fo]
            if ft != "Все":
                filtered = [s for s in filtered if s.get('ticker') == ft]
            if fd != "Все":
                filtered = [s for s in filtered if s.get('trade_direction') == fd]
            
            st.markdown(f"Найдено: **{len(filtered)}**")
            
            for sig in filtered[:30]:
                outcome = sig.get('outcome', 'pending')
                em = "✅" if outcome == 'win' else "❌" if outcome == 'loss' else "⏳"
                cls = f"outcome-{outcome}" if outcome in ['win', 'loss'] else ""
                st.markdown(f'<div class="{cls}">', unsafe_allow_html=True)
                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                with c1:
                    st.markdown(f"**{em} {sig.get('name', '')}** ({sig.get('ticker', '')})")
                    st.caption(sig.get('trade_direction', ''))
                with c2: st.metric("Вход", f"{sig.get('entry_price', 0):.2f}")
                with c3:
                    if sig.get('checked'):
                        pnl = sig.get('pnl_pct', 0) or 0
                        c = "green" if pnl >= 0 else "red"
                        st.markdown(f"<span style='color:{c};'>{pnl:+.2f}%</span>", unsafe_allow_html=True)
                with c4: st.markdown(f"**{outcome}**")
                st.markdown('</div>', unsafe_allow_html=True)
                st.divider()

if __name__ == "__main__":
    main()
