from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from enum import Enum


class UserBase(BaseModel):
    first_name: str
    last_name: str
    email: str

    class Config:
        from_attributes = True


class UserCreate(UserBase):
    pass


class UserRead(UserBase):
    """A user as returned by read endpoints - includes the primary key."""
    id: int

    class Config:
        from_attributes = True


class User(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class LogStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    fixed = "fixed"
    wontfix = "wontfix"


class LogCreate(BaseModel):
    type: str
    application: str
    message: str
    trace: str = ""
    status: LogStatus = LogStatus.open


class LogRecord(LogCreate):
    guid: str
    datetime: datetime
