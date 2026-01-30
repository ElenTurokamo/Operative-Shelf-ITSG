#!/bin/bash
set -e

if [ -z "$BOT_TOKEN" ]; then
  echo "❌ BOT_TOKEN не установлен! Проверьте .env"
  exit 1
fi

echo "🚀 Запуск бота..."
python main.py
