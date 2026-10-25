from typing import List


def chunk_text(text: str, chunk_size: int = 700, chunk_overlap: int = 75) -> List[str]:
    if not text or not text.strip():
        return []
    
    # Simple word-based chunking
    words = text.split()
    if len(words) == 0:
        return []
    
    chunks = []
    start = 0
    
    while start < len(words):
        end = start + chunk_size
        chunk_words = words[start:end]
        chunk = ' '.join(chunk_words)
        if chunk.strip():
            chunks.append(chunk.strip())
        start = end - chunk_overlap
        if start < 0:
            start = 0
        if start >= len(words) - chunk_overlap and len(chunks) > 0:
            break
    
    return chunks
