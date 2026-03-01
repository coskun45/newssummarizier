"""
Application configuration using Pydantic Settings.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )
    
    # OpenAI Configuration
    openai_api_key: str
    
    # Database
    database_url: str = "sqlite:///./news_summary.db"
    checkpoints_db: str = "checkpoints.db"
    
    # Application Settings
    app_name: str = "News Summarizer"
    app_version: str = "1.0.0"
    debug: bool = True
    
    # RSS Feed Configuration
    default_feed_url: str = "https://rss.dw.com/atom/rss-de-all"
    feed_refresh_interval: int = 1800  # seconds (30 minutes)
    
    # Scraping Configuration
    scraping_enabled: bool = True
    scraping_delay: float = 1.0  # seconds between requests
    max_retries: int = 3
    
    # OpenAI Configuration
    default_model: str = "gpt-4o-mini"
    detailed_model: str = "gpt-4o"
    max_tokens_input: int = 4000
    max_tokens_output_brief: int = 150
    max_tokens_output_standard: int = 300
    max_tokens_output_detailed: int = 1000
    
    # Cost Management
    daily_cost_limit: float = 5.0  # USD
    monthly_cost_limit: float = 100.0  # USD
    
    # CORS
    cors_origins: str = "http://localhost:5174,http://localhost:3000"

    # JWT Authentication
    jwt_secret_key: str = "change-me-in-production-use-32-char-minimum-secret-key"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480  # 8 hours
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins string into list."""
        return [origin.strip() for origin in self.cors_origins.split(",")]


# Global settings instance
settings = Settings()
