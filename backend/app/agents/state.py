"""
State schema for the news processing workflow.
"""
from typing import TypedDict, List, Dict, Optional, Any
from datetime import datetime


class ArticleData(TypedDict, total=False):
    """Individual article data structure."""
    url: str
    title: str
    author: Optional[str]
    published_at: Optional[datetime]
    raw_content: Optional[str]
    cleaned_content: Optional[str]
    summary_brief: Optional[str]
    summary_standard: Optional[str]
    summary_detailed: Optional[str]
    topics: List[Dict[str, Any]]  # List of {topic_id, topic_name, confidence}
    status: str
    error: Optional[str]


class NewsProcessingState(TypedDict, total=False):
    """State for news processing workflow."""
    # Input
    feed_id: int
    feed_url: str
    
    # RSS Fetching
    rss_articles: List[ArticleData]  # Articles from RSS feed
    
    # Current article being processed
    current_article: Optional[ArticleData]
    current_article_index: int
    
    # Processing results
    processed_articles: List[ArticleData]
    
    # Error tracking
    errors: List[Dict[str, Any]]
    
    # Metadata
    total_articles: int
    total_cost: float
    
    # Control flow
    should_continue: bool
