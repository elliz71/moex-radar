#!/bin/bash
echo "📈 Запуск Макро-Радара МОЕХ..."

# Проверка виртуального окружения
if [ ! -d "venv" ]; then
    echo "⚠️ Виртуальное окружение не найдено. Создаю..."
    python3 -m venv venv
fi

# Активация venv
source venv/bin/activate

# Установка зависимостей (если нужно)
pip install -q -r requirements.txt

# Запуск Streamlit
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
