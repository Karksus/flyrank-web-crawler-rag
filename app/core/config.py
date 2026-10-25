from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = Field(default="postgresql+psycopg://postgres:postgres@localhost:5432/company_rag_bot")
    SQL_ECHO: bool = Field(default=False)
    
    # Application
    SECRET_KEY: str = Field(default="your-secret-key-change-in-production")
    APP_NAME: str = Field(default="Company Portal RAG Chatbot")
    DEBUG: bool = Field(default=True)
    
    # Authentication
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60)
    
    # LLM Configuration
    LLM_PROVIDER: str = Field(default="ollama")  # ollama, openrouter, openai, anthropic
    OLLAMA_BASE_URL: str = Field(default="http://localhost:11434")
    OLLAMA_MODEL: str = Field(default="llama3.1:8b")
    OLLAMA_TIMEOUT: int = Field(default=300)
    
    # OpenRouter
    OPENROUTER_API_KEY: str = Field(default="")
    OPENROUTER_BASE_URL: str = Field(default="https://openrouter.ai/api/v1")
    OPENROUTER_MODEL: str = Field(default="google/gemma-4-26b-a4b-it:free")
    OPENROUTER_FALLBACK_MODELS: str = Field(default="recursive/flint-v1.0:free,nvidia/nemotron-3.5-lightning:free,cohere/north-mini-code:free,google/gemma-4-31b-it:free")
    OPENROUTER_MAX_TOKENS: int = Field(default=1200)
    OPENROUTER_TIMEOUT: int = Field(default=300)
    
    # OpenAI
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_BASE_URL: str = Field(default="https://api.openai.com/v1")
    OPENAI_MODEL: str = Field(default="gpt-4o-mini")
    OPENAI_MAX_TOKENS: int = Field(default=1200)
    OPENAI_TIMEOUT: int = Field(default=300)
    
    # Anthropic
    ANTHROPIC_API_KEY: str = Field(default="")
    ANTHROPIC_BASE_URL: str = Field(default="https://api.anthropic.com/v1")
    ANTHROPIC_MODEL: str = Field(default="claude-3-5-haiku-latest")
    ANTHROPIC_MAX_TOKENS: int = Field(default=1200)
    ANTHROPIC_TIMEOUT: int = Field(default=300)
    
    # Embeddings
    EMBEDDING_MODEL: str = Field(default="all-MiniLM-L6-v2")
    EMBEDDING_DEVICE: str = Field(default="cpu")
    
    # Crawling
    CRAWL_MAX_PAGES: int = Field(default=50)
    CRAWL_MAX_DEPTH: int = Field(default=2)
    CRAWL_DELAY: float = Field(default=1.0)
    CRAWL_TIMEOUT: int = Field(default=30)
    CRAWL_USER_AGENT: str = Field(default="CompanyRAGBot/1.0")
    RESPECT_ROBOTS_TXT: bool = Field(default=True)
    
    # RAG
    RAG_TOP_K: int = Field(default=5)
    CHUNK_SIZE: int = Field(default=700)
    CHUNK_OVERLAP: int = Field(default=75)
    
    # Caching
    CACHE_TTL_SECONDS: int = Field(default=300)

    # Public opinion check
    PUBLIC_OPINION_ENABLED: bool = Field(default=True)
    PUBLIC_OPINION_TIMEOUT: int = Field(default=20)
    PUBLIC_OPINION_MAX_ITEMS: int = Field(default=12)
    PUBLIC_OPINION_CACHE_TTL_SECONDS: int = Field(default=1800)
    PUBLIC_OPINION_USER_AGENT: str = Field(default="CompanyRAGBot/1.0 (+public-opinion-check)")
    PUBLIC_OPINION_LLM_MODELS: str = Field(default="poolside/laguna-s-2.1:free,cohere/north-mini-code:free,nvidia/nemotron-3-ultra-550b-a55b:free")

    # Logging
    LOG_LEVEL: str = Field(default="INFO")
    LOG_FILE: str = Field(default="app.log")
    LOG_MAX_BYTES: int = Field(default=10 * 1024 * 1024)
    LOG_BACKUP_COUNT: int = Field(default=5)
    
    # Server
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8000)
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
