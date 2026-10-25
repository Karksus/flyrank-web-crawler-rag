from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
import asyncio
import logging
import time
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from urllib.parse import urlparse
from tldextract import extract
from datetime import datetime, timezone
import hashlib
from app.db.session import get_db
from app.core.config import settings
from app.core.deps import get_current_active_user
from app.models.user import User
from app.models.company import Company, CompanyStatus
from app.models.crawl_job import CrawlJob, CrawlJobStatus
from app.models.page import Page
from app.models.chunk import Chunk
from app.models.embedding import Embedding
from app.schemas.company import CompanyCreate
from app.services.crawler import PoliteCrawler
from app.services.chunker import chunk_text
from app.services.embeddings import generate_embeddings

router = APIRouter(prefix="/companies", tags=["companies"])
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


def get_base_domain(url: str) -> str:
    extracted = extract(url)
    return f"{extracted.domain}.{extracted.suffix}" if extracted.suffix else extracted.domain


@router.get("/create", response_class=HTMLResponse)
async def create_company_page(request: Request, current_user: User = Depends(get_current_active_user)):
    return templates.TemplateResponse("create_bot.html", {"request": request, "user": current_user})


@router.post("/")
async def create_company(
    company_data: CompanyCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    base_url = str(company_data.base_url)
    parsed = urlparse(base_url)
    
    # Ensure it's a root URL (no path except /)
    if parsed.path and parsed.path != '/':
        raise HTTPException(status_code=400, detail="Please provide the root URL only (e.g., https://example.com)")
    
    domain = get_base_domain(base_url)
    if company_data.name:
        name = company_data.name
    else:
        name = domain
    # Ensure no double "Bot"
    if name.endswith(' Bot Bot'):
        name = name.replace(' Bot Bot', ' Bot')
    elif not name.endswith(' Bot') and not name.lower().endswith('bot'):
        name = f"{name} Bot"

    # Create company
    company = Company(
        user_id=current_user.id,
        name=name,
        base_url=base_url,
        domain=domain,
        status=CompanyStatus.PENDING
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    
    # Create crawl job
    crawl_job = CrawlJob(
        company_id=company.id,
        status=CrawlJobStatus.PENDING
    )
    db.add(crawl_job)
    db.commit()
    db.refresh(crawl_job)
    
    # Start crawling in background
    background_tasks.add_task(run_crawl, company.id, crawl_job.id, base_url)
    
    return {"message": "Bot created and crawling started", "company_id": company.id, "redirect": f"/companies/{company.id}/status"}


def run_crawl(company_id: int, crawl_job_id: int, start_url: str):
    """Crawl a company portal and ingest it.

    This is intentionally a *sync* function: Starlette runs sync background
    tasks in a worker thread, so the event loop keeps serving status requests
    while the crawl/embedding work is happening.
    """
    from app.db.session import SessionLocal

    db = SessionLocal()
    started = time.monotonic()
    crawl_job = db.query(CrawlJob).filter(CrawlJob.id == crawl_job_id).first()
    company = db.query(Company).filter(Company.id == company_id).first()

    logger.info(
        "Crawl job %s starting for company %s (%s)", crawl_job_id, company_id, start_url
    )

    try:
        if not crawl_job:
            logger.error("Crawl job %s does not exist; aborting", crawl_job_id)
            return
        if not company:
            logger.error("Company %s does not exist; aborting crawl job %s", company_id, crawl_job_id)
            return

        crawl_job.status = CrawlJobStatus.RUNNING
        crawl_job.started_at = datetime.now(timezone.utc)
        crawl_job.pages_crawled = 0
        crawl_job.pages_total = 0
        crawl_job.error = None
        company.status = CompanyStatus.CRAWLING
        db.commit()

        logger.info(
            "Crawl job %s config: max_pages=%s max_depth=%s delay=%ss timeout=%ss",
            crawl_job_id, settings.CRAWL_MAX_PAGES, settings.CRAWL_MAX_DEPTH,
            settings.CRAWL_DELAY, settings.CRAWL_TIMEOUT,
        )

        # Load the embedding model *before* crawling. If the model cannot be
        # loaded/downloaded we fail fast with a clear log entry instead of
        # losing the first page half-way through ingestion.
        from app.services.embeddings import get_model

        model_started = time.monotonic()
        logger.info("Loading embedding model %s", settings.EMBEDDING_MODEL)
        get_model()
        logger.info("Embedding model ready in %.1fs", time.monotonic() - model_started)

        # The crawler is async; run it to completion inside this worker thread.
        crawler = PoliteCrawler()
        pages_data = asyncio.run(crawler.crawl(start_url))
        logger.info(
            "Crawl returned %d pages for company %s in %.1fs",
            len(pages_data), company_id, time.monotonic() - started,
        )

        crawl_job.pages_total = len(pages_data)
        db.commit()

        existing_urls = {
            row[0]
            for row in db.query(Page.url).filter(Page.company_id == company_id).all()
        }
        existing_hashes = {
            row[0]
            for row in db.query(Page.content_hash).filter(Page.company_id == company_id).all()
            if row[0]
        }
        logger.info(
            "Company %s already has %d stored pages; processing %d crawled pages",
            company_id, len(existing_urls), len(pages_data),
        )

        inserted = 0
        skipped = 0
        duplicates = 0
        failures = []

        for idx, page_data in enumerate(pages_data, start=1):
            url = page_data["url"]
            try:
                if url in existing_urls:
                    skipped += 1
                    logger.info(
                        "[%d/%d] Skipping already stored page %s", idx, len(pages_data), url
                    )
                else:
                    text = page_data["text"]
                    content_hash = hashlib.sha256(text.encode()).hexdigest()

                    if content_hash in existing_hashes:
                        duplicates += 1
                        logger.info(
                            "[%d/%d] Skipping duplicate content at %s",
                            idx, len(pages_data), url,
                        )
                    else:
                        page_started = time.monotonic()
                        chunks_text = chunk_text(text)

                        logger.info(
                            "[%d/%d] Ingesting %s (%d chars, %d chunks)",
                            idx, len(pages_data), url, len(text), len(chunks_text),
                        )

                        # Embed before opening the DB transaction so a slow/failing
                        # model does not hold a PostgreSQL transaction open.
                        vectors = generate_embeddings(chunks_text) if chunks_text else []
                        logger.info(
                            "[%d/%d] Generated %d embeddings in %.1fs",
                            idx, len(pages_data), len(vectors), time.monotonic() - page_started,
                        )

                        page = Page(
                            company_id=company_id,
                            url=url,
                            content_hash=content_hash,
                            raw_html=page_data["html"][:10000],  # truncate
                            cleaned_text=text,
                            status_code=page_data["status_code"],
                        )
                        db.add(page)
                        db.flush()

                        for cidx, (chunk_content, vector) in enumerate(zip(chunks_text, vectors)):
                            chunk = Chunk(
                                company_id=company_id,
                                page_id=page.id,
                                text=chunk_content,
                                chunk_index=cidx,
                            )
                            db.add(chunk)
                            db.flush()
                            db.add(Embedding(chunk_id=chunk.id, embedding=vector))

                        db.commit()
                        existing_urls.add(url)
                        existing_hashes.add(content_hash)
                        inserted += 1
                        logger.info(
                            "[%d/%d] Stored %s with %d chunks in %.1fs",
                            idx, len(pages_data), url, len(chunks_text),
                            time.monotonic() - page_started,
                        )
            except Exception as exc:
                db.rollback()
                failures.append((url, str(exc)))
                logger.exception(
                    "[%d/%d] Failed to ingest page %s (company %s); continuing",
                    idx, len(pages_data), url, company_id,
                )

            # Always update progress, even for skipped/failed pages, so the UI
            # does not appear stuck at 0/50.
            try:
                job = db.get(CrawlJob, crawl_job_id)
                if job:
                    job.pages_crawled = idx
                    job.pages_total = len(pages_data)
                db.commit()
            except Exception:
                db.rollback()
                logger.warning(
                    "Could not update progress for crawl job %s", crawl_job_id, exc_info=True
                )

        elapsed = time.monotonic() - started
        crawl_job = db.get(CrawlJob, crawl_job_id)
        company = db.get(Company, company_id)

        if not pages_data or (failures and inserted == 0):
            reason = (
                "No pages could be crawled (network error, robots.txt, or non-HTML content)"
                if not pages_data
                else f"All {len(failures)} pages failed during ingestion; last error: {failures[-1][1]}"
            )
            crawl_job.status = CrawlJobStatus.FAILED
            crawl_job.error = reason
            company.status = CompanyStatus.FAILED
            logger.error("Crawl job %s failed for company %s: %s", crawl_job_id, company_id, reason)
        else:
            crawl_job.status = CrawlJobStatus.COMPLETED
            company.status = CompanyStatus.READY
            company.last_crawled_at = datetime.now(timezone.utc)
            logger.info(
                "Crawl job %s completed for company %s in %.1fs: "
                "crawled=%d inserted=%d skipped=%d duplicates=%d failed=%d",
                crawl_job_id, company_id, elapsed, len(pages_data), inserted, skipped,
                duplicates, len(failures),
            )

        crawl_job.finished_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as exc:
        logger.exception("Crawl job %s failed for company %s", crawl_job_id, company_id)
        try:
            db.rollback()
            crawl_job = db.get(CrawlJob, crawl_job_id)
            company = db.get(Company, company_id)
            if crawl_job:
                crawl_job.status = CrawlJobStatus.FAILED
                crawl_job.error = str(exc)
                crawl_job.finished_at = datetime.now(timezone.utc)
            if company:
                company.status = CompanyStatus.FAILED
            db.commit()
        except Exception:
            logger.exception("Could not persist failure state for crawl job %s", crawl_job_id)
            db.rollback()
    finally:
        db.close()


@router.get("/{company_id}/status", response_class=HTMLResponse)
async def company_status(request: Request, company_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    company = db.query(Company).filter(Company.id == company_id, Company.user_id == current_user.id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    crawl_job = db.query(CrawlJob).filter(CrawlJob.company_id == company_id).order_by(CrawlJob.created_at.desc()).first()
    
    return templates.TemplateResponse("crawl_status.html", {"request": request, "company": company, "crawl_job": crawl_job})
