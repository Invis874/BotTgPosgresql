import os
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

# Telegram Bot
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env файле")

# Web App URL (для кнопки в боте)
WEBAPP_URL = os.getenv('WEBAPP_URL')
if not WEBAPP_URL:
    raise ValueError("WEBAPP_URL не найден в .env файле")

# GigaChat - Authorization Key (тот самый длинный ключ)
GIGACHAT_CREDENTIALS = os.getenv('GIGACHAT_CREDENTIALS')
if not GIGACHAT_CREDENTIALS:
    raise ValueError("GIGACHAT_CREDENTIALS не найден в .env файле")

# Database (если нужно вынести)
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'dbe')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'example')

# Формируем строку подключения к БД
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"

# Для проверки (первые символы токена, остальное скрыто)
def print_config():
    print(f"✅ Бот токен: {TOKEN[:10]}... (скрыто)")
    print(f"✅ GigaChat ключ: {GIGACHAT_CREDENTIALS[:15]}... (скрыто)")
    print(f"✅ База данных: {DATABASE_URL}")

if __name__ == "__main__":
    print_config()