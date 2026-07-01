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
    return sqlite3.connect('signals.db', check_same_thread=False, timeout=10)

def init_db():
    with DB_LOCK:
        conn = get_db_connection()
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
        conn.close()

def execute_db_query(query, params=None, fetch=False):
    with DB_LOCK:
        conn = get_db_connection()
        try:
            c = conn.cursor()
            if params: c.execute(query, params)
            else: c.execute(query)
            result = c.fetchall() if fetch else None
            conn.commit()
            return result
        finally:
            conn.close()

# ==========================================
# 📊 MOEX API
# ==========================================
def fetch_moex_data_raw(ticker: str, asset_type: str) -> Optional[pd.DataFrame]:
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
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            continue
    return None

@st.cache_data(ttl=CONFIG['CACHE_TTL'])
def get_moex_data(ticker: str, asset_type: str) -> Optional[pd.DataFrame]:
    return fetch_moex_data_raw(ticker, asset_type)

# ==========================================
# 📈 ТЕХНИЧЕСКИЙ АНАЛИЗ
# ==========================================
def calculate_atr(df: pd.DataFrame, period: int = None) -> float:
    period = period or CONFIG['ATR_PERIOD']
    if len(df) < period: return 0.0
    tr = pd.concat([df['high'] - df['low'], 
                    abs(df['high'] - df['close'].shift()), 
                    abs(df['low'] - df['close'].shift())], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else 0.0

def find_support_resistance(df: pd.DataFrame, window: int = 20) -> Tuple[float, float]:
    if len(df) < window:
        cp = df['close'].iloc[-1]
        return cp * 0.98, cp * 1.02
    recent = df.tail(window)
    return float(recent['low'].min()), float(recent['high'].max())

def calculate_rsi(df: pd.DataFrame, period: int = None) -> float:
    period = period or CONFIG['RSI_PERIOD']
    if len(df) < period: return 50.0
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0

def calculate_macd(df: pd.DataFrame):
    """MACD индикатор"""
    if len(df) < 26: return None, None, None
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line
    return float(macd_line.iloc[-1]), float(signal_line.iloc[-1]), float(histogram.iloc[-1])

def calculate_trade_levels(price, direction, atr, support, resistance, volatility):
    vol_mult = {'low': 0.8, 'medium': 1.0, 'high': 1.2}.get(volatility, 1.0)
    if direction == 'long':
        stop_distance = atr * CONFIG['STOP_LOSS_ATR_MULTIPLIER'] * vol_mult
        stop_loss = max(price - stop_distance, support * 0.995)
        risk = price - stop_loss
        if risk <= 0:
            return {'entry': price, 'stop_loss': price, 'tp1': price, 'tp2': price, 'tp3': price, 'risk_reward': 0}
        tp1 = price + risk * CONFIG['TAKE_PROFIT_LEVELS'][0]
        tp2 = price + risk * CONFIG['TAKE_PROFIT_LEVELS'][1]
        tp3 = min(price + risk * CONFIG['TAKE_PROFIT_LEVELS'][2], resistance)
        risk_reward = (tp2 - price) / risk
    elif direction == 'short':
        stop_distance = atr * CONFIG['STOP_LOSS_ATR_MULTIPLIER'] * vol_mult
        stop_loss = min(price + stop_distance, resistance * 1.005)
        risk = stop_loss - price
        if risk <= 0:
            return {'entry': price, 'stop_loss': price, 'tp1': price, 'tp2': price, 'tp3': price, 'risk_reward': 0}
        tp1 = price - risk * CONFIG['TAKE_PROFIT_LEVELS'][0]
        tp2 = price - risk * CONFIG['TAKE_PROFIT_LEVELS'][1]
        tp3 = max(price - risk * CONFIG['TAKE_PROFIT_LEVELS'][2], support)
        risk_reward = (price - tp2) / risk
    else:
        return {'entry': price, 'stop_loss': price, 'tp1': price, 'tp2': price, 'tp3': price, 'risk_reward': 0}
    return {
        'entry': round(price, 2), 'stop_loss': round(stop_loss, 2),
        'tp1': round(tp1, 2), 'tp2': round(tp2, 2), 'tp3': round(tp3, 2),
        'risk_reward': round(risk_reward, 2)
    }

def calculate_position_size(balance, risk_pct, entry, stop):
    if entry <= 0 or stop <= 0 or entry == stop: return 0
    return max(int(balance * risk_pct / abs(entry - stop)), 0)

def determine_trade_direction(rsi, price_change, sentiment, support, resistance, price):
    score = 0
    if rsi < CONFIG['RSI_OVERSOLD']: score += 2
    elif rsi > CONFIG['RSI_OVERBOUGHT']: score -= 2
    if price_change > 1.5: score += 1
    elif price_change < -1.5: score -= 1
    if sentiment > 0.3: score += 1
    elif sentiment < -0.3: score -= 1
    if price < support * 1.01: score += 1
    elif price > resistance * 0.99: score -= 1
    if score >= 2: return 'long'
    elif score <= -2: return 'short'
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
    text = (title + ' ' + description).lower()
    pos_count = sum(1 for w in POSITIVE_WORDS if w in text)
    neg_count = sum(1 for w in NEGATIVE_WORDS if w in text)
    total = pos_count + neg_count
    sentiment = (pos_count - neg_count) / max(total, 1)
    found_tickers, found_keywords, sector = [], [], 'general'
    for ticker, info in CONFIG['ASSETS'].items():
        for kw in info['keywords']:
            if kw in text:
                found_tickers.append(ticker)
                found_keywords.append(kw)
                if info['sector'] != 'general': sector = info['sector']
                break
    return round(sentiment, 2), found_tickers, sector, found_keywords

def calculate_forecast_score(signal_data, news_sentiment, historical_data):
    score = 50.0
    price_momentum = min(abs(signal_data['change_pct']) * 10, 20)
    score += price_momentum if signal_data['change_pct'] > 0 else -price_momentum
    volume_factor = min((signal_data['volume'] / max(signal_data['avg_volume'], 1) - 1) * 15, 25)
    score += volume_factor if signal_data['change_pct'] > 0 else -volume_factor
    rsi = signal_data.get('rsi', 50)
    if rsi < CONFIG['RSI_OVERSOLD']: score += 15
    elif rsi > CONFIG['RSI_OVERBOUGHT']: score -= 15
    score += news_sentiment * 20
    ticker_history = [s for s in historical_data if s.get('ticker') == signal_data['ticker']]
    if len(ticker_history) >= 5:
        success_rate = sum(1 for s in ticker_history[-10:] if s.get('change_pct', 0) > 0) / len(ticker_history[-10:])
        score += (success_rate - 0.5) * 20
    return max(0, min(100, round(score)))

# ==========================================
# 🤖 АВТОРАЗМЕТКА
# ==========================================
def auto_label_signals():
    unchecked = execute_db_query(
        'SELECT * FROM signals WHERE checked = 0 AND trade_direction != "neutral" ORDER BY timestamp ASC LIMIT 10',
        fetch=True)
    if not unchecked: return
    columns = ['id', 'timestamp', 'ticker', 'name', 'type', 'sector', 'price', 'change_pct',
               'volume', 'avg_volume', 'rsi', 'atr', 'strength', 'news_sentiment', 'forecast_score',
               'entry_price', 'stop_loss', 'take_profit_1', 'take_profit_2', 'take_profit_3',
               'risk_reward', 'position_size', 'trade_direction', 'support_level', 'resistance_level',
               'outcome', 'pnl_pct', 'max_price', 'min_price', 'hours_elapsed', 'checked', 'exit_reason']
    now = datetime.now(CONFIG['MSK_TZ'])
    for row in unchecked:
        signal = dict(zip(columns, row))
        try:
            try:
                signal_time = datetime.fromisoformat(signal['timestamp'])
                if signal_time.tzinfo is None:
                    signal_time = CONFIG['MSK_TZ'].localize(signal_time)
            except ValueError: continue
            hours_elapsed = (now - signal_time).total_seconds() / 3600
            if hours_elapsed < CONFIG['AUTO_LABEL_HOURS']: continue
            df = fetch_moex_data_raw(signal['ticker'], signal['type'])
            if df is None or len(df) < 5: continue
            df['time'] = pd.to_datetime(df['begin'])
            try: df['time'] = df['time'].dt.tz_localize(CONFIG['MSK_TZ'])
            except Exception: pass
            df_after = df[df['time'] > signal_time]
            if len(df_after) == 0: df_after = df.tail(20)
            entry_price = signal['entry_price']
            stop_loss = signal['stop_loss']
            tp1, tp2, tp3 = signal['take_profit_1'], signal['take_profit_2'], signal['take_profit_3']
            direction = signal['trade_direction']
            max_price = df_after['high'].max()
            min_price = df_after['low'].min()
            final_price = df_after['close'].iloc[-1]
            outcome, exit_reason, pnl_pct = 'neutral', '', 0.0
            if direction == 'long':
                if min_price <= stop_loss:
                    outcome, exit_reason = 'loss', 'stop_loss'
                    pnl_pct = (stop_loss - entry_price) / entry_price * 100
                elif max_price >= tp3:
                    outcome, exit_reason = 'win', 'target_3'
                    pnl_pct = (tp3 - entry_price) / entry_price * 100
                elif max_price >= tp2:
                    outcome, exit_reason = 'win', 'target_2'
                    pnl_pct = (tp2 - entry_price) / entry_price * 100
                elif max_price >= tp1:
                    outcome, exit_reason = 'win', 'target_1'
                    pnl_pct = (tp1 - entry_price) / entry_price * 100
                else:
                    pnl_pct = (final_price - entry_price) / entry_price * 100
                    if pnl_pct > 1.0: outcome, exit_reason = 'partial_win', 'in_profit'
                    elif pnl_pct < -1.0: outcome, exit_reason = 'partial_loss', 'in_loss'
                    else: outcome, exit_reason = 'neutral', 'sideways'
            elif direction == 'short':
                if max_price >= stop_loss:
                    outcome, exit_reason = 'loss', 'stop_loss'
                    pnl_pct = (entry_price - stop_loss) / entry_price * 100
                elif min_price <= tp3:
                    outcome, exit_reason = 'win', 'target_3'
                    pnl_pct = (entry_price - tp3) / entry_price * 100
                elif min_price <= tp2:
                    outcome, exit_reason = 'win', 'target_2'
                    pnl_pct = (entry_price - tp2) / entry_price * 100
                elif min_price <= tp1:
                    outcome, exit_reason = 'win', 'target_1'
                    pnl_pct = (entry_price - tp1) / entry_price * 100
                else:
                    pnl_pct = (entry_price - final_price) / entry_price * 100
                    if pnl_pct > 1.0: outcome, exit_reason = 'partial_win', 'in_profit'
                    elif pnl_pct < -1.0: outcome, exit_reason = 'partial_loss', 'in_loss'
                    else: outcome, exit_reason = 'neutral', 'sideways'
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
    init_db()
    alerted_candles = {}
    last_label_check = 0
    last_news_check = 0
    while True:
        try:
            current_time = time.time()
            if current_time - last_label_check > 600:
                try:
                    auto_label_signals()
                    last_label_check = current_time
                except Exception as e:
                    logger.error(f"Ошибка авторазметки: {e}")
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
                        logger.info(f"📰 Новости обновлены: {saved_count}")
                except Exception as e:
                    logger.error(f"Ошибка новостей: {e}")
            now = datetime.now(CONFIG['MSK_TZ'])
            is_open = now.weekday() < 5 and 10 <= now.hour < 24
            if is_open:
                for ticker, info in CONFIG['ASSETS'].items():
                    df = fetch_moex_data_raw(ticker, info['type'])
                    if df is not None and len(df) >= 5:
                        current_volume = df['volume'].iloc[-1]
                        current_close = df['close'].iloc[-1]
                        prev_close = df['close'].iloc[-2]
                        candle_time = df['begin'].iloc[-1]
                        if alerted_candles.get(ticker) == candle_time: continue
                        avg_volume = df['volume'].iloc[:-1].mean()
                        price_change_pct = ((current_close - prev_close) / prev_close) * 100
                        if current_volume > avg_volume * CONFIG['VOLUME_MULTIPLIER'] and abs(price_change_pct) >= CONFIG['PRICE_CHANGE_THRESHOLD']:
                            rsi = calculate_rsi(df)
                            atr = calculate_atr(df)
                            support, resistance = find_support_resistance(df)
                            strength = 'strong' if abs(price_change_pct) > 3.0 or rsi < CONFIG['RSI_OVERSOLD'] or rsi > CONFIG['RSI_OVERBOUGHT'] else 'medium'
                            recent_news = execute_db_query('SELECT sentiment_score, related_tickers FROM news_analysis ORDER BY timestamp DESC LIMIT 5', fetch=True) or []
                            ticker_sent, news_count = 0, 0
                            for row in recent_news:
                                if ticker in (row[1] or ''):
                                    ticker_sent += row[0]
                                    news_count += 1
                            ticker_sent = ticker_sent / max(news_count, 1)
                            hist_rows = execute_db_query('SELECT ticker, change_pct FROM signals ORDER BY timestamp DESC LIMIT 50', fetch=True) or []
                            historical = [{'ticker': r[0], 'change_pct': r[1]} for r in hist_rows]
                            forecast = calculate_forecast_score(
                                {'ticker': ticker, 'change_pct': price_change_pct, 'volume': current_volume, 'avg_volume': avg_volume, 'rsi': rsi},
                                ticker_sent, historical)
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
                            logger.info(f"🎯 Сигнал: {ticker} {price_change_pct:+.2f}% | Прогноз: {forecast}")
                    time.sleep(1)
                time.sleep(15)
            else:
                time.sleep(60)
        except Exception as e:
            logger.error(f"Критическая ошибка фона: {e}")
            time.sleep(30)

# ==========================================
# 🎨 ПРОФЕССИОНАЛЬНЫЕ СВЕЧНЫЕ ГРАФИКИ
# ==========================================
def generate_candlestick_chart(df, ticker, name, trade_levels=None):
    """Профессиональный свечной график с уровнями Entry/Stop/TP"""
    try:
        df_plot = df.copy()
        df_plot['begin'] = pd.to_datetime(df_plot['begin'])
        df_plot = df_plot.set_index('begin')
        df_plot = df_plot.rename(columns={
            'open': 'Open', 'high': 'High', 'low': 'Low',
            'close': 'Close', 'volume': 'Volume'
        })
        df_plot = df_plot.tail(50)
        
        # Стиль графика
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
        
        # Горизонтальные линии (уровни)
        hlines_dict = {}
        add_plots = []
        
        if trade_levels and trade_levels.get('risk_reward', 0) > 0:
            hlines_dict = {
                'hlines': [
                    trade_levels['entry'],
                    trade_levels['stop_loss'],
                    trade_levels['tp1'],
                    trade_levels['tp2'],
                    trade_levels['tp3']
                ],
                'colors': ['#00ffcc', '#ff4444', '#ffaa00', '#00ff00', '#00ffff'],
                'linestyle': ['-', '--', '-', '-', '-'],
                'linewidths': [1.5, 1.5, 1, 1, 1]
            }
        
        # Добавляем SMA 20
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
            hlines=hlines_dict if hlines_dict else None,
            addplot=add_plots if add_plots else None,
            tight_layout=True
        )
        
        # Заголовок
        axes[0].set_title(f'{name} ({ticker}) - 10min candles', 
                         color='white', fontsize=14, pad=10)
        
        # Легенда уровней
        if trade_levels and trade_levels.get('risk_reward', 0) > 0:
            from matplotlib.lines import Line2D
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
        # Fallback на простой график
        return generate_simple_chart(df, ticker, name)

def generate_simple_chart(df, ticker, name):
    """Упрощенный график на случай ошибки mplfinance"""
    with plt.style.context('dark_background'):
        fig, ax = plt.subplots(figsize=(12, 5))
        fig.patch.set_facecolor('#0e1117')
        ax.set_facecolor('#0e1117')
        ax.plot(range(len(df)), df['close'], color='#00ffcc', linewidth=2)
        ax.set_title(f'{name} ({ticker})', color='white', fontsize=14)
        ax.grid(True, alpha=0.2)
        plt.tight_layout()
        return fig

# ==========================================
# 🔥 HEATMAP КОРРЕЛЯЦИЙ
# ==========================================
def render_heatmap_correlation():
    """Тепловая карта корреляций между активами"""
    st.subheader("🔥 Корреляция доходностей активов")
    st.caption("Как активы движутся относительно друг друга за последние часы")
    
    with st.spinner("Загрузка данных..."):
        prices_data = {}
        for ticker, info in CONFIG['ASSETS'].items():
            df = fetch_moex_data_raw(ticker, info['type'])
            if df is not None and len(df) > 20:
                returns = df['close'].pct_change().dropna()
                prices_data[ticker] = returns
        
        if len(prices_data) < 3:
            st.warning("⚠️ Недостаточно данных для корреляции (нужно минимум 3 актива)")
            return
        
        returns_df = pd.DataFrame(prices_data)
        corr_matrix = returns_df.corr()
    
    # Создание heatmap
    with plt.style.context('dark_background'):
        fig, ax = plt.subplots(figsize=(10, 8))
        fig.patch.set_facecolor('#0e1117')
        ax.set_facecolor('#0e1117')
        
        im = ax.imshow(corr_matrix.values, cmap='RdYlGn', aspect='auto', vmin=-1, vmax=1)
        
        ax.set_xticks(range(len(corr_matrix.columns)))
        ax.set_yticks(range(len(corr_matrix.columns)))
        ax.set_xticklabels(corr_matrix.columns, rotation=45, ha='right', color='white')
        ax.set_yticklabels(corr_matrix.columns, color='white')
        
        # Значения в ячейках
        for i in range(len(corr_matrix)):
            for j in range(len(corr_matrix)):
                val = corr_matrix.values[i, j]
                color = 'white' if abs(val) < 0.5 else 'black'
                ax.text(j, i, f'{val:.2f}', ha="center", va="center", 
                       color=color, fontsize=9, fontweight='bold')
        
        plt.colorbar(im, label='Корреляция', ax=ax)
        ax.set_title('Корреляция доходностей (10-мин свечи)', 
                    color='white', fontsize=14, pad=20)
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)
    
    # Интерпретация
    st.markdown("### 📖 Как читать карту")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.success("🟢 **Зелёный (>0.5)**\nАктивы движутся вместе")
    with col2:
        st.error("🔴 **Красный (<-0.3)**\nПротивоположное движение")
    with col3:
        st.info("⚪ **Белый (~0)**\nНет связи")
    
    # Топ корреляций
    st.markdown("### 🔗 Самые сильные связи")
    pairs = []
    for i in range(len(corr_matrix)):
        for j in range(i+1, len(corr_matrix)):
            pairs.append({
                'pair': f"{corr_matrix.columns[i]} ↔ {corr_matrix.columns[j]}",
                'correlation': corr_matrix.values[i, j]
            })
    pairs.sort(key=lambda x: abs(x['correlation']), reverse=True)
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**🟢 Сильнейшая положительная:**")
        for p in pairs[:3]:
            if p['correlation'] > 0:
                st.markdown(f"- `{p['pair']}`: **{p['correlation']:+.2f}**")
    with col2:
        st.markdown("**🔴 Сильнейшая отрицательная:**")
        for p in reversed(pairs[-3:]):
            if p['correlation'] < 0:
                st.markdown(f"- `{p['pair']}`: **{p['correlation']:+.2f}**")
    
    st.info("💡 **Совет:** Для диверсификации портфеля выбирайте активы с низкой корреляцией (< 0.3)")

# ==========================================
# ⭐ ДАШБОРД ЛУЧШИХ ИДЕЙ
# ==========================================
def render_best_ideas_dashboard():
    """Топ сигналов по разным критериям"""
    st.subheader("⭐ Лучшие торговые идеи")
    st.caption("Автоматический отбор топ-сигналов по ключевым параметрам")
    
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
    signals = [dict(zip(sig_cols, r)) for r in signals_rows]
    
    # === ТОП-3 ПО ПРОГНОЗУ ===
    st.markdown("### 🎯 Топ-3 по вероятности успеха")
    top_forecast = sorted(signals, key=lambda x: x['forecast_score'], reverse=True)[:3]
    cols = st.columns(3)
    for i, sig in enumerate(top_forecast):
        with cols[i]:
            emoji = "📈" if sig['trade_direction'] == 'long' else "📉"
            css = "trade-long" if sig['trade_direction'] == 'long' else "trade-short"
            st.markdown(f'<div class="{css}">', unsafe_allow_html=True)
            st.markdown(f"#### {emoji} {sig['name']}")
            st.metric("🎯 Прогноз", f"{sig['forecast_score']:.0f}%")
            st.metric("R:R", f"1:{sig['risk_reward']:.1f}")
            st.metric("RSI", f"{sig['rsi']:.1f}")
            st.caption(f"{sig['change_pct']:+.2f}% | **{sig['trade_direction'].upper()}** | {sig['sector']}")
            st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("---")
    
    # === ТОП-3 ПО RISK/REWARD ===
    st.markdown("### 💰 Топ-3 по соотношению риск/прибыль")
    valid_rr = [s for s in signals if s['risk_reward'] > 0]
    top_rr = sorted(valid_rr, key=lambda x: x['risk_reward'], reverse=True)[:3]
    
    if top_rr:
        cols = st.columns(3)
        for i, sig in enumerate(top_rr):
            with cols[i]:
                emoji = "📈" if sig['trade_direction'] == 'long' else "📉"
                st.markdown(f"#### {emoji} {sig['name']}")
                st.metric("💎 R:R", f"1:{sig['risk_reward']:.1f}")
                col1, col2 = st.columns(2)
                with col1: st.markdown(f"**Вход:** {sig['entry_price']:.2f}")
                with col2: st.markdown(f"**Стоп:** <span style='color:#ff4444;'>{sig['stop_loss']:.2f}</span>", unsafe_allow_html=True)
                st.caption(f"Цели: {sig['take_profit_1']:.2f} → {sig['take_profit_2']:.2f} → {sig['take_profit_3']:.2f}")
    else:
        st.info("Пока нет сигналов с хорошим R:R")
    
    st.markdown("---")
    
    # === ТОП-3 ПО СИЛЕ СИГНАЛА ===
    st.markdown("### 💪 Топ-3 по силе импульса")
    top_strength = sorted(signals, key=lambda x: (
        1 if x['strength'] == 'strong' else 0,
        abs(x['change_pct']),
        x['volume'] / max(x['avg_volume'], 1)
    ), reverse=True)[:3]
    
    cols = st.columns(3)
    for i, sig in enumerate(top_strength):
        with cols[i]:
            emoji = "📈" if sig['trade_direction'] == 'long' else "📉"
            st.markdown(f"#### {emoji} {sig['name']}")
            st.metric("⚡ Импульс", f"{sig['change_pct']:+.2f}%")
            vol_ratio = sig['volume'] / max(sig['avg_volume'], 1)
            st.metric("📊 Объём", f"x{vol_ratio:.1f}")
            strength_label = "💥 СИЛЬНЫЙ" if sig['strength'] == 'strong' else "⚖️ Средний"
            st.caption(f"{strength_label} | Сентимент: {sig['news_sentiment']:+.2f}")
    
    st.markdown("---")
    
    # === СВОДНАЯ ТАБЛИЦА ВСЕХ ИДЕЙ ===
    st.markdown("### 📋 Все активные идеи")
    table_data = []
    for sig in signals[:20]:
        emoji = "📈" if sig['trade_direction'] == 'long' else "📉"
        table_data.append({
            '': emoji,
            'Актив': f"{sig['name']} ({sig['ticker']})",
            'Напр.': sig['trade_direction'].upper(),
            'Прогноз': f"{sig['forecast_score']:.0f}%",
            'R:R': f"1:{sig['risk_reward']:.1f}",
            'Вход': f"{sig['entry_price']:.2f}",
            'Стоп': f"{sig['stop_loss']:.2f}",
            'RSI': f"{sig['rsi']:.0f}",
            'Сила': '💥' if sig['strength'] == 'strong' else '⚖️',
            'Время': sig['timestamp'][11:16] if len(sig['timestamp']) > 16 else ''
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
            sector = info['sector']
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
                    price_change = (df['close'].iloc[-1] - df['close'].iloc[-10]) / df['close'].iloc[-10] * 100
                    performances.append(price_change)
                    details.append({'ticker': ticker, 'change': price_change})
            if performances:
                sector_performance[sector] = sum(performances) / len(performances)
                sector_details[sector] = details
    
    if not sector_performance:
        st.warning("⚠️ Недостаточно данных")
        return
    
    # График
    with plt.style.context('dark_background'):
        fig, ax = plt.subplots(figsize=(10, 6))
        fig.patch.set_facecolor('#0e1117')
        ax.set_facecolor('#0e1117')
        
        sectors_list = list(sector_performance.keys())
        performance_list = list(sector_performance.values())
        colors = ['#26a69a' if p >= 0 else '#ef5350' for p in performance_list]
        
        bars = ax.barh(sectors_list, performance_list, color=colors, alpha=0.8, edgecolor='none')
        
        for bar, perf in zip(bars, performance_list):
            width = bar.get_width()
            ax.text(width + (0.05 if width >= 0 else -0.05), 
                   bar.get_y() + bar.get_height()/2, 
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
    
    # Анализ
    best_sector = max(sector_performance.items(), key=lambda x: x[1])
    worst_sector = min(sector_performance.items(), key=lambda x: x[1])
    
    st.markdown("### 💡 Анализ секторов")
    col1, col2 = st.columns(2)
    with col1:
        st.success(f"🏆 **Сильнейший:** {best_sector[0]}\n\n{best_sector[1]:+.2f}%")
        if best_sector[0] in sector_details:
            for d in sector_details[best_sector[0]]:
                emoji = "🚀" if d['change'] > 0 else "🩸"
                st.caption(f"{emoji} `{d['ticker']}`: {d['change']:+.2f}%")
    with col2:
        st.error(f"📉 **Слабейший:** {worst_sector[0]}\n\n{worst_sector[1]:+.2f}%")
        if worst_sector[0] in sector_details:
            for d in sector_details[worst_sector[0]]:
                emoji = "🚀" if d['change'] > 0 else "🩸"
                st.caption(f"{emoji} `{d['ticker']}`: {d['change']:+.2f}%")
    
    # Рекомендации
    st.markdown("### 🎯 Торговые рекомендации")
    if best_sector[1] > 1.0:
        st.success(f"✅ Сектор **{best_sector[0]}** показывает силу — рассмотрите лонг-позиции")
    if worst_sector[1] < -1.0:
        st.warning(f"⚠️ Сектор **{worst_sector[0]}** под давлением — осторожнее с лонгами")
    
    # Детальная таблица
    with st.expander("📋 Детальная статистика по всем активам"):
        all_data = []
        for sector, details in sector_details.items():
            for d in details:
                all_data.append({
                    'Сектор': sector,
                    'Тикер': d['ticker'],
                    'Изм. за 100 мин %': f"{d['change']:+.2f}%"
                })
        if all_data:
            df_table = pd.DataFrame(all_data)
            st.dataframe(df_table.sort_values('Изм. за 100 мин %', 
                                             key=lambda x: x.str.replace('%', '').str.replace('+', '').astype(float),
                                             ascending=False), 
                        use_container_width=True, hide_index=True)

# ==========================================
# 📈 ВКЛАДКА КОТИРОВОК (с профессиональными графиками)
# ==========================================
@st.cache_data(ttl=60)
def get_all_assets_data():
    assets = []
    for ticker, info in CONFIG['ASSETS'].items():
        df = fetch_moex_data_raw(ticker, info['type'])
        if df is not None and len(df) > 0:
            current = df['close'].iloc[-1]
            prev = df['close'].iloc[-2] if len(df) > 1 else current
            change = ((current - prev) / prev) * 100
            assets.append({
                'ticker': ticker, 'name': info['name'], 'type': info['type'],
                'sector': info['sector'], 'price': current, 'change_pct': change,
                'volume': df['volume'].iloc[-1], 'df': df
            })
    return assets

def get_latest_trade_levels(ticker):
    """Получить последние торговые уровни для тикера"""
    row = execute_db_query(
        f'SELECT entry_price, stop_loss, take_profit_1, take_profit_2, take_profit_3, risk_reward FROM signals WHERE ticker="{ticker}" ORDER BY timestamp DESC LIMIT 1',
        fetch=True)
    if row:
        return {
            'entry': row[0][0], 'stop_loss': row[0][1],
            'tp1': row[0][2], 'tp2': row[0][3], 'tp3': row[0][4],
            'risk_reward': row[0][5]
        }
    return None

def render_quotes_tab():
    st.subheader("📈 Котировки и профессиональные графики")
    
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        show_type = st.selectbox("Показать", ["Все", "Только акции", "Только фьючерсы"], key="qt_type")
    with col2:
        sort_by = st.selectbox("Сортировка", ["По имени", "По изменению %", "По объему"], key="qt_sort")
    with col3:
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
        assets.sort(key=lambda x: x['change_pct'], reverse=True)
    elif sort_by == "По объему":
        assets.sort(key=lambda x: x['volume'], reverse=True)
    else:
        assets.sort(key=lambda x: x['name'])
    
    col1, col2, col3, col4 = st.columns(4)
    with col1: st.metric("Активов", len(assets))
    with col2: st.metric("Растущих", f"{len([a for a in assets if a['change_pct'] > 0])} 🚀")
    with col3: st.metric("Падающих", f"{len([a for a in assets if a['change_pct'] < 0])} 🩸")
    with col4:
        avg = sum(a['change_pct'] for a in assets) / max(len(assets), 1)
        color = "green" if avg >= 0 else "red"
        st.markdown(f"**Среднее:** <span style='color:{color}; font-size:20px;'>{avg:+.2f}%</span>", unsafe_allow_html=True)
    
    st.markdown("---")
    
    stocks = [a for a in assets if a['type'] == 'stock']
    futures = [a for a in assets if a['type'] == 'futures']
    
    def render_asset_block(asset_list, title):
        if not asset_list: return
        st.markdown(f"### {title}")
        for asset in asset_list:
            with st.container():
                col1, col2, col3 = st.columns([1, 2, 1])
                with col1:
                    emoji = "🚀" if asset['change_pct'] > 0 else "🩸" if asset['change_pct'] < 0 else "⚖️"
                    st.markdown(f"## {emoji} {asset['name']}")
                    st.markdown(f"**{asset['ticker']}** | {asset['sector']}")
                    color = "green" if asset['change_pct'] >= 0 else "red"
                    st.markdown(f"<span style='color:{color}; font-size:28px; font-weight:bold;'>{asset['price']:.2f}</span>", unsafe_allow_html=True)
                    st.markdown(f"<span style='color:{color}; font-size:20px;'>{asset['change_pct']:+.2f}%</span>", unsafe_allow_html=True)
                    st.markdown(f"**Объем:** {asset['volume']:,.0f}")
                with col2:
                    try:
                        trade_levels = get_latest_trade_levels(asset['ticker'])
                        fig = generate_candlestick_chart(asset['df'], asset['ticker'], asset['name'], trade_levels)
                        st.pyplot(fig)
                        plt.close(fig)
                    except Exception as e:
                        st.error(f"Ошибка: {e}")
                with col3:
                    rsi = calculate_rsi(asset['df'])
                    atr = calculate_atr(asset['df'])
                    macd_line, signal_line, hist = calculate_macd(asset['df'])
                    
                    if rsi < CONFIG['RSI_OVERSOLD']:
                        st.success(f"📉 **RSI: {rsi:.1f}**\nПерепроданность")
                    elif rsi > CONFIG['RSI_OVERBOUGHT']:
                        st.error(f"📈 **RSI: {rsi:.1f}**\nПерекупленность")
                    else:
                        st.info(f"⚖️ **RSI: {rsi:.1f}**")
                    
                    st.metric("ATR", f"{atr:.2f}")
                    
                    if macd_line is not None:
                        macd_signal = "🟢 Бычий" if macd_line > signal_line else "🔴 Медвежий"
                        st.markdown(f"**MACD:** {macd_signal}")
                        st.caption(f"Line: {macd_line:.2f}\nSignal: {signal_line:.2f}")
                    
                    if len(asset['df']) >= 20:
                        r = asset['df'].tail(20)
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
    st.subheader("📰 Новости с аналитикой")
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        news_filter = st.selectbox("Фильтр", 
            ["Все новости", "Только с тикерами", "Только позитивные", "Только негативные"], key="news_filter")
    with col2:
        news_source = st.selectbox("Источник", ["РБК (свежие)", "Из базы (история)"], key="news_source")
    with col3:
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
            n = dict(zip(news_cols, row))
            tickers_str = n['tickers'] if isinstance(n['tickers'], str) else ''
            news_list.append({
                'title': n['title'], 'url': n['url'], 'published': n['timestamp'],
                'sentiment': n['sentiment'],
                'tickers': tickers_str.split(',') if tickers_str else [],
                'sector': n['sector'],
                'keywords': n['keywords'].split(',') if isinstance(n['keywords'], str) and n['keywords'] else [],
                'source': 'db'
            })
        if news_list: st.info(f"📊 {len(news_list)} из базы")
        else: st.warning("⚠️ База пуста")
    
    if news_filter == "Только с тикерами":
        news_list = [n for n in news_list if n['tickers']]
    elif news_filter == "Только позитивные":
        news_list = [n for n in news_list if n['sentiment'] > 0.2]
    elif news_filter == "Только негативные":
        news_list = [n for n in news_list if n['sentiment'] < -0.2]
    
    st.markdown("---")
    if not news_list:
        st.info("📭 Нет новостей")
    else:
        col1, col2, col3, col4 = st.columns(4)
        with col1: st.metric("Всего", len(news_list))
        with col2: st.metric("🟢 Позитив", len([n for n in news_list if n['sentiment'] > 0.2]))
        with col3: st.metric("🔴 Негатив", len([n for n in news_list if n['sentiment'] < -0.2]))
        with col4: st.metric("🟡 Нейтрал", len(news_list) - len([n for n in news_list if abs(n['sentiment']) > 0.2]))
        
        avg_sent = sum(n['sentiment'] for n in news_list) / len(news_list)
        mood = "🟢 ПОЗИТИВНО" if avg_sent > 0.2 else "🔴 НЕГАТИВНО" if avg_sent < -0.2 else "🟡 НЕЙТРАЛЬНО"
        mood_color = "green" if avg_sent > 0.2 else "red" if avg_sent < -0.2 else "orange"
        st.markdown(f"**Настроение:** <span style='color:{mood_color}; font-size:18px;'>{mood} ({avg_sent:+.2f})</span>", unsafe_allow_html=True)
        st.markdown("---")
        
        for n in news_list:
            if n['sentiment'] > 0.2: sent_emoji, sent_text = "🟢", f"Позитив ({n['sentiment']:+.2f})"
            elif n['sentiment'] < -0.2: sent_emoji, sent_text = "🔴", f"Негатив ({n['sentiment']:+.2f})"
            else: sent_emoji, sent_text = "🟡", f"Нейтрально ({n['sentiment']:+.2f})"
            with st.container():
                st.markdown(f"### {sent_emoji} [{n['title']}]({n['url']})")
                meta = [f"**Сентимент:** {sent_text}"]
                if n['tickers']: meta.append(f"**Тикеры:** {' '.join(['`'+t+'`' for t in n['tickers']])}")
                if n['sector'] != 'general': meta.append(f"**Сектор:** {n['sector']}")
                meta.append("💾 Из базы" if n['source'] == 'db' else "📡 Live")
                st.caption(" • ".join(meta))
                st.divider()

# ==========================================
# 💡 СИГНАЛЫ НА ВЫХОД
# ==========================================
def generate_exit_signals(price, entry, stop, tp1, tp2, tp3, direction, rsi):
    signals = []
    if direction == 'long':
        if price <= stop: signals.append("🔴 СТОП-ЛОСС")
        if price >= tp1: signals.append(f"🟡 Цель 1 ({tp1:.2f})")
        if price >= tp2: signals.append(f"🟢 Цель 2 ({tp2:.2f})")
        if price >= tp3: signals.append(f"🎯 Цель 3 ({tp3:.2f})")
        if rsi > CONFIG['RSI_OVERBOUGHT'] and price > entry * 1.05:
            signals.append(f"⚠️ RSI перекуплен ({rsi:.1f})")
    elif direction == 'short':
        if price >= stop: signals.append("🔴 СТОП-ЛОСС")
        if price <= tp1: signals.append(f"🟡 Цель 1 ({tp1:.2f})")
        if price <= tp2: signals.append(f"🟢 Цель 2 ({tp2:.2f})")
        if price <= tp3: signals.append(f"🎯 Цель 3 ({tp3:.2f})")
        if rsi < CONFIG['RSI_OVERSOLD'] and price < entry * 0.95:
            signals.append(f"⚠️ RSI перепродан ({rsi:.1f})")
    return signals

# ==========================================
# 🎨 ГЛАВНЫЙ ИНТЕРФЕЙС
# ==========================================
def main():
    st.set_page_config(page_title="Макро-Радар МОЕХ v6.0", page_icon="📈", layout="wide")
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
    
    st.title("📈 Макро-Радар МОЕХ v6.0")
    st.caption("**Профессиональный трейдинг-терминал с AI-аналитикой**")
    st.warning("⚠️ Аналитический инструмент. Все решения принимаете самостоятельно.")
    
    now = datetime.now(CONFIG['MSK_TZ'])
    is_open = now.weekday() < 5 and 10 <= now.hour < 24
    st.caption(f"**Статус:** {'🟢 Торги' if is_open else '🔴 Закрыт'} | **Время:** {now.strftime('%H:%M:%S')}")
    
    signals_rows = execute_db_query('SELECT * FROM signals ORDER BY timestamp DESC LIMIT 200', fetch=True) or []
    sig_cols = ['id', 'timestamp', 'ticker', 'name', 'type', 'sector', 'price', 'change_pct',
              'volume', 'avg_volume', 'rsi', 'atr', 'strength', 'news_sentiment', 'forecast_score',
              'entry_price', 'stop_loss', 'take_profit_1', 'take_profit_2', 'take_profit_3',
              'risk_reward', 'position_size', 'trade_direction', 'support_level', 'resistance_level',
              'outcome', 'pnl_pct', 'max_price', 'min_price', 'hours_elapsed', 'checked', 'exit_reason']
    signals = [dict(zip(sig_cols, r)) for r in signals_rows]
    
    ideas_rows = execute_db_query('SELECT * FROM trade_ideas WHERE status="active" ORDER BY timestamp DESC', fetch=True) or []
    idea_cols = ['id', 'timestamp', 'ticker', 'name', 'direction', 'entry_price', 'stop_loss',
                 'take_profit_1', 'take_profit_2', 'take_profit_3', 'risk_reward', 'position_size',
                 'confidence', 'status', 'exit_signal', 'exit_timestamp']
    trade_ideas = [dict(zip(idea_cols, r)) for r in ideas_rows]
    
    checked = [s for s in signals if s['checked'] == 1]
    wins = [s for s in checked if s['outcome'] == 'win']
    losses = [s for s in checked if s['outcome'] == 'loss']
    
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1: st.metric("Сигналов", len(signals))
    with col2: st.metric("Проверено", len(checked))
    with col3:
        wr = len(wins) / max(len(checked), 1) * 100
        st.metric("Win Rate", f"{wr:.1f}%")
    with col4: st.metric("Идей", len(trade_ideas))
    with col5:
        avg_pnl = sum(s['pnl_pct'] for s in checked) / max(len(checked), 1)
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
    
    with tab1: render_best_ideas_dashboard()
    with tab2: render_heatmap_correlation()
    with tab3: render_sector_comparison()
    with tab4: render_quotes_tab()
    
    with tab5:
        st.subheader("Готовые торговые планы")
        if not trade_ideas:
            st.info("Ожидание идей с R:R ≥ 1:2...")
        else:
            for idea in trade_ideas[:10]:
                dir_emoji = "📈" if idea['direction'] == 'long' else "📉"
                css = "trade-long" if idea['direction'] == 'long' else "trade-short"
                df = get_moex_data(idea['ticker'], CONFIG['ASSETS'][idea['ticker']]['type'])
                exit_sigs = []
                if df is not None:
                    cp = df['close'].iloc[-1]
                    rsi = calculate_rsi(df)
                    exit_sigs = generate_exit_signals(cp, idea['entry_price'], idea['stop_loss'],
                        idea['take_profit_1'], idea['take_profit_2'], idea['take_profit_3'],
                        idea['direction'], rsi)
                st.markdown(f'<div class="{css}">', unsafe_allow_html=True)
                c1, c2, c3 = st.columns([2, 1, 1])
                with c1:
                    st.markdown(f"**{dir_emoji} {idea['name']} ({idea['ticker']})**")
                    st.caption(f"**{idea['direction'].upper()}** | Уверенность: {idea['confidence']:.0f}%")
                with c2: st.metric("Вход", f"{idea['entry_price']:.2f}")
                with c3: st.metric("R:R", f"1:{idea['risk_reward']:.1f}")
                st.markdown("---")
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.markdown("**🛑 Стоп**")
                    st.markdown(f"<span style='color:#ff4444; font-size:20px;'>{idea['stop_loss']:.2f}</span>", unsafe_allow_html=True)
                with c2:
                    st.markdown("**🎯 Цель 1**")
                    st.markdown(f"<span style='color:#ffaa00; font-size:20px;'>{idea['take_profit_1']:.2f}</span>", unsafe_allow_html=True)
                with c3:
                    st.markdown("**🎯 Цель 2**")
                    st.markdown(f"<span style='color:#00ff00; font-size:20px;'>{idea['take_profit_2']:.2f}</span>", unsafe_allow_html=True)
                with c4:
                    st.markdown("**🎯 Цель 3**")
                    st.markdown(f"<span style='color:#00ffff; font-size:20px;'>{idea['take_profit_3']:.2f}</span>", unsafe_allow_html=True)
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
                de = "📈" if sig['trade_direction'] == 'long' else "📉" if sig['trade_direction'] == 'short' else "⚖️"
                with st.expander(f"{de} {sig['name']} | {sig['change_pct']:+.2f}% | Прогноз: {sig['forecast_score']:.0f}%", expanded=False):
                    c1, c2, c3, c4, c5 = st.columns(5)
                    with c1: st.metric("Цена", f"{sig['price']:.2f}")
                    with c2: st.metric("RSI", f"{sig['rsi']:.1f}")
                    with c3: st.metric("ATR", f"{sig['atr']:.2f}")
                    with c4: st.metric("Направление", sig['trade_direction'].upper())
                    with c5: st.metric("R:R", f"1:{sig['risk_reward']:.1f}")
                    st.markdown(f"**Вход:** {sig['entry_price']:.2f} | **Стоп:** {sig['stop_loss']:.2f}")
                    st.markdown(f"**Цели:** {sig['take_profit_1']:.2f} / {sig['take_profit_2']:.2f} / {sig['take_profit_3']:.2f}")
    
    with tab7:
        st.subheader("Активные позиции")
        if not trade_ideas:
            st.info("Нет позиций")
        else:
            for idea in trade_ideas:
                df = get_moex_data(idea['ticker'], CONFIG['ASSETS'][idea['ticker']]['type'])
                if df is not None:
                    cp = df['close'].iloc[-1]
                    pnl = ((cp - idea['entry_price']) / idea['entry_price'] * 100) if idea['direction'] == 'long' else ((idea['entry_price'] - cp) / idea['entry_price'] * 100)
                    color = "green" if pnl >= 0 else "red"
                    st.markdown(f'<div class="{"outcome-win" if pnl >= 0 else "outcome-loss"}">', unsafe_allow_html=True)
                    c1, c2, c3 = st.columns([2, 1, 1])
                    with c1:
                        st.markdown(f"**{idea['name']}** ({idea['ticker']})")
                        st.caption(f"Вход: {idea['entry_price']:.2f}")
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
                avg_win = sum(s['pnl_pct'] for s in wins) / max(len(wins), 1)
                st.metric("Ср. прибыль", f"{avg_win:+.2f}%")
            with c3:
                avg_loss = sum(s['pnl_pct'] for s in losses) / max(len(losses), 1)
                st.metric("Ср. убыток", f"{avg_loss:+.2f}%")
            with c4:
                tw = sum(s['pnl_pct'] for s in wins)
                tl = sum(s['pnl_pct'] for s in losses)
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
            stats = df_checked.groupby('ticker').agg({
                'outcome': lambda x: (x == 'win').sum() / len(x) * 100,
                'pnl_pct': 'mean', 'id': 'count'
            }).round(2)
            stats.columns = ['Win Rate %', 'Ср. P&L %', 'Кол-во']
            st.dataframe(stats.sort_values('Win Rate %', ascending=False), use_container_width=True)
    
    with tab9: render_news_tab()
    
    with tab10:
        st.subheader("📜 История")
        if not signals:
            st.info("Пусто")
        else:
            c1, c2, c3 = st.columns(3)
            with c1: fo = st.selectbox("Исход", ["Все", "win", "loss", "neutral", "pending"], key="h_out")
            with c2: ft = st.selectbox("Тикер", ["Все"] + list(set(s['ticker'] for s in signals)), key="h_tick")
            with c3: fd = st.selectbox("Направление", ["Все", "long", "short", "neutral"], key="h_dir")
            filtered = signals
            if fo != "Все": filtered = [s for s in filtered if s['outcome'] == fo]
            if ft != "Все": filtered = [s for s in filtered if s['ticker'] == ft]
            if fd != "Все": filtered = [s for s in filtered if s['trade_direction'] == fd]
            st.markdown(f"Найдено: **{len(filtered)}**")
            for sig in filtered[:30]:
                em = "✅" if sig['outcome'] == 'win' else "❌" if sig['outcome'] == 'loss' else "⏳"
                cls = f"outcome-{sig['outcome']}" if sig['outcome'] in ['win', 'loss'] else ""
                st.markdown(f'<div class="{cls}">', unsafe_allow_html=True)
                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                with c1:
                    st.markdown(f"**{em} {sig['name']}** ({sig['ticker']})")
                    st.caption(sig['trade_direction'])
                with c2: st.metric("Вход", f"{sig['entry_price']:.2f}")
                with c3:
                    if sig['checked']:
                        c = "green" if sig['pnl_pct'] >= 0 else "red"
                        st.markdown(f"<span style='color:{c};'>{sig['pnl_pct']:+.2f}%</span>", unsafe_allow_html=True)
                with c4: st.markdown(f"**{sig['outcome']}**")
                st.markdown('</div>', unsafe_allow_html=True)
                st.divider()

if __name__ == "__main__":
    main()
