"""
Migration script: Silinen kategorilerdeki makaleleri Önemsiz olarak işaretle,
ardından kategorileri sil.

Kategoriler: Politik, Wirtschaft, Technologie, Sport, Kultur, Wissenschaft, Umwelt, Gesundheit
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.database import SessionLocal
from app.db import models

TOPICS_TO_REMOVE = [
    "Politik",
    "Wirtschaft",
    "Technologie",
    "Sport",
    "Kultur",
    "Wissenschaft",
    "Umwelt",
    "Gesundheit",
]

def main():
    db = SessionLocal()
    try:
        # Find existing topics from the list
        topics = db.query(models.Topic).filter(
            models.Topic.name.in_(TOPICS_TO_REMOVE)
        ).all()

        if not topics:
            print("Bu kategorilerden hiçbiri veritabanında bulunamadı.")
            return

        print(f"Bulunan kategoriler: {[t.name for t in topics]}")
        topic_ids = [t.id for t in topics]

        # Find articles linked to these topics
        article_topic_rows = db.query(models.ArticleTopic).filter(
            models.ArticleTopic.topic_id.in_(topic_ids)
        ).all()

        article_ids = list({row.article_id for row in article_topic_rows})
        print(f"Etkilenen makale sayısı: {len(article_ids)}")

        # For each affected article: set importance=unimportant, priority=null
        # BUT only if the article has NO other topics outside the removed list
        updated_count = 0
        for article_id in article_ids:
            # Check if article has topics outside the removed set
            other_topics = db.query(models.ArticleTopic).filter(
                models.ArticleTopic.article_id == article_id,
                ~models.ArticleTopic.topic_id.in_(topic_ids)
            ).first()

            if not other_topics:
                # No other topics — mark as unimportant
                article = db.query(models.Article).filter(
                    models.Article.id == article_id
                ).first()
                if article:
                    article.importance = "unimportant"
                    article.priority = None
                    updated_count += 1

        # Remove all ArticleTopic associations for these topics
        deleted_assoc = db.query(models.ArticleTopic).filter(
            models.ArticleTopic.topic_id.in_(topic_ids)
        ).delete(synchronize_session=False)
        print(f"Silinen makale-konu ilişkisi: {deleted_assoc}")

        # Delete the topics themselves
        deleted_topics = db.query(models.Topic).filter(
            models.Topic.id.in_(topic_ids)
        ).delete(synchronize_session=False)
        print(f"Silinen kategori sayısı: {deleted_topics}")

        db.commit()
        print(f"Önemsiz yapılan makale sayısı: {updated_count}")
        print("Migration tamamlandi.")

    except Exception as e:
        db.rollback()
        print(f"HATA: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
