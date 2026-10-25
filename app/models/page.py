from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.db.base import Base


class Page(Base):
    __tablename__ = "pages"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    url = Column(String, nullable=False, index=True)
    content_hash = Column(String, nullable=True)
    raw_html = Column(Text, nullable=True)
    cleaned_text = Column(Text, nullable=True)
    status_code = Column(Integer, nullable=True)
    source_type = Column(String, default="portal")  # portal or reddit
    crawled_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    company = relationship("Company", back_populates="pages")
    chunks = relationship("Chunk", back_populates="page", cascade="all, delete-orphan")
