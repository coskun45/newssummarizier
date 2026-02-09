"""
Custom exceptions for the application.
"""


class NewsAppException(Exception):
    """Base exception for all application errors."""
    pass


class RSSFetchError(NewsAppException):
    """Exception raised when RSS feed fetching fails."""
    pass


class ScrapingError(NewsAppException):
    """Exception raised when web scraping fails."""
    pass


class SummarizationError(NewsAppException):
    """Exception raised when content summarization fails."""
    pass


class TopicCategorizationError(NewsAppException):
    """Exception raised when topic categorization fails."""
    pass


class DatabaseError(NewsAppException):
    """Exception raised when database operations fail."""
    pass


class CostLimitExceededError(NewsAppException):
    """Exception raised when API cost limits are exceeded."""
    pass
