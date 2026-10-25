from sentence_transformers import SentenceTransformer
from typing import List
import numpy as np
from app.core.config import settings

model = None


def get_model():
    global model
    if model is None:
        model = SentenceTransformer(settings.EMBEDDING_MODEL)
    return model


def generate_embeddings(texts: List[str]) -> List[np.ndarray]:
    if not texts:
        return []
    model = get_model()
    embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
    return embeddings.tolist() if hasattr(embeddings, 'tolist') else list(embeddings)
