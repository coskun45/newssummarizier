"""
Database seeding script.
"""
import logging
from app.db.database import SessionLocal
from app.db import crud
from app.core.config import settings

logger = logging.getLogger(__name__)


def seed_topics():
    """Seed predefined topics."""
    db = SessionLocal()
    try:
        topics_data = [
            {"name": "Politik", "description": "Politische Nachrichten", "color": "#3B82F6"},  # Blue
            {"name": "Wirtschaft", "description": "Wirtschaftsnachrichten", "color": "#10B981"},  # Green
            {"name": "Technologie", "description": "Technologie und Innovation", "color": "#8B5CF6"},  # Purple
            {"name": "Sport", "description": "Sportnachrichten", "color": "#F59E0B"},  # Orange
            {"name": "Kultur", "description": "Kultur und Unterhaltung", "color": "#EC4899"},  # Pink
            {"name": "Wissenschaft", "description": "Wissenschaft und Forschung", "color": "#06B6D4"},  # Cyan
            {"name": "Umwelt", "description": "Umwelt und Klima", "color": "#22C55E"},  # Light Green
            {"name": "Gesundheit", "description": "Gesundheit und Medizin", "color": "#EF4444"},  # Red
        ]
        
        created_count = 0
        for topic_data in topics_data:
            existing = crud.get_topic_by_name(db, topic_data["name"])
            if not existing:
                crud.create_topic(
                    db=db,
                    name=topic_data["name"],
                    description=topic_data["description"],
                    color=topic_data["color"]
                )
                created_count += 1
                logger.info(f"Created topic: {topic_data['name']}")
        
        logger.info(f"Topics seeding completed. Created {created_count} new topics.")
        
    except Exception as e:
        logger.error(f"Error seeding topics: {e}")
    finally:
        db.close()


def seed_feed():
    """Seed the default DW RSS feed."""
    db = SessionLocal()
    try:
        feed_url = settings.default_feed_url
        
        # Check if feed already exists
        existing_feed = crud.get_feed_by_url(db, feed_url)
        if existing_feed:
            logger.info(f"Feed already exists: {feed_url}")
            return existing_feed.id
        
        # Create feed
        feed = crud.create_feed(
            db=db,
            url=feed_url,
            title="DW - Deutsche Welle",
            description="Deutschlands internationale Medienorganisation"
        )
        
        logger.info(f"Created feed: {feed.title} ({feed.url})")
        return feed.id
        
    except Exception as e:
        logger.error(f"Error seeding feed: {e}")
        return None
    finally:
        db.close()


def seed_database():
    """Seed all initial data."""
    logger.info("Starting database seeding...")
    
    # Seed topics
    seed_topics()
    
    # Seed feed
    feed_id = seed_feed()
    
    # Seed default system prompts
    seed_system_prompts()
    
    logger.info("Database seeding completed.")
    return feed_id


def seed_system_prompts():
    """Seed default system prompts."""
    db = SessionLocal()
    try:
        default_prompts = {
            "classification": """You are a news categorization assistant. Analyze German news articles and categorize them into appropriate topics with confidence scores. 

Your task:
1. Read the article title and content carefully
2. Identify relevant topics from the provided list
3. Assign confidence scores (0.0-1.0) based on how well the article fits each topic
4. Return only topics with confidence >= 0.5
5. Always return at least one topic

Return ONLY valid JSON with no additional text.""",
            
            "summarization": """You are a professional news summarization assistant. Create clear, concise, and informative summaries of German news articles.

Your task:
1. Read the article carefully
2. Extract the main points and key information
3. Create a summary that captures the essence of the article
4. Use clear and professional language in German
5. Focus on facts and avoid personal opinions
6. Maintain the original tone and context

Return only the summary text without any additional formatting or explanations."""
        }
        
        created_count = 0
        for prompt_type, prompt_text in default_prompts.items():
            existing = crud.get_system_prompt(db, prompt_type)
            if not existing:
                crud.create_system_prompt(
                    db=db,
                    prompt_type=prompt_type,
                    prompt_text=prompt_text,
                    is_active=True
                )
                created_count += 1
                logger.info(f"Created system prompt: {prompt_type}")
        
        logger.info(f"System prompts seeding completed. Created {created_count} new prompts.")
        
    except Exception as e:
        logger.error(f"Error seeding system prompts: {e}")
    finally:
        db.close()

