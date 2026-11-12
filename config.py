# Заполните переменные окружения в панели Bothost.
# Не публикуйте токены в GitHub и не отправляйте их в чаты.
import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "9200223510:AAEfFyRxrhWkFKOva02OZ2aspZ1VXOFR_T0")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "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")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://ВАШ-ДОМЕН.bothost.tech")
WEB_HOST = "0.0.0.0"
WEB_PORT = int(os.getenv("PORT", "3000"))
