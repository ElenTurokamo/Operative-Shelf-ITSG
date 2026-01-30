import os
from urllib.parse import quote_plus
from dotenv import load_dotenv

# Загружаем переменные из .env (если файл есть)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")

# --- ЛОГИКА ГЕНЕРАЦИИ DB_URL ---
DB_URL = os.getenv("DB_URL")

# Если DB_URL не задан явно, пробуем собрать его из частей
if not DB_URL:
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    db_host = os.getenv("DB_HOST")
    db_name = os.getenv("DB_NAME")

    # Проверяем, что все части есть
    if db_user and db_password and db_host and db_name:
        # ВАЖНО: Экранируем пароль, иначе символы типа @ или : сломают подключение
        encoded_password = quote_plus(db_password)
        
        DB_URL = f"mysql+mysqlconnector://{db_user}:{encoded_password}@{db_host}/{db_name}"
        print(f"🔧 DB_URL сгенерирован автоматически для хоста: {db_host}")
    else:
        # Если чего-то не хватает, оставляем None (вызовет ошибку позже, но понятную)
        print("⚠️ Не удалось сгенерировать DB_URL: не хватает DB_USER, DB_HOST или других переменных.")