"""
CRUD operations against Neon via asyncpg.
All public functions accept an asyncpg Pool acquired from connection.get_pool().
"""
import logging
from datetime import datetime
from typing import Optional
from database.connection import get_pool

logger = logging.getLogger(__name__)


# ── POSTS ─────────────────────────────────────────────────────────────────────

async def save_post(
    topic: str,
    platforms: list[str],
    content_linkedin: str = "",
    content_medium: str = "",
    content_github: str = "",
    content_twitter: str = "",
    content_reddit: str = "",
    image_url: str = "",
    image_data: bytes | None = None,
    hashtags: list[str] | None = None,
    linkedin_url: str = "",
    medium_url: str = "",
    github_url: str = "",
    twitter_url: str = "",
    reddit_url: str = "",
    status: str = "published",
) -> int:
    """Insert a post record and return its ID."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO posts
            (topic, platforms, content_linkedin,
             content_medium, content_github, content_twitter, content_reddit,
             image_url, image_data, hashtags, linkedin_url, medium_url, github_url,
             twitter_url, reddit_url, status)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
        RETURNING id
        """,
        topic, platforms, content_linkedin,
        content_medium, content_github, content_twitter, content_reddit,
        image_url, image_data, hashtags or [], linkedin_url, medium_url, github_url,
        twitter_url, reddit_url, status,
    )
    post_id = row["id"]
    logger.info(f"Post saved id={post_id}")
    return post_id


async def get_recent_posts(limit: int = 5) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM posts ORDER BY posted_at DESC LIMIT $1", limit
    )
    return [dict(r) for r in rows]


# ── SCHEDULED POSTS ───────────────────────────────────────────────────────────

async def save_scheduled_post(
    topic: str,
    scheduled_time: datetime,
    platforms: list[str],
    content_linkedin: str = "",
    content_medium: str = "",
    content_github: str = "",
    content_twitter: str = "",
    content_reddit: str = "",
    image_url: str = "",
    image_data: bytes | None = None,
    job_id: str = "",
) -> int:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO scheduled_posts
            (topic, scheduled_time, platforms,
             content_linkedin, content_medium, content_github,
             content_twitter, content_reddit, image_url, image_data, job_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        RETURNING id
        """,
        topic, scheduled_time, platforms,
        content_linkedin, content_medium, content_github,
        content_twitter, content_reddit, image_url, image_data, job_id,
    )
    return row["id"]


async def mark_scheduled_posted(scheduled_id: int) -> None:
    pool = await get_pool()
    await pool.execute(
        "UPDATE scheduled_posts SET status='posted' WHERE id=$1", scheduled_id
    )


async def get_pending_scheduled() -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM scheduled_posts WHERE status='pending' ORDER BY scheduled_time"
    )
    return [dict(r) for r in rows]


async def get_post_image(post_id: int) -> bytes | None:
    """Retrieve stored image bytes for a post."""
    pool = await get_pool()
    row = await pool.fetchrow("SELECT image_data FROM posts WHERE id=$1", post_id)
    return row["image_data"] if row and row["image_data"] else None


# ── USER STYLE PREFS ──────────────────────────────────────────────────────────

async def get_style_prefs(telegram_user_id: int) -> dict:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM user_style_prefs WHERE telegram_user_id=$1", telegram_user_id
    )
    if row:
        return dict(row)
    return {"tone": "entrepreneur", "custom_notes": ""}


async def upsert_style_prefs(telegram_user_id: int, tone: str, custom_notes: str) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO user_style_prefs (telegram_user_id, tone, custom_notes)
        VALUES ($1, $2, $3)
        ON CONFLICT (telegram_user_id) DO UPDATE
            SET tone=$2, custom_notes=$3, updated_at=NOW()
        """,
        telegram_user_id, tone, custom_notes,
    )


# ── OAUTH TOKENS ──────────────────────────────────────────────────────────────

async def save_oauth_token(
    platform: str,
    access_token: str,
    person_urn: str = "",
    refresh_token: str = "",
    expires_at: Optional[datetime] = None,
    extra_data: dict | None = None,
) -> None:
    pool = await get_pool()
    import json
    await pool.execute(
        """
        INSERT INTO oauth_tokens (platform, access_token, person_urn, refresh_token, expires_at, extra_data)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (platform) DO UPDATE
            SET access_token=$2, person_urn=$3, refresh_token=$4,
                expires_at=$5, extra_data=$6, updated_at=NOW()
        """,
        platform, access_token, person_urn, refresh_token, expires_at,
        json.dumps(extra_data or {}),
    )


async def get_oauth_token(platform: str) -> dict | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM oauth_tokens WHERE platform=$1", platform
    )
    return dict(row) if row else None


# ── POST CONTEXT (memory) ─────────────────────────────────────────────────────

async def save_post_context(summary: str, topic: str, platforms: list[str]) -> None:
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO post_context (summary, topic, platforms) VALUES ($1,$2,$3)",
        summary, topic, platforms,
    )


async def get_recent_context(limit: int = 3) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM post_context ORDER BY posted_at DESC LIMIT $1", limit
    )
    return [dict(r) for r in rows]
