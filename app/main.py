import logging

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from app.core.config import settings
from app.core.logging import configure_logging
from app.api import auth, companies, chat, public_opinion

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.APP_NAME,
    description="RAG-powered chatbot for company portals",
    version="0.1.0"
)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Templates
templates = Jinja2Templates(directory="app/templates")

# Include routers
app.include_router(auth.router)
app.include_router(companies.router)
app.include_router(chat.router)
app.include_router(public_opinion.router)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "app_name": settings.APP_NAME})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/health")
async def health():
    return {"status": "healthy", "app": settings.APP_NAME}


@app.on_event("startup")
async def on_startup():
    logger.info("%s started (debug=%s, log_level=%s)", settings.APP_NAME, settings.DEBUG, settings.LOG_LEVEL)
