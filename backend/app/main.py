"""
FastAPI main application with CORS and lifespan management.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.database import init_db
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO if settings.debug else logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info("Starting News Summarizer application...")
    
    # Initialize database
    init_db()
    logger.info("Database initialized")
    
    # Seed database with initial data (only creates feed and topics if missing)
    from app.db.seed import seed_database
    feed_id = seed_database()
    
    # Note: Initial feed fetch is NOT triggered automatically
    # Use the "Neue Nachrichten laden" button in the frontend to fetch news
    if feed_id:
        logger.info(f"Feed ID {feed_id} ready. Use manual refresh button to fetch news.")
    
    yield
    
    # Shutdown
    logger.info("Shutting down News Summarizer application...")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# Import and include routers
from app.api.routes import rss, articles, summaries, settings as settings_routes, topics, prompts

app.include_router(rss.router, prefix="/api/feeds", tags=["feeds"])
app.include_router(articles.router, prefix="/api/articles", tags=["articles"])
app.include_router(summaries.router, prefix="/api", tags=["summaries"])
app.include_router(settings_routes.router, prefix="/api/settings", tags=["settings"])
app.include_router(topics.router, prefix="/api/topics", tags=["topics"])
app.include_router(prompts.router, prefix="/api/prompts", tags=["prompts"])
