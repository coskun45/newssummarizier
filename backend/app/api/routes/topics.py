"""
Topics endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from app.db.database import get_db
from app.db import crud
import random

router = APIRouter()


class TopicCreate(BaseModel):
    """Topic creation model."""
    name: str
    description: Optional[str] = None
    color: Optional[str] = None


class TopicUpdate(BaseModel):
    """Topic update model."""
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None


class TopicResponse(BaseModel):
    """Topic response model."""
    id: int
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    article_count: int = 0
    
    class Config:
        from_attributes = True


def generate_random_color() -> str:
    """Generate a random color for a topic."""
    colors = [
        "#3b82f6",  # blue
        "#8b5cf6",  # purple
        "#ec4899",  # pink
        "#f59e0b",  # amber
        "#10b981",  # green
        "#06b6d4",  # cyan
        "#f97316",  # orange
        "#6366f1",  # indigo
        "#14b8a6",  # teal
        "#84cc16",  # lime
    ]
    return random.choice(colors)


@router.get("/", response_model=List[TopicResponse])
async def list_topics(feed_id: Optional[int] = None, db: Session = Depends(get_db)):
    """
    List all topics with article counts, optionally filtered by feed.
    """
    topics_with_counts = crud.get_topics_with_counts(db, feed_id=feed_id)
    return [TopicResponse(**topic_dict) for topic_dict in topics_with_counts]


@router.post("/", response_model=TopicResponse)
async def create_topic(topic: TopicCreate, db: Session = Depends(get_db)):
    """
    Create a new topic.
    """
    # Check if topic with same name already exists
    existing_topic = crud.get_topic_by_name(db, topic.name)
    if existing_topic:
        raise HTTPException(status_code=400, detail="Topic with this name already exists")
    
    # Generate random color if not provided
    color = topic.color if topic.color else generate_random_color()
    
    # Create topic
    new_topic = crud.create_topic(
        db=db,
        name=topic.name,
        description=topic.description,
        color=color
    )
    
    return TopicResponse(
        id=new_topic.id,
        name=new_topic.name,
        description=new_topic.description,
        color=new_topic.color,
        article_count=0
    )


@router.get("/{topic_id}", response_model=TopicResponse)
async def get_topic(topic_id: int, db: Session = Depends(get_db)):
    """
    Get a specific topic by ID.
    """
    topic = crud.get_topic(db, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    
    # Get article count for this topic
    article_count = crud.count_articles(db, topic_ids=[topic_id])
    
    return TopicResponse(
        id=topic.id,
        name=topic.name,
        description=topic.description,
        color=topic.color,
        article_count=article_count
    )


@router.put("/{topic_id}", response_model=TopicResponse)
async def update_topic(topic_id: int, topic: TopicUpdate, db: Session = Depends(get_db)):
    """
    Update a topic.
    """
    # Check if topic exists
    existing_topic = crud.get_topic(db, topic_id)
    if not existing_topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    
    # If name is being changed, check if new name is already taken
    if topic.name and topic.name != existing_topic.name:
        name_taken = crud.get_topic_by_name(db, topic.name)
        if name_taken:
            raise HTTPException(status_code=400, detail="Topic with this name already exists")
    
    # Update topic
    updated_topic = crud.update_topic(
        db=db,
        topic_id=topic_id,
        name=topic.name,
        description=topic.description,
        color=topic.color
    )
    
    if not updated_topic:
        raise HTTPException(status_code=500, detail="Failed to update topic")
    
    # Get article count for this topic
    article_count = crud.count_articles(db, topic_ids=[topic_id])
    
    return TopicResponse(
        id=updated_topic.id,
        name=updated_topic.name,
        description=updated_topic.description,
        color=updated_topic.color,
        article_count=article_count
    )


@router.delete("/{topic_id}")
async def delete_topic(topic_id: int, db: Session = Depends(get_db)):
    """
    Delete a topic.
    """
    # Check if topic exists
    topic = crud.get_topic(db, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    
    # Delete the topic
    success = crud.delete_topic(db, topic_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete topic")
    
    return {"status": "success", "message": f"Topic '{topic.name}' deleted successfully"}
