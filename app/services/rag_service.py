from sqlalchemy.orm import Session
from sqlalchemy import text
from app.models.chunk import Chunk
from app.models.embedding import Embedding
from app.models.page import Page
from app.services.embeddings import generate_embeddings
from typing import List, Dict


class RAGService:
    def search_similar(self, db: Session, company_id: int, query: str, top_k: int = 5) -> List[Dict]:
        # Generate query embedding
        query_embedding = generate_embeddings([query])[0]
        
        # Search using pgvector cosine similarity
        # Convert to string format for pgvector
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
        
        sql = text("""
            SELECT 
                c.id as chunk_id,
                c.text,
                p.url,
                p.id as page_id,
                (e.embedding <-> :query_embedding) as distance
            FROM chunks c
            JOIN embeddings e ON e.chunk_id = c.id
            JOIN pages p ON p.id = c.page_id
            WHERE c.company_id = :company_id
            ORDER BY e.embedding <-> :query_embedding
            LIMIT :top_k
        """)
        
        result = db.execute(sql, {
            "query_embedding": embedding_str,
            "company_id": company_id,
            "top_k": top_k
        })
        
        chunks = []
        for row in result:
            chunks.append({
                "chunk_id": row.chunk_id,
                "text": row.text,
                "url": row.url,
                "page_id": row.page_id,
                "distance": row.distance
            })
        
        return chunks


rag_service = RAGService()
