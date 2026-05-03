"""
Migration: Add is_read column to articles table.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "news_summary.db")


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}, skipping migration.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if column already exists
    cursor.execute("PRAGMA table_info(articles)")
    columns = [row[1] for row in cursor.fetchall()]

    if "is_read" in columns:
        print("Column 'is_read' already exists. Skipping.")
    else:
        cursor.execute("ALTER TABLE articles ADD COLUMN is_read BOOLEAN NOT NULL DEFAULT 0")
        conn.commit()
        print("Column 'is_read' added successfully.")

    conn.close()


if __name__ == "__main__":
    migrate()
