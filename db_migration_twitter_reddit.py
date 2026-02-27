"""
One-time script to add twitter and reddit columns to Neon Database.
"""
import asyncio
import psycopg2
from config import NEON_DATABASE_URL
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migration():
    # Use sync psycopg2 for simple DDL
    db_url = NEON_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    commands = [
        "ALTER TABLE posts ADD COLUMN IF NOT EXISTS content_twitter TEXT DEFAULT '';",
        "ALTER TABLE posts ADD COLUMN IF NOT EXISTS content_reddit TEXT DEFAULT '';",
        "ALTER TABLE posts ADD COLUMN IF NOT EXISTS twitter_url TEXT DEFAULT '';",
        "ALTER TABLE posts ADD COLUMN IF NOT EXISTS reddit_url TEXT DEFAULT '';",
        
        "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS content_twitter TEXT DEFAULT '';",
        "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS content_reddit TEXT DEFAULT '';"
    ]

    for cmd in commands:
        logger.info(f"Executing: {cmd}")
        try:
            cur.execute(cmd)
        except Exception as e:
            logger.error(f"Error: {e}")

    cur.close()
    conn.close()
    logger.info("✅ Database migration completed.")

if __name__ == "__main__":
    run_migration()
