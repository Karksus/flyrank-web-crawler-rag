from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.db.base import Base


class Embedding(Base):
    __tablename__ = "embeddings"

    id = Column(Integer, primary_key=True, index=True)
    chunk_id = Column(Integer, ForeignKey("chunks.id"), nullable=False, unique=True)
    embedding = Column(Vector(384))  # 384 dims for all-MiniLM-L6-v2

    # Relationships
    chunk = relationship("Chunk", back_populates="embedding")
