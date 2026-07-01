#!/bin/bash
echo "🧹 Очистка проекта..."

# Удаление кэша Streamlit
rm -rf ~/.streamlit/cache

# Удаление базы данных (ОСТОРОЖНО!)
# read -p "Удалить базу данных? (y/n): " confirm
# if [ "$confirm" = "y" ]; then
#     rm -f signals.db
#     echo "✅ База данных удалена"
# fi

# Удаление Python кэша
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -type f -name "*.pyc" -delete

echo "✅ Очистка завершена"
