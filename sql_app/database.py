from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import config  # Импортируем наш config

# Используем DATABASE_URL из config
engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()