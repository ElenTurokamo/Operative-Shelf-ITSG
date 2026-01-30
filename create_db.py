from sqlalchemy import create_engine
from models import Base
from config import DB_URL

def init_db():
    try:
        engine = create_engine(DB_URL)
        Base.metadata.create_all(engine)
        print("---")
        print("Успех: Таблицы Users, Storage и Requests созданы в MySQL.")
        print("---")
    except Exception as e:
        print(f"Ошибка при создании БД: {e}")

if __name__ == "__main__":
    init_db()