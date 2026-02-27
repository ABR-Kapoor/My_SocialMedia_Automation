"""
Central configuration for the Social Media Automation Agent.
Loads from .env — never hardcode secrets here.
"""
import os
from datetime import timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# ── TIMEZONE ──────────────────────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))

# ── TELEGRAM ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
try:
    TELEGRAM_CHAT_ID: int = int(os.environ["TELEGRAM_CHAT_ID"])
except (ValueError, KeyError):
    raise SystemExit(
        "❌ TELEGRAM_CHAT_ID must be a plain number (e.g. 123456789).\n"
        "   Get yours by messaging @userinfobot on Telegram.\n"
        f"   Current value: {os.environ.get('TELEGRAM_CHAT_ID', 'NOT SET')!r}"
    )

# ── AI / LLMs ─────────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.environ["GEMINI_API_KEY"]
OPENAI_API_KEY: str = os.environ["OPENAI_API_KEY"]
GEMINI_MODEL   = "gemini-2.5-flash"
OPENAI_MODEL   = "gpt-4o-mini"
IMAGE_MODEL    = "dall-e-3"

# ── DATABASE ──────────────────────────────────────────────────────────────────
NEON_DATABASE_URL: str = os.environ["NEON_DATABASE_URL"]   # sync (psycopg2)
NEON_ASYNC_URL: str    = os.environ["NEON_ASYNC_URL"]       # async (asyncpg)

# ── LINKEDIN ──────────────────────────────────────────────────────────────────
LINKEDIN_CLIENT_ID: str     = os.environ.get("LINKEDIN_CLIENT_ID", "")
LINKEDIN_CLIENT_SECRET: str = os.environ.get("LINKEDIN_CLIENT_SECRET", "")
LINKEDIN_REDIRECT_URI: str  = os.environ.get("LINKEDIN_REDIRECT_URI", "http://localhost:8080/linkedin/callback")
LINKEDIN_ACCESS_TOKEN: str  = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
LINKEDIN_SCOPES             = ["openid", "profile", "email", "w_member_social"]


# ── MEDIUM ────────────────────────────────────────────────────────────────────
MEDIUM_SID_COOKIE: str = os.environ.get("MEDIUM_SID_COOKIE", "")
MEDIUM_UID_COOKIE: str = os.environ.get("MEDIUM_UID_COOKIE", "")

# ── GITHUB ────────────────────────────────────────────────────────────────────
GITHUB_PAT: str      = os.environ.get("GITHUB_PAT", "")
GITHUB_DSA_REPO: str = os.environ.get("GITHUB_DSA_REPO", "ABR-Kapoor/DSA-java")
GITHUB_USERNAME: str = os.environ.get("GITHUB_USERNAME", "ABR-Kapoor")

# ── BRAND PERSONA ─────────────────────────────────────────────────────────────
BRAND = {
    "name":         "Abeer Kapoor",
    "title":        "Full-Stack Developer | AI Builder | Blockchain Entrepreneur",
    "github":       "https://github.com/ABR-Kapoor",
    "linkedin":     "https://www.linkedin.com/in/abeer-kapoor/",
    "twitter":      "",  # removed
    "medium":       "https://medium.com/@abrmkprm",
    "topics":       [
        "Full-Stack Development", "Artificial Intelligence", "Blockchain & Web3",
        "Data Structures & Algorithms", "Entrepreneurship", "Economics",
        "Geopolitics", "Building in Public", "Open Source",
    ],
    "community":    "FrequnSync",
    "tone":         "Bold, contrarian, entrepreneur-creator (Naval + Hormozi + Sahil Bloom)",
}

# ── APP ───────────────────────────────────────────────────────────────────────
APP_URL: str = os.environ.get("APP_URL", "http://localhost:8080")
PORT: int    = int(os.environ.get("PORT", 8080))
ENV: str     = os.environ.get("ENV", "development")
