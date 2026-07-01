import streamlit as st
import requests
import pandas as pd
import feedparser
import time
import sqlite3
import logging
from datetime import datetime, timedelta
import pytz
import threading
from typing import Optional, Dict, List
import json

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# ⚙️ КОНФИГУРАЦИЯ
# ==========================================
CONFIG = {
    'ASSETS': {
        'SBER': {'type': 'stock', 'name': 'Сбербанк'},
        'GAZP': {'type': 'stock', 'name': 'Газпром'},
        'LKOH': {'type': 'stock', 'name': 'Лукойл'},
        'YNDX': {'type': 'stock', 'name': 'Яндекс'},
        'ROSN': {'type': 'stock', 'name': 'Роснефть'},
        'PLZL': {'type': 'stock', 'name': 'Полюс'},
        'BR0':  {'type': 'futures', 'name': 'Нефть Brent'},
        'GD0':  {'type': 'futures', 'name': 'Золото'},
        'Si0':  {'type': 'futures', 'name': 'Доллар/Рубль'}
    },
    'INTERVAL': 10,
    'VOLUME_MULTIPLIER': 2.5,
    'PRICE_CHANGE_THRESHOLD': 1.2,
    'RSI_OVERSOLD': 30,
    'RSI_OVERBOUGHT': 70,
    'NEWS_FEED_URL': "https://rssexport.rbc.ru/rbcnews/news/20/full",
    'MSK_TZ': pytz.timezone('Europe/Moscow'),
    'MAX_SIGNALS': 50,
    'CACHE_TTL': 30  # Кэш на 30 секунд
}

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# ==========================================
# 🗄️ БАЗА ДАННЫХ
# ==========================================
def init_db():
    """Инициализация базы данных для хранения истории сигналов"""
    conn = sqlite3.connect('signals.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            ticker TEXT,
            name TEXT,
            asset_type TEXT,
            price REAL,
            change_pct REAL,
            volume REAL,
            avg_volume REAL,
            rsi REAL,
            signal_strength TEXT
        )
    ''')
    conn.commit()
    return conn

def save_signal(conn, signal_data: Dict):
    """Сохранение сигнала в базу"""
    c = conn.cursor()
    c.execute('''
        INSERT INTO signals (timestamp, ticker, name, asset_type, price, change_pct, volume, avg_volume, rsi, signal_strength)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        signal_data['timestamp'],
        signal_data['ticker'],
        signal_data['name'],
        signal_data['type'],
        signal_data['price'],
        signal_data['change_pct'],
        signal_data['volume'],
        signal_data['avg_volume'],
        signal_data.get('rsi', 0),
        signal_data.get('strength', 'medium')
    ))
    conn.commit()

def load_signals(conn, limit: int = 50) -> List[Dict]:
    """Загрузка последних сигналов"""
    c = conn.cursor()
    c.execute('''
        SELECT * FROM signals 
        ORDER BY timestamp DESC 
        LIMIT ?
    ''', (limit,))
    
    columns = ['id', 'timestamp', 'ticker', 'name', 'type', 'price', 'change_pct', 
               'volume', 'avg_volume', 'rsi', 'strength']
    return [dict(zip(columns, row)) for row in c.fetchall()]

# ==========================================
# 📊 РАБОТА С MOEX API
# ==========================================
@st.cache_data(ttl=CONFIG['CACHE_TTL'])
def get_moex_data(ticker: str, asset_type: str) -> Optional[pd.DataFrame]:
    """Получение данных с MOEX с кэшированием и retry-логикой"""
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
                df = pd.DataFrame(data['candles']['data'], columns=data['candles']['columns'])
                return df
                
        except requests.exceptions.RequestException as e:
            logger.warning(f"Попытка {attempt + 1}/{max_retries} для {ticker} не удалась: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Экспоненциальная задержка
            continue
        except Exception as e:
            logger.error(f"Ошибка обработки данных для {ticker}: {e}")
            break
    
    return None

def calculate_rsi(df: pd.DataFrame, period: int = 14) -> float:
    """Расчёт индикатора RSI"""
    if len(df) < period:
        return 50.0  # Нейтральное значение
    
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0

def is_market_open() -> bool:
    """Проверка, открыт ли рынок"""
    now = datetime.now(CONFIG['MSK_TZ'])
    return now.weekday() < 5 and 10 <= now.hour < 24

# ==========================================
# 🤖 ФОНОВЫЙ МОНИТОРИНГ
# ==========================================
def background_monitor():
    """Фоновый процесс мониторинга"""
    conn = init_db()
    alerted_candles = {}
    
    while True:
        try:
            if is_market_open():
                for ticker, info in CONFIG['ASSETS'].items():
                    df = get_moex_data(ticker, info['type'])
                    
                    if df is not None and len(df) >= 5:
                        current_volume = df['volume'].iloc[-1]
                        current_close = df['close'].iloc[-1]
                        prev_close = df['close'].iloc[-2]
                        candle_time = df['begin'].iloc[-1]
                        
                        # Защита от дублирования
                        if alerted_candles.get(ticker) == candle_time:
                            continue
                        
                        avg_volume = df['volume'].iloc[:-1].mean()
                        price_change_pct = ((current_close - prev_close) / prev_close) * 100
                        
                        # Проверка условий аномалии
                        volume_anomaly = current_volume > (avg_volume * CONFIG['VOLUME_MULTIPLIER'])
                        price_anomaly = abs(price_change_pct) >= CONFIG['PRICE_CHANGE_THRESHOLD']
                        
                        if volume_anomaly and price_anomaly:
                            # Расчёт RSI для оценки силы сигнала
                            rsi = calculate_rsi(df)
                            
                            # Определение силы сигнала
                            strength = 'strong' if abs(price_change_pct) > 3.0 else 'medium'
                            if rsi < CONFIG['RSI_OVERSOLD'] or rsi > CONFIG['RSI_OVERBOUGHT']:
                                strength = 'strong'
                            
                            signal = {
                                'timestamp': datetime.now(CONFIG['MSK_TZ']).isoformat(),
                                'ticker': ticker,
                                'name': info['name'],
                                'type': info['type'],
                                'price': float(current_close),
                                'change_pct': float(price_change_pct),
                                'volume': float(current_volume),
                                'avg_volume': float(avg_volume),
                                'rsi': rsi,
                                'strength': strength
                            }
                            
                            save_signal(conn, signal)
                            alerted_candles[ticker] = candle_time
                            logger.info(f"Обнаружен сигнал: {ticker} {price_change_pct:+.2f}%")
                    
                    time.sleep(1)  # Пауза между запросами
                
                time.sleep(15)  # Основной цикл каждые 15 секунд
            else:
                time.sleep(60)  # Спим, если рынок закрыт
                
        except Exception as e:
            logger.error(f"Критическая ошибка в мониторинге: {e}")
            time.sleep(30)

# ==========================================
# 🎨 ИНТЕРФЕЙС
# ==========================================
def main():
    st.set_page_config(
        page_title="Макро-Радар МОЕХ",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Кастомные стили
    st.markdown("""
    <style>
        .main { background-color: #0e1117; }
        .stAlert { background-color: #262730; }
        div[data-testid="stMetricValue"] { font-size: 24px; }
        .signal-strong { border-left: 4px solid #00ff00; padding-left: 10px; }
        .signal-medium { border-left: 4px solid #ffaa00; padding-left: 10px; }
    </style>
    """, unsafe_allow_html=True)
    
    # Инициализация состояния
    if 'monitor_running' not in st.session_state:
        st.session_state.monitor_running = False
        thread = threading.Thread(target=background_monitor, daemon=True)
        thread.start()
        st.session_state.monitor_running = True
        logger.info("Фоновый мониторинг запущен")
    
    # Заголовок
    st.title("📈 Макро-Радар Московской Биржи")
    
    market_status = "🟢 Торги идут" if is_market_open() else "🔴 Рынок закрыт"
    st.caption(f"**Статус:** {market_status} | **Последнее обновление:** {datetime.now().strftime('%H:%M:%S')}")
    
    # Боковая панель
    with st.sidebar:
        st.header("⚙️ Настройки")
        st.metric("Отслеживаемых активов", len(CONFIG['ASSETS']))
        st.metric("Таймфрейм", f"{CONFIG['INTERVAL']} мин")
        st.metric("Порог объема", f"x{CONFIG['VOLUME_MULTIPLIER']}")
        st.metric("Порог цены", f"{CONFIG['PRICE_CHANGE_THRESHOLD']}%")
        
        st.markdown("---")
        st.subheader("📊 Фильтры")
        filter_type = st.selectbox("Тип актива", ["Все", "Акции", "Фьючерсы"])
        filter_strength = st.selectbox("Сила сигнала", ["Все", "Сильные", "Средние"])
        
        st.markdown("---")
        if st.button("🔄 Обновить данные"):
            st.rerun()
    
    # Загрузка сигналов
    conn = init_db()
    signals = load_signals(conn)
    
    # Применение фильтров
    if filter_type == "Акции":
        signals = [s for s in signals if s['type'] == 'stock']
    elif filter_type == "Фьючерсы":
        signals = [s for s in signals if s['type'] == 'futures']
    
    if filter_strength == "Сильные":
        signals = [s for s in signals if s['strength'] == 'strong']
    elif filter_strength == "Средние":
        signals = [s for s in signals if s['strength'] == 'medium']
    
    # Метрики
    col1, col2, col3, col4 = st.columns(4)
    today_signals = [s for s in signals if datetime.fromisoformat(s['timestamp']).date() == datetime.now().date()]
    
    with col1:
        st.metric("Всего сигналов", len(signals))
    with col2:
        st.metric("Сегодня", len(today_signals))
    with col3:
        strong_count = len([s for s in signals if s['strength'] == 'strong'])
        st.metric("Сильных сигналов", strong_count)
    with col4:
        positive = len([s for s in today_signals if s['change_pct'] > 0])
        negative = len(today_signals) - positive
        st.metric("Рост / Падение", f"{positive} / {negative}")
    
    st.markdown("---")
    
    # Вкладки
    tab1, tab2, tab3, tab4 = st.tabs([
        "🚨 Сигналы", 
        "📰 Новости", 
        "📊 Все активы",
        "📈 Статистика"
    ])
    
    with tab1:
        st.subheader("Обнаруженные аномалии")
        
        if not signals:
            st.info("🔍 Радар сканирует рынок... Ожидание аномальных объемов.")
        else:
            for sig in signals[:20]:  # Показываем последние 20
                emoji = "🚀" if sig['change_pct'] > 0 else "🩸"
                strength_class = "signal-strong" if sig['strength'] == 'strong' else "signal-medium"
                
                with st.container():
                    st.markdown(f'<div class="{strength_class}">', unsafe_allow_html=True)
                    
                    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                    
                    with col1:
                        st.markdown(f"**{emoji} {sig['name']}** ({sig['ticker']})")
                        st.caption(f"{datetime.fromisoformat(sig['timestamp']).strftime('%d.%m %H:%M')}")
                    
                    with col2:
                        st.metric("Цена", f"{sig['price']:.2f}")
                    
                    with col3:
                        st.metric("Изменение", f"{sig['change_pct']:+.2f}%")
                    
                    with col4:
                        st.metric("RSI", f"{sig['rsi']:.1f}")
                    
                    st.caption(f"Объем: {sig['volume']:,.0f} (средний: {sig['avg_volume']:,.0f}) | Сила: {sig['strength'].upper()}")
                    st.markdown('</div>', unsafe_allow_html=True)
                    st.divider()
    
    with tab2:
        st.subheader("Макроэкономические новости")
        
        try:
            feed = feedparser.parse(CONFIG['NEWS_FEED_URL'])
            keywords = ['цб', 'ставк', 'нефт', 'brent', 'золот', 'доллар', 'рубл', 'санкц', 'инфляц']
            
            count = 0
            for entry in feed.entries[:20]:
                title_lower = entry.title.lower()
                if any(kw in title_lower for kw in keywords):
                    with st.container():
                        st.markdown(f"### [{entry.title}]({entry.link})")
                        if hasattr(entry, 'published'):
                            st.caption(f"📅 {entry.published}")
                        st.divider()
                        count += 1
                        if count >= 10:
                            break
            
            if count == 0:
                st.info("Релевантных новостей пока нет")
                
        except Exception as e:
            st.error(f"Ошибка загрузки новостей: {e}")
    
    with tab3:
        st.subheader("Текущее состояние активов")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### 🏭 Акции РФ")
            for ticker, info in CONFIG['ASSETS'].items():
                if info['type'] == 'stock':
                    df = get_moex_data(ticker, info['type'])
                    if df is not None and len(df) > 0:
                        current_price = df['close'].iloc[-1]
                        prev_price = df['close'].iloc[-2] if len(df) > 1 else current_price
                        change = ((current_price - prev_price) / prev_price) * 100
                        
                        col_a, col_b = st.columns([2, 1])
                        with col_a:
                            st.write(f"**{info['name']}** ({ticker})")
                        with col_b:
                            color = "green" if change >= 0 else "red"
                            st.markdown(f"<span style='color:{color}; font-size:18px;'>{change:+.2f}%</span>", unsafe_allow_html=True)
                    time.sleep(0.5)
        
        with col2:
            st.markdown("#### 🌍 Сырье и Валюта")
            for ticker, info in CONFIG['ASSETS'].items():
                if info['type'] == 'futures':
                    df = get_moex_data(ticker, info['type'])
                    if df is not None and len(df) > 0:
                        current_price = df['close'].iloc[-1]
                        prev_price = df['close'].iloc[-2] if len(df) > 1 else current_price
                        change = ((current_price - prev_price) / prev_price) * 100
                        
                        col_a, col_b = st.columns([2, 1])
                        with col_a:
                            st.write(f"**{info['name']}** ({ticker})")
                        with col_b:
                            color = "green" if change >= 0 else "red"
                            st.markdown(f"<span style='color:{color}; font-size:18px;'>{change:+.2f}%</span>", unsafe_allow_html=True)
                    time.sleep(0.5)
    
    with tab4:
        st.subheader("Статистика сигналов")
        
        if signals:
            df_stats = pd.DataFrame(signals)
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### По типам активов")
                type_counts = df_stats['type'].value_counts()
                st.bar_chart(type_counts)
            
            with col2:
                st.markdown("#### По силе сигналов")
                strength_counts = df_stats['strength'].value_counts()
                st.bar_chart(strength_counts)
            
            st.markdown("#### Распределение изменений цены")
            st.histogram(df_stats['change_pct'], bins=20)
            
            # Экспорт данных
            st.markdown("---")
            csv = df_stats.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Скачать историю сигналов (CSV)",
                data=csv,
                file_name=f"signals_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
        else:
            st.info("Недостаточно данных для статистики")
    
    # Автообновление каждые 30 секунд
    time.sleep(30)
    st.rerun()

if __name__ == "__main__":
    main()
