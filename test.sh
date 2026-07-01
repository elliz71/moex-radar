#!/bin/bash
echo "🧪 Тестирование компонентов..."

# Проверка Python
python3 --version

# Проверка импортов
python3 -c "import streamlit; print('✅ Streamlit:', streamlit.__version__)"
python3 -c "import pandas; print('✅ Pandas:', pandas.__version__)"
python3 -c "import requests; print('✅ Requests:', requests.__version__)"
python3 -c "import feedparser; print('✅ Feedparser OK')"
python3 -c "import matplotlib; print('✅ Matplotlib:', matplotlib.__version__)"

# Проверка подключения к MOEX
python3 -c "
import requests
url = 'https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/SBER/candles.json?interval=10'
try:
    r = requests.get(url, timeout=5)
    if r.status_code == 200:
        print('✅ MOEX API доступен')
    else:
        print('❌ MOEX API ошибка:', r.status_code)
except Exception as e:
    print('❌ MOEX API недоступен:', str(e))
"

echo "✅ Тестирование завершено"
