import os
import secrets
import string
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text
from models import Base

# --- НАСТРОЙКИ ПО УМОЛЧАНИЮ ---
DEFAULT_DB_HOST = "db"
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
    encoded_root_pass = quote_plus(root_pass)
    root_url = f"mysql+mysqlconnector://root:{encoded_root_pass}@{db_host}"
    
    try:
        engine = create_engine(root_url)
        with engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {new_db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"))
            
            # Создаем пользователя
            conn.execute(text(f"CREATE USER IF NOT EXISTS '{new_user}'@'%' IDENTIFIED BY '{new_password}';"))
            conn.execute(text(f"ALTER USER '{new_user}'@'%' IDENTIFIED BY '{new_password}';"))
            
            # Выдаем права
            conn.execute(text(f"GRANT ALL PRIVILEGES ON {new_db_name}.* TO '{new_user}'@'%';"))
            conn.execute(text("FLUSH PRIVILEGES;"))
            
            print(f"✔ База данных '{new_db_name}' и пользователь '{new_user}' успешно настроены.")
            return True
    except Exception as e:
        print(f"❌ Ошибка при настройке MySQL: {e}")
        return False

def update_env_file(db_user, db_pass, db_host, db_name):
    """Обновляет .env, сохраняя старые данные (токен и т.д.)."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(base_dir, ".env")
    
    print(f"⏳ Обновление файла: {env_path}")

    # Экранируем пароль для URL
    encoded_pass = quote_plus(db_pass)
    db_url = f"mysql+mysqlconnector://{db_user}:{encoded_pass}@{db_host}/{db_name}"

    # Список ключей, которые мы будем перезаписывать
    db_keys = ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_URL"]
    
    lines_to_keep = []

    # 1. Читаем существующий файл и сохраняем всё, КРОМЕ настроек БД
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                # Если строка пустая или комментарий — оставляем
                if not stripped or stripped.startswith("#"):
                    lines_to_keep.append(line)
                    continue
                
                # Проверяем ключ (до знака =)
                if "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    # Если ключа нет в списке DB_KEYS, значит это токен или группа — оставляем
                    if key not in db_keys:
                        lines_to_keep.append(line)

    # 2. Формируем новые строки для БД
    new_db_lines = [
        f"\n# --- Database Config ---\n",
        f"DB_HOST={db_host}\n",
        f"DB_NAME={db_name}\n",
        f"DB_USER={db_user}\n",
        f"DB_PASSWORD={db_pass}\n",
        f"DB_URL={db_url}\n"
    ]

    # 3. Перезаписываем файл: Старые данные + Новые данные БД
    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines_to_keep)
            # Добавляем перенос строки, если предыдущий блок не заканчивался им
            if lines_to_keep and not lines_to_keep[-1].endswith("\n"):
                f.write("\n")
            f.writelines(new_db_lines)
        
        print("✔ Файл .env успешно обновлен (Token и Group ID сохранены).")
        return db_url
    except Exception as e:
        print(f"❌ Ошибка при записи файла .env: {e}")
        return None

def init_tables(db_url):
    try:
        engine = create_engine(db_url)
        Base.metadata.create_all(engine)
        print("✔ Таблицы SQLAlchemy созданы.")
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

    root_pass = input("Введите пароль ROOT пользователя MySQL: ").strip()
    new_password = generate_password()

    # 1. Создаем ресурсы в MySQL
    if create_mysql_resources(root_pass, db_host, db_name, db_user, new_password):
        
        # 2. Обновляем .env (сохраняя старые данные)
        full_db_url = update_env_file(db_user, new_password, db_host, db_name)
        
        if full_db_url:
            # 3. Создаем таблицы
            init_tables(full_db_url)

            print("\n" + "="*40)
            print("🎉 УСПЕШНО! ДАННЫЕ ОБНОВЛЕНЫ")
            print("="*40)
            print(f"DB_URL: {full_db_url}")
            print(f"User:   {db_user}")
            print(f"Pass:   {new_password}")
            print("="*40)
        else:
            print("⚠ База создана, но не удалось обновить .env")
    else:
        print("\n⛔ Ошибка подключения к MySQL.")

if __name__ == "__main__":
    main()