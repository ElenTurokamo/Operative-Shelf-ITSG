import os
import secrets
import string
from sqlalchemy import create_engine, text
from dotenv import set_key

from models import Base

DEFAULT_DB_HOST = "localhost"
DEFAULT_DB_NAME = "telegram_bot_db"
DEFAULT_NEW_USER = "bot_admin"

def generate_password(length=20):
    """Генерирует криптографически стойкий пароль."""
    alphabet = string.ascii_letters + string.digits + "!@#%^&*()_+"
    while True:
        password = ''.join(secrets.choice(alphabet) for i in range(length))
        if (any(c.islower() for c in password)
                and any(c.isupper() for c in password)
                and any(c.isdigit() for c in password)):
            return password

def create_mysql_resources(root_pass, db_host, new_db_name, new_user, new_password):
    """Подключается под root, создает БД и пользователя."""
    root_url = f"mysql+mysqlconnector://root:{root_pass}@{db_host}"
    
    try:
        engine = create_engine(root_url)
        with engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {new_db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"))
            
            conn.execute(text(f"CREATE USER IF NOT EXISTS '{new_user}'@'%' IDENTIFIED BY '{new_password}';"))
            conn.execute(text(f"ALTER USER '{new_user}'@'%' IDENTIFIED BY '{new_password}';"))
            
            conn.execute(text(f"GRANT ALL PRIVILEGES ON {new_db_name}.* TO '{new_user}'@'%';"))
            conn.execute(text("FLUSH PRIVILEGES;"))
            
            print(f"✔ База данных '{new_db_name}' и пользователь '{new_user}' успешно настроены.")
            return True
    except Exception as e:
        print(f"❌ Ошибка при настройке MySQL: {e}")
        return False

def update_env_file(db_user, db_pass, db_host, db_name):
    """Записывает данные в .env файл."""
    env_path = ".env"
    
    db_url = f"mysql+mysqlconnector://{db_user}:{db_pass}@{db_host}/{db_name}"

    if not os.path.exists(env_path):
        open(env_path, 'w').close()

    set_key(env_path, "DB_HOST", db_host)
    set_key(env_path, "DB_NAME", db_name)
    set_key(env_path, "DB_USER", db_user)
    set_key(env_path, "DB_PASSWORD", db_pass)
    set_key(env_path, "DB_URL", db_url)
    
    return db_url

def init_tables(db_url):
    """Создает таблицы, используя новые учетные данные."""
    try:
        engine = create_engine(db_url)
        Base.metadata.create_all(engine)
        print("✔ Таблицы SQLAlchemy (Users, Storage, Requests) успешно созданы.")
    except Exception as e:
        print(f"❌ Ошибка при создании таблиц: {e}")

def main():
    print("--- АВТОМАТИЧЕСКАЯ НАСТРОЙКА БД ---")
    
    print(f"По умолчанию Host: {DEFAULT_DB_HOST}, DB Name: {DEFAULT_DB_NAME}, User: {DEFAULT_NEW_USER}")
    use_defaults = input("Использовать настройки по умолчанию? (y/n): ").lower().strip()
    
    if use_defaults == 'n':
        db_host = input("Введите хост БД (например, localhost): ").strip() or DEFAULT_DB_HOST
        db_name = input("Введите имя новой БД: ").strip() or DEFAULT_DB_NAME
        db_user = input("Введите имя нового пользователя БД: ").strip() or DEFAULT_NEW_USER
    else:
        db_host = DEFAULT_DB_HOST
        db_name = DEFAULT_DB_NAME
        db_user = DEFAULT_NEW_USER

    root_pass = input("Введите пароль ROOT пользователя MySQL (для создания базы): ").strip()
    
    new_password = generate_password()

    if create_mysql_resources(root_pass, db_host, db_name, db_user, new_password):
        
        full_db_url = update_env_file(db_user, new_password, db_host, db_name)
        
        init_tables(full_db_url)

        print("\n" + "="*40)
        print("🎉 УСПЕШНО! ДАННЫЕ СОХРАНЕНЫ В .env")
        print("="*40)
        print(f"DB_HOST:     {db_host}")
        print(f"DB_NAME:     {db_name}")
        print(f"DB_USER:     {db_user}")
        print(f"DB_PASSWORD: {new_password}")
        print(f"DB_URL:      {full_db_url}")
        print("="*40)
        print("Сохраните эти данные в надежном месте (они уже в .env).")
    else:
        print("Прекращение установки из-за ошибок MySQL.")

if __name__ == "__main__":
    main()