"""
LangGraph workflow for news processing.
"""
from langgraph.graph import StateGraph, END
from typing import TypedDict
from app.agents.state import NewsProcessingState
from app.agents.nodes import (
    rss_fetcher_node,
    article_processor_node,
    should_continue_processing
)
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


def create_news_processing_workflow():
    """
    Create the news processing workflow graph.
    
    Workflow:
    1. RSS Fetcher: Fetch articles from RSS feed
    2. Article Processor: For each article:
       - Extract content from web page
       - Categorize by topics
       - Generate summaries (brief, standard, detailed)
    3. Loop until all articles processed
    """
    # Create the state graph
    workflow = StateGraph(NewsProcessingState)
    
    # Add nodes
    workflow.add_node("rss_fetcher", rss_fetcher_node)
    workflow.add_node("article_processor", article_processor_node)
    
    # Set entry point
    workflow.set_entry_point("rss_fetcher")
    
    # Add edges
    workflow.add_edge("rss_fetcher", "article_processor")
    
    # Add conditional edge for looping
    workflow.add_conditional_edges(
        "article_processor",
        should_continue_processing,
        {
            "continue": "article_processor",
            "end": END
        }
    )
    
    return workflow


def get_compiled_workflow():
    """
    Get compiled workflow.
    Note: Checkpointing is disabled for simplicity. Can be added later if needed.
    """
    workflow = create_news_processing_workflow()
    
    # Compile the workflow without checkpointer for now
    compiled_workflow = workflow.compile()
    
    logger.info("News processing workflow compiled successfully")
    
    return compiled_workflow


# Global workflow instance
news_workflow = None


def get_workflow():
    """Get or create the global workflow instance."""
    global news_workflow
    if news_workflow is None:
        news_workflow = get_compiled_workflow()
    return news_workflow
