from pydantic import BaseModel, HttpUrl
from datetime import datetime
from typing import Optional


class CompanyCreate(BaseModel):
    name: Optional[str] = None
    base_url: HttpUrl


class CompanyRead(BaseModel):
    id: int
    name: str
    base_url: str
    domain: str
    status: str
    created_at: datetime
    last_crawled_at: Optional[datetime] = None

    class Config:
        from_attributes = True
