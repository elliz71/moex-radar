#!/bin/bash
echo "🔄 Обновление из GitHub..."

# Сохранение текущих изменений
git add .
git commit -m "Auto-backup before update"

# Получение обновлений
git pull origin main

# Переустановка зависимостей
pip install -r requirements.txt

echo "✅ Обновление завершено!"
