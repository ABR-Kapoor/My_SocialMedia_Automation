"""
Lightweight Flask server for OAuth callbacks (LinkedIn).
Runs in a background thread alongside the Telegram bot.
Also serves /health for Render.com keep-alive pings.

IMPORTANT: All route handlers are fully synchronous (requests + psycopg2),
because Flask runs in a background thread and cannot safely use the
asyncpg pool which belongs to the main asyncio event loop.
"""
import json
import logging
import requests as req
import psycopg2

from flask import Flask, request, jsonify
from config import (
    APP_URL, PORT,
    LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET, LINKEDIN_REDIRECT_URI,
    NEON_DATABASE_URL,
)

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__)

    # ── Health check ──────────────────────────────────────────────────────────

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "bot": "Abeer Brand Bot"}), 200

    @app.route("/")
    def index():
        return (
            "<h2>🚀 Abeer Brand Bot</h2>"
            "<p>Telegram bot is running.</p>"
            "<p><a href='/health'>Health Check</a></p>"
        ), 200

    # ── LinkedIn OAuth Callback (fully SYNC — no asyncio) ─────────────────────

    @app.route("/linkedin/callback")
    def linkedin_callback():
        code  = request.args.get("code")
        error = request.args.get("error")

        if error:
            logger.error(f"LinkedIn OAuth error: {error}")
            return f"<h3>❌ LinkedIn auth failed: {error}</h3>", 400

        if not code:
            return "<h3>❌ No code received from LinkedIn</h3>", 400

        try:
            # ── 1. Exchange code for access token (sync HTTP) ─────────────────
            token_resp = req.post(
                "https://www.linkedin.com/oauth/v2/accessToken",
                data={
                    "grant_type":    "authorization_code",
                    "code":          code,
                    "redirect_uri":  LINKEDIN_REDIRECT_URI,
                    "client_id":     LINKEDIN_CLIENT_ID,
                    "client_secret": LINKEDIN_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            token_data   = token_resp.json()
            access_token = token_data.get("access_token")

            if not access_token:
                logger.error(f"LinkedIn token error: {token_data}")
                return f"<h3>❌ LinkedIn token exchange failed: {token_data}</h3>", 500

            # ── 2. Fetch LinkedIn profile ─────────────────────────────────────
            profile_resp = req.get(
                "https://api.linkedin.com/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
            profile    = profile_resp.json()
            person_urn = profile.get("sub", "")
            name       = profile.get("name", "")

            # Also fetch vanityName for profile URL
            vanity_name = ""
            try:
                me_resp = req.get(
                    "https://api.linkedin.com/v2/me?projection=(vanityName)",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=10,
                )
                vanity_name = me_resp.json().get("vanityName", "")
            except Exception:
                pass
            logger.info(f"✅ LinkedIn authenticated: {name} ({person_urn}) vanity={vanity_name}")

            # ── 3. Save token to Neon DB (sync psycopg2) ──────────────────────
            # Strip SQLAlchemy prefix if present
            db_url = NEON_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
            conn = psycopg2.connect(db_url)
            cur  = conn.cursor()
            cur.execute(
                """
                INSERT INTO oauth_tokens
                    (platform, access_token, person_urn, extra_data, updated_at)
                VALUES ('linkedin', %s, %s, %s, NOW())
                ON CONFLICT (platform) DO UPDATE
                    SET access_token = EXCLUDED.access_token,
                        person_urn   = EXCLUDED.person_urn,
                        extra_data   = EXCLUDED.extra_data,
                        updated_at   = NOW()
                """,
                (access_token, person_urn, json.dumps({"name": name, "vanity_name": vanity_name})),
            )
            conn.commit()
            cur.close()
            conn.close()
            logger.info("✅ LinkedIn token saved to DB")

            # ── 4. Notify user via Telegram (sync HTTP) ───────────────────────
            try:
                from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
                req.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id":    TELEGRAM_CHAT_ID,
                        "text":       f"✅ *LinkedIn Connected!*\n\nAccount: `{name}`\nProfile: linkedin.com/in/{vanity_name or person_urn}\nUse /post to publish!",
                        "parse_mode": "Markdown",
                    },
                    timeout=5,
                )
            except Exception as tg_err:
                logger.warning(f"Telegram notify failed (non-critical): {tg_err}")

            return (
                "<html><body style='font-family:sans-serif;text-align:center;padding:40px'>"
                "<h2>✅ LinkedIn Connected!</h2>"
                f"<p>Account: <strong>{name}</strong></p>"
                "<p>You can close this window and return to Telegram.</p>"
                "<script>setTimeout(() => window.close(), 3000);</script>"
                "</body></html>"
            ), 200

        except Exception as e:
            logger.error(f"LinkedIn token exchange failed: {e}", exc_info=True)
            return f"<h3>❌ Error: {e}</h3>", 500

    return app


def run_flask_server():
    """Start Flask in a background thread."""
    app = create_app()
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
