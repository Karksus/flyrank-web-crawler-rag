# FlyRank Web Crawler RAG

A **company portal RAG chatbot** (FlyRank Capstone Project). Submit any public company URL, and the system crawls it, indexes it into a vector database, and lets you chat with answers grounded in that company's own data — with verifiable citations. Multi-tenant: each user owns their company bots.

## What it does

- **Polite web crawling** — `httpx` + `trafilatura` + `BeautifulSoup` + `Playwright`; respects `robots.txt`, crawl-delay, domain boundaries, URL canonicalization, dedup, idempotency; max 50 pages, depth 2. (`app/services/crawler.py:L31`)
- **RAG with citations** — `sentence-transformers` (all-MiniLM-L6-v2, 384 dims) + `pgvector`, cosine similarity, top-k 4-6, citation-first prompting, LLM token/cost logging per message. (`docs/MY_10X_SOLUTION_TEMPLATE.md`)
- **Public opinion check** — Reddit RSS, Hacker News Algolia, Bing News RSS, with LLM sentiment summary. (`app/services/llm_service.py:L491`)
- **Multi-tenant auth** — email + password via `fastapi-users`, `passlib[bcrypt]`, `python-jose[cryptography]`. (`app/api/auth.py`)
- **Local-first LLM** — Ollama over HTTP API; $0 cost, no API keys, all processing local. (`app/services/llm_service.py:L55`)

**Tech stack:** FastAPI, Jinja2 + HTMX, Postgres + pgvector, Ollama, `cachetools`, BackgroundTasks — 34 packages total (`requirements.txt`).

**Data model:** `users`, `companies`, `crawl_jobs`, `pages`, `chunks`, `embeddings`, `chat_sessions`, `messages` (`docs/project_plan.md`).

## How to use

| Page | Purpose |
|------|---------|
| Home | Feature overview (polite crawling, RAG citations, multi-tenant, secure & private) |
| Create Bot | Submit a company URL to spin up a specialized chatbot |
| Dashboard | View your company bots |
| Chat | Company chat with citations + public opinion panel |
| Crawl Status | Live crawl progress, auto-refresh every 5s |
| Login / Register | Email + password auth |

API routes: URL submission, crawl management, chat, bot management, authentication (`app/api/`).

## Setup

1. **Clone & enter the repo**
   ```bash
   git clone https://github.com/Karksus/flyrank-web-crawler-rag.git
   cd flyrank-web-crawler-rag
   ```

2. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env as needed (DATABASE_URL, OLLAMA_BASE_URL, EMBEDDING_MODEL, CRAWL_MAX_PAGES, etc.)
   ```

3. **Start PostgreSQL with pgvector**
   ```bash
   docker compose up -d db
   ```

4. **Install Python dependencies**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

5. **Install Playwright browsers** (for JS-heavy page fallback)
   ```bash
   playwright install
   ```

6. **Choose an LLM provider** (three options):
   - **Ollama (local, free)** — recommended for development:
     ```bash
     ollama pull llama3.1:8b   # or llama3.2:3b, qwen2.5:7b, mistral
     # Ollama runs on http://localhost:11434 by default
     ```
   - **OpenRouter (free tier)** — set `LLM_PROVIDER=openrouter` and `OPENROUTER_API_KEY` in `.env`.
   - **OpenAI / Anthropic (paid)** — set `LLM_PROVIDER=openai` or `anthropic` and the corresponding API key in `.env`.

7. **Run database migrations**
   ```bash
   alembic upgrade head
   ```

8. **Run the app**
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
   Open [http://localhost:8000](http://localhost:8000).

Prerequisites: Python 3.10+, Docker & Docker Compose, 4–8 GB RAM recommended. Plus one LLM provider: Ollama (local), OpenRouter API key (free tier), or OpenAI / Anthropic API key (paid).

## Citation

If you use this software, please cite it as:

```
FlyRank Capstone Team. (2026). FlyRank Web Crawler RAG. https://github.com/Karksus/flyrank-web-crawler-rag
```

Or click **"Cite this repository"** on GitHub for BibTeX, APA, and other formats (powered by `CITATION.cff`).
