ANGELOK HUB — исправленный комплект

Домен уже прописан:
https://bot-1794496165-5480-inedral.bothost.tech

Файлы:
- bot_easy.py — Telegram-бот
- server.py — HTTP API / Mini App backend
- index.html — сайт Angelok Hub
- config.py — настройки
- requirements.txt — зависимости

УСТАНОВКА НА BOTHOST:
1. Остановите проект.
2. Загрузите и замените bot_easy.py, server.py, index.html, config.py, requirements.txt.
3. Не удаляйте angelok_hub.db и другие файлы базы данных.
4. В config.py вставьте НОВЫЙ BOT_TOKEN и НОВЫЙ OPENROUTER_API_KEY.
   Либо задайте переменные BOT_TOKEN и OPENROUTER_API_KEY в переменных окружения Bothost.
5. В настройке HTTP включите сервер, порт 3000, кастомный домен пустой.
6. Главный файл: bot_easy.py
7. Перезапустите проект.

ВАЖНО:
- Старые токены из предыдущего config.py уже раскрывались в переписке. Отзовите их и создайте новые через BotFather и OpenRouter.
- Сайт требует запуска внутри Telegram через кнопку «Открыть Angelok Hub». При открытии обычной ссылкой в Chrome Telegram initData отсутствует, поэтому API отвечает 401.
- OpenRouter без действующего ключа работать не будет.
- Не удаляйте angelok_hub.db: там хранятся данные бота.
