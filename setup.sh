#!/bin/bash
echo "🚀 Установка Макро-Радара МОЕХ..."

# Обновление pip
python3 -m pip install --upgrade pip

# Установка зависимостей
pip install -r requirements.txt

# Установка автообновления (опционально)
pip install streamlit-autorefresh

echo "✅ Установка завершена!"
echo "Запустите: streamlit run app.py"
