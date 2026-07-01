import sqlite3
import threading
import logging

# Логгер для этого модуля
logger = logging.getLogger(__name__)

# ==========================================
# 🔒 БЕЗОПАСНАЯ РАБОТА С SQLITE
# ==========================================
DB_LOCK = threading.Lock()


def get_db_connection():
    """Создать подключение к базе данных"""
    return sqlite3.connect('signals.db', check_same_thread=False, timeout=10)


def init_db():
    """Инициализация базы данных: создание всех таблиц"""
    with DB_LOCK:
        conn = get_db_connection()
        try:
            c = conn.cursor()
            
            # Главная таблица сигналов
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
            
            # Миграция: добавляем недостающие колонки если БД уже существует
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
            
            # Таблица анализа новостей
            c.execute('''CREATE TABLE IF NOT EXISTS news_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, title TEXT, url TEXT,
                sentiment_score REAL, related_tickers TEXT, sector_impact TEXT, keywords_found TEXT)''')
            
            # Таблица торговых идей
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
    """Универсальная функция для выполнения SQL-запросов"""
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
