import pytz

# ==========================================
# ⚙️ КОНФИГУРАЦИЯ ПРОЕКТА
# ==========================================
CONFIG = {
    'CORE_ASSETS': {
        'SBER': {'type': 'stock', 'name': 'Сбербанк', 'sector': 'bank', 
                 'keywords': ['сбер', 'банк', 'кредит', 'ипотека', 'дивиденд'], 'volatility': 'medium'},
        'GAZP': {'type': 'stock', 'name': 'Газпром', 'sector': 'energy', 
                 'keywords': ['газпром', 'газ', 'экспорт', 'труба', 'дивиденд'], 'volatility': 'medium'},
        'LKOH': {'type': 'stock', 'name': 'Лукойл', 'sector': 'energy', 
                 'keywords': ['лукойл', 'нефть', 'добыча', 'дивиденд', 'npv'], 'volatility': 'medium'},
        'YNDX': {'type': 'stock', 'name': 'Яндекс', 'sector': 'tech', 
                 'keywords': ['яндекс', 'it', 'технологии', 'регулятор', 'антимонополь'], 'volatility': 'high'},
        'ROSN': {'type': 'stock', 'name': 'Роснефть', 'sector': 'energy', 
                 'keywords': ['роснефть', 'нефть', 'сечин', 'восток', 'дивиденд'], 'volatility': 'medium'},
        'PLZL': {'type': 'stock', 'name': 'Полюс', 'sector': 'metals', 
                 'keywords': ['полюс', 'золото', 'драгметалл', 'добыча'], 'volatility': 'high'},
    },
    'FUTURES': {
        'BR0':  {'type': 'futures', 'name': 'Нефть Brent', 'sector': 'commodity', 
                 'keywords': ['нефть', 'brent', 'opec', 'саудов', 'спот'], 'volatility': 'high'},
        'GD0':  {'type': 'futures', 'name': 'Золото', 'sector': 'commodity', 
                 'keywords': ['золото', 'gold', 'fed', 'инфляц', 'убежищ'], 'volatility': 'medium'},
        'Si0':  {'type': 'futures', 'name': 'Доллар/Рубль', 'sector': 'currency', 
                 'keywords': ['доллар', 'рубль', 'цб', 'курс', 'валют', 'санкц'], 'volatility': 'low'},
    },
    'DYNAMIC_STOCKS': {},
    
    'INTERVAL': 10,
    'VOLUME_MULTIPLIER': 1.8,
    'PRICE_CHANGE_THRESHOLD': 0.7,
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
    'AUTO_LABEL_HOURS': 2,
    'MAX_TRACKED_STOCKS': 30,
}

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}


def get_all_assets():
    """Получить активы для мониторинга (core + dynamic + futures)"""
    assets = {}
    assets.update(CONFIG['CORE_ASSETS'])
    assets.update(CONFIG.get('DYNAMIC_STOCKS', {}))
    assets.update(CONFIG['FUTURES'])
    return assets
