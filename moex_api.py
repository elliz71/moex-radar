import streamlit as st
import requests
import pandas as pd
import time
import logging
from typing import Optional
from config import CONFIG, HEADERS

logger = logging.getLogger(__name__)


# ==========================================
# 📊 MOEX API - Загрузка котировок
# ==========================================
def fetch_moex_data_raw(ticker: str, asset_type: str) -> Optional[pd.DataFrame]:
    """Загрузка данных с Мосбиржи с повторными попытками"""
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
    """Загрузка данных с кэшированием"""
    return fetch_moex_data_raw(ticker, asset_type)


# ==========================================
# 🇷🇺 ЗАГРУЗКА ВСЕХ АКЦИЙ МОСБИРЖИ
# ==========================================
def _guess_sector(ticker, name):
    """Определение сектора по тикеру/названию"""
    name_lower = (name or '').lower()
    ticker_lower = (ticker or '').lower()
    text = name_lower + ' ' + ticker_lower
    
    if any(w in text for w in ['банк', 'bank', 'сбер', 'втб', 'тбанк', 'альфа', 'росбанк', 'открыт']):
        return 'bank'
    elif any(w in text for w in ['нефть', 'газ', 'oil', 'gas', 'лукойл', 'роснефть', 'татнефть', 'сургут', 'башнефть']):
        return 'energy'
    elif any(w in text for w in ['золот', 'gold', 'полюс', 'полиметалл', 'селигдар']):
        return 'gold'
    elif any(w in text for w in ['алроса', 'алмаз']):
        return 'diamonds'
    elif any(w in text for w in ['сталь', 'металл', 'steel', 'металлоинвест', 'северсталь', 'ммк', 'нлмк', 'евраз', 'норникель', 'русал']):
        return 'metals'
    elif any(w in text for w in ['яндекс', 'ozon', 'циан', 'астрон', 'headhunter', 'софт', 'posit']):
        return 'tech'
    elif any(w in text for w in ['аэрофлот', 'авиа', 'совкомфлот', 'трансконтейнер']):
        return 'transport'
    elif any(w in text for w in ['магнит', 'x5', 'дикси', 'лента', 'м.видео', 'детск', 'черкизов']):
        return 'retail'
    elif any(w in text for w in ['фарм', 'pharm', 'апрель', 'протек', 'фармстандарт']):
        return 'pharma'
    elif any(w in text for w in ['мечел', 'уголь', 'coal', 'распадская', 'кузбасс', 'en+']):
        return 'mining'
    elif any(w in text for w in ['телеком', 'telecom', 'мтс', 'ростелеком', 'мегафон', 'вымпелком']):
        return 'telecom'
    elif any(w in text for w in ['пик', 'самолет', 'лср', 'эталон', 'девелоп', 'строй', 'галс']):
        return 'realestate'
    elif any(w in text for w in ['электро', 'энерг', 'сет', 'россети', 'интер рао', 'rushydro', 'огк', 'тгк']):
        return 'utilities'
    elif any(w in text for w in ['удобр', 'фосагро', 'акрон', 'хим', 'uralkali', 'уралкалий']):
        return 'chemicals'
    else:
        return 'other'


def fetch_all_moex_stocks():
    """Загрузка полного списка акций с Мосбиржи"""
    try:
        url = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json"
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        securities = data.get('securities', {})
        sec_data = securities.get('data', [])
        sec_columns = securities.get('columns', [])
        
        if not sec_data:
            logger.error("Пустой список акций от MOEX")
            return []
        
        df = pd.DataFrame(sec_data, columns=sec_columns)
        
        # Фильтрация только акций
        if 'SEC_TYPE' in df.columns:
            valid_types = ['common_share', 'preferred_share', '']
            stocks = df[df['SEC_TYPE'].isin(valid_types) | df['SEC_TYPE'].isna()].copy()
        else:
            stocks = df.copy()
        
        # Исключаем ETF, облигации
        if 'SECNAME' in stocks.columns:
            exclude_patterns = ['etf', 'ofz', 'офз', 'флоат', 'фонд', 'облиг', 'bond', 'pkb', 'индекс']
            for pattern in exclude_patterns:
                stocks = stocks[~stocks['SECNAME'].str.lower().str.contains(pattern, na=False)]
        
        if 'ISIN' in stocks.columns:
            stocks = stocks[stocks['ISIN'].str.startswith('RU', na=False)]
        
        # Рыночные данные
        marketdata = data.get('marketdata', {})
        md_data = marketdata.get('data', [])
        md_columns = marketdata.get('columns', [])
        
        if md_data:
            md_df = pd.DataFrame(md_data, columns=md_columns)
            stocks = stocks.merge(md_df, on='SECID', how='left')
        
        # Сортировка по объёму
        if 'VALTODAY' in stocks.columns:
            stocks['VALTODAY'] = pd.to_numeric(stocks['VALTODAY'], errors='coerce').fillna(0)
            stocks = stocks.sort_values('VALTODAY', ascending=False)
        
        result = []
        for _, row in stocks.iterrows():
            ticker = row.get('SECID', '')
            if not ticker or ticker in CONFIG['CORE_ASSETS']:
                continue
            
            name = row.get('SHORTNAME', row.get('SECNAME', ticker))
            sector = _guess_sector(ticker, name)
            volume_today = row.get('VALTODAY', 0)
            last_price = row.get('LAST', 0)
            
            result.append({
                'ticker': ticker,
                'name': name,
                'sector': sector,
                'type': 'stock',
                'volatility': 'medium',
                'volume_today': float(volume_today) if volume_today else 0,
                'last_price': float(last_price) if last_price else 0
            })
        
        logger.info(f"✅ Загружено {len(result)} акций с Мосбиржи")
        return result
    
    except Exception as e:
        logger.error(f"Ошибка загрузки списка акций: {e}")
        return []


@st.cache_data(ttl=300)
def get_all_stocks_catalog():
    """Получить каталог всех акций с кэшированием"""
    return fetch_all_moex_stocks()


def load_dynamic_stocks(top_n=None):
    """Загрузка топ-N акций для мониторинга"""
    top_n = top_n or CONFIG.get('MAX_TRACKED_STOCKS', 30)
    
    logger.info(f"🔄 Загрузка топ-{top_n} акций для мониторинга...")
    all_stocks = get_all_stocks_catalog()
    
    if not all_stocks:
        logger.error("❌ Каталог акций пуст!")
        return {}
    
    logger.info(f"📊 В каталоге {len(all_stocks)} акций")
    
    dynamic = {}
    added_count = 0
    
    for stock in all_stocks:
        ticker = stock['ticker']
        
        if ticker in CONFIG['CORE_ASSETS']:
            continue
        
        name_words = stock['name'].lower().split() if stock['name'] else []
        keywords = [ticker.lower()]
        if name_words:
            keywords.append(name_words[0])
        
        dynamic[ticker] = {
            'type': 'stock',
            'name': stock['name'],
            'sector': stock['sector'],
            'keywords': keywords,
            'volatility': stock.get('volatility', 'medium')
        }
        
        added_count += 1
        if added_count >= top_n:
            break
    
    CONFIG['DYNAMIC_STOCKS'] = dynamic
    
    total_monitored = len(CONFIG['CORE_ASSETS']) + len(dynamic) + len(CONFIG['FUTURES'])
    logger.info(f"✅ Загружено {len(dynamic)} динамических акций")
    logger.info(f"📈 Итого для мониторинга: {total_monitored} активов")
    
    return dynamic
