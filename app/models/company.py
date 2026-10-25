from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum
from app.db.base import Base


class CompanyStatus(str, enum.Enum):
    PENDING = "pending"
    CRAWLING = "crawling"
    READY = "ready"
    FAILED = "failed"


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    base_url = Column(String, nullable=False)
    domain = Column(String, nullable=False, index=True)
    status = Column(Enum(CompanyStatus), default=CompanyStatus.PENDING, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_crawled_at = Column(DateTime, nullable=True)

    # Relationships
    owner = relationship("User", back_populates="companies")
    crawl_jobs = relationship("CrawlJob", back_populates="company", cascade="all, delete-orphan")
    pages = relationship("Page", back_populates="company", cascade="all, delete-orphan")
    chunks = relationship("Chunk", back_populates="company", cascade="all, delete-orphan")
    chat_sessions = relationship("ChatSession", back_populates="company", cascade="all, delete-orphan")
