from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionMaker
import os

from sqlalchemy.ext.asyncio import create_async_engine
import os

DATABASE_URL = (
    f"postgresql+asyncpg://"
    f"{os.environ['POSTGRES_USER']}:"
    f"{os.environ['POSTGRES_PASSWORD']}@"
    f"{os.environ['POSTGRES_HOST']}:"
    f"{os.environ['POSTGRES_PORT']}/"
    f"{os.environ['POSTGRES_DB']}"
)

engine = create_async_engine(DATABASE_URL)

SessionLocal = sessionMaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


