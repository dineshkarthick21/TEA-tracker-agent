from datetime import date
from typing import Optional, Literal
from pydantic import BaseModel

class TeaLogBase(BaseModel):
    user_name: Optional[str] = "Staff"
    session: Literal["morning", "evening"]
    count: int = 1

class TeaLogCreate(TeaLogBase):
    phone_number: str
    date: Optional[date] = None

class TeaLogUpdate(BaseModel):
    count: Optional[int] = None
    session: Optional[Literal["morning", "evening"]] = None

class TeaLogResponse(TeaLogBase):
    id: int
    phone_number: str
    date: date

    class Config:
        from_attributes = True