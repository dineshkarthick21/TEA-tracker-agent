from datetime import date
from sqlalchemy import Column, Integer, String, Date, Enum
from database import Base

class TeaLog(Base):
    __tablename__ = "tea_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone_number = Column(String(20), nullable=False, index=True)
    user_name = Column(String(100), default="Staff", nullable=False)
    date = Column(Date, default=date.today, nullable=False, index=True)
    session = Column(Enum("morning", "evening"), nullable=False)
    count = Column(Integer, nullable=False, default=1)