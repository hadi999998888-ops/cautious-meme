# Angelok Hub — конфигурация для Bothost
# Вставьте новые ключи в кавычки ИЛИ задайте одноимённые переменные окружения в Bothost.
import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "9200223510:AAEfFyRxrhWkFKOva02OZ2aspZ1VXOFR_T0")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "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")

# Домен вашего проекта Bothost (уже подставлен)
WEBAPP_URL = os.getenv(
    "WEBAPP_URL",
    "https://bot-1794496165-5480-inedral.bothost.tech"
)

WEB_HOST = "0.0.0.0"
WEB_PORT = int(os.getenv("PORT", "3000"))
