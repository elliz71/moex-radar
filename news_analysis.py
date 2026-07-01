import streamlit as st
import logging
from typing import Tuple, List
from config import CONFIG, get_all_assets

logger = logging.getLogger(__name__)


# ==========================================
# 📰 NLP-АНАЛИЗ НОВОСТЕЙ
# ==========================================

# Словари ключевых слов для определения тональности
POSITIVE_WORDS = {
    'рост', 'повышен', 'увелич', 'прибыл', 'доход', 'дивиденд', 'покуп', 
    'оптимизм', 'успех', 'рекорд', 'превыш', 'прогноз', 'позитив', 
    'поддерж', 'развит', 'инвест', 'сделк', 'партнер', 'экспорт', 
    'спрос', 'дефицит', 'подорожан', 'укрепл'
}

NEGATIVE_WORDS = {
    'пад', 'снижен', 'убыт', 'потерь', 'рис', 'опас', 'негатив', 
    'проблем', 'криз', 'санкц', 'огранич', 'запрет', 'штраф', 'суд', 
    'расслед', 'отказ', 'задерж', 'авар', 'пожар', 'конфликт', 'войн', 
    'эскал', 'инфляц', 'рецесс', 'девальв', 'обвал', 'паник', 
    'распродаж', 'давлен', 'сниж', 'коррекц'
}


@st.cache_data(ttl=60)
def get_cached_assets_for_analysis():
    """Кэшированный список активов для анализа"""
    return get_all_assets()


def analyze_news_sentiment(title, description='') -> Tuple[float, List[str], str, List[str]]:
    """
    Анализ тональности новости
    
    Возвращает: (sentiment_score, found_tickers, sector, found_keywords)
    - sentiment_score: от -1 (очень плохо) до +1 (очень хорошо)
    - found_tickers: список найденных тикеров акций
    - sector: сектор, к которому относится новость
    - found_keywords: какие ключевые слова нашли
    """
    try:
        text = (title + ' ' + description).lower()
        
        # Подсчёт позитивных и негативных слов
        pos_count = sum(1 for w in POSITIVE_WORDS if w in text)
        neg_count = sum(1 for w in NEGATIVE_WORDS if w in text)
        total = pos_count + neg_count
        
        # Расчёт оценки тональности
        sentiment = (pos_count - neg_count) / max(total, 1)
        
        # Поиск упоминаний компаний
        found_tickers, found_keywords, sector = [], [], 'general'
        assets = get_cached_assets_for_analysis()
        
        for ticker, info in assets.items():
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


def calculate_forecast_score(signal_data, news_sentiment, historical_data) -> float:
    """
    Расчёт прогноза успеха сигнала (0-100%)
    
    Учитывает:
    - Изменение цены
    - Объём торгов
    - RSI
    - Тональность новостей
    - Историческую успешность тикера
    """
    try:
        score = 50.0  # Базовая оценка
        
        # 1. Импульс цены (до ±20 баллов)
        price_change = signal_data.get('change_pct', 0)
        price_momentum = min(abs(price_change) * 10, 20)
        score += price_momentum if price_change > 0 else -price_momentum
        
        # 2. Объём торгов (до ±25 баллов)
        volume = signal_data.get('volume', 0)
        avg_volume = signal_data.get('avg_volume', 1)
        if avg_volume > 0:
            volume_factor = min((volume / avg_volume - 1) * 15, 25)
            score += volume_factor if price_change > 0 else -volume_factor
        
        # 3. RSI (±15 баллов)
        rsi = signal_data.get('rsi', 50)
        if rsi < CONFIG['RSI_OVERSOLD']:
            score += 15  # Перепроданность = хорошо для покупки
        elif rsi > CONFIG['RSI_OVERBOUGHT']:
            score -= 15  # Перекупленность = плохо
        
        # 4. Тональность новостей (до ±20 баллов)
        score += (news_sentiment or 0) * 20
        
        # 5. Историческая успешность тикера (до ±20 баллов)
        ticker = signal_data.get('ticker')
        if ticker and historical_data:
            ticker_history = [s for s in historical_data if s.get('ticker') == ticker]
            if len(ticker_history) >= 5:
                success_count = sum(1 for s in ticker_history[-10:] if s.get('change_pct', 0) > 0)
                success_rate = success_count / len(ticker_history[-10:])
                score += (success_rate - 0.5) * 20
        
        # Ограничиваем от 0 до 100
        return max(0, min(100, round(score)))
    
    except Exception as e:
        logger.error(f"Ошибка прогноза: {e}")
        return 50
