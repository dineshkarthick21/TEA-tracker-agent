import os
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

load_dotenv()

# Prefer separate DB_* variables; fall back to a single DATABASE_URL
if os.getenv("DB_HOST"):
    connection_url = URL.create(
        drivername="mysql+pymysql",
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", 3306)),
        database=os.getenv("DB_NAME"),
    )
elif os.getenv("DATABASE_URL"):
    connection_url = make_url(os.getenv("DATABASE_URL"))
else:
    raise RuntimeError("Database not configured: set DB_HOST/DB_USER/DB_PASSWORD/DB_PORT/DB_NAME or DATABASE_URL")

connect_args = {
    "ssl": {"ssl_mode": "REQUIRED"}
}

engine = create_engine(
    connection_url,
    connect_args=connect_args,
    pool_recycle=3600,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()