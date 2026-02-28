import logging
import re
import json
import os

# curl_cffi mimics Chrome TLS fingerprint — bypasses Cloudflare cf_clearance restrictions
# (Replaced with standard requests for Termux compatibility, manual post mode active)
import requests as cf_requests

from config import MEDIUM_SID_COOKIE, MEDIUM_UID_COOKIE

logger = logging.getLogger(__name__)

MEDIUM_BASE = "https://medium.com"

MEDIUM_COOKIE_STRING = os.environ.get("MEDIUM_COOKIE_STRING", "")

# Match EXACTLY the User-Agent from the browser that generated cf_clearance
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.5 Mobile/15E148 Safari/604.1"
)


def _strip(text: str) -> str:
    return re.sub(r'^\]\)\}while\(1\);<\/x>', '', text).strip()


class MediumPlatform:
    def __init__(self):
        # Standard requests session (no impersonation)
        self.session = cf_requests.Session()

        # ── Build raw Cookie header ───────────────────────────────────────────
        if MEDIUM_COOKIE_STRING:
            raw_cookie = MEDIUM_COOKIE_STRING.strip().strip('"').strip("'")
            logger.info("Medium: using full MEDIUM_COOKIE_STRING from env")
            # Extract CSRF tokens directly from the cookie string — don't re-fetch
            xsrf  = self._extract_cookie(raw_cookie, "xsrf")
            nonce = self._extract_cookie(raw_cookie, "nonce")
            csrf  = xsrf or nonce
            logger.info(f"Medium CSRF token (xsrf={xsrf[:8] if xsrf else 'none'}, nonce={nonce[:8] if nonce else 'none'})")
        else:
            raw_cookie = f"sid={MEDIUM_SID_COOKIE}"
            if MEDIUM_UID_COOKIE:
                raw_cookie += f"; uid={MEDIUM_UID_COOKIE}"
            logger.info("Medium: using sid/uid cookies from env")
            csrf = self._fetch_nonce(raw_cookie)
            if csrf:
                raw_cookie += f"; nonce={csrf}"

        self.session.headers.update({
            "User-Agent":    UA,
            "Accept":        "application/json, text/plain, */*",
            "Content-Type":  "application/json",
            "Referer":       "https://medium.com/",
            "Origin":        "https://medium.com",
            "x-obvious-cid": "web",
            "Cookie":        raw_cookie,
        })
        if csrf:
            self.session.headers["x-xsrf-token"] = csrf

    @staticmethod
    def _extract_cookie(cookie_str: str, name: str) -> str:
        """Extract a named cookie value from a raw Cookie header string."""
        m = re.search(rf'(?:^|;\s*){re.escape(name)}=([^;]+)', cookie_str)
        return m.group(1).strip() if m else ""

    def _fetch_nonce(self, raw_cookie: str = "") -> str:
        """Load medium.com to get the nonce cookie Medium needs for CSRF."""
        try:
            resp = self.session.get(
                "https://medium.com/",
                timeout=12,
                headers={"Accept": "text/html,application/xhtml+xml,*/*"},
            )
            for hdr in resp.headers.get("Set-Cookie", "").split(","):
                m = re.search(r'nonce=([^;,\s]+)', hdr)
                if m:
                    return m.group(1)
            m = re.search(r'"nonce"\s*:\s*"([a-zA-Z0-9_\-]+)"', resp.text)
            if m:
                return m.group(1)
            nonce_cookie = resp.cookies.get("nonce")
            if nonce_cookie:
                return nonce_cookie
        except Exception as e:
            logger.debug(f"Medium nonce fetch error: {e}")
        return ""

    def _get_user_id(self) -> str:
        """Try GraphQL → REST to get current user's Medium ID."""

        # 1️⃣  GraphQL — most reliable for auth check
        try:
            r = self.session.post(
                f"{MEDIUM_BASE}/_/graphql",
                json={"query": "{ viewer { id username name } }"},
                headers={"graphql-operation": "Viewer"},
                timeout=15,
            )
            logger.debug(f"GraphQL /viewer → HTTP {r.status_code}")
            if r.status_code == 200:
                data = json.loads(_strip(r.text))
                uid  = (data.get("data") or {}).get("viewer", {}).get("id", "")
                if uid:
                    logger.info(f"✅ Medium userId via GraphQL: {uid}")
                    return uid
        except Exception as e:
            logger.debug(f"GraphQL failed: {e}")

        # 2️⃣  REST /_/api/me
        try:
            r = self.session.get(f"{MEDIUM_BASE}/_/api/me", timeout=15)
            logger.debug(f"/_/api/me → HTTP {r.status_code}")
            if r.status_code == 200:
                data = json.loads(_strip(r.text))
                uid  = data.get("payload", {}).get("user", {}).get("userId", "")
                if uid:
                    logger.info(f"✅ Medium userId via /_/api/me: {uid}")
                    return uid
        except Exception as e:
            logger.debug(f"/_/api/me error: {e}")

        # 3️⃣  REST /me?format=json
        try:
            r = self.session.get(f"{MEDIUM_BASE}/me?format=json", timeout=15)
            logger.debug(f"/me?format=json → HTTP {r.status_code}")
            if r.status_code == 200:
                data = json.loads(_strip(r.text))
                uid  = data.get("payload", {}).get("user", {}).get("userId", "")
                if uid:
                    logger.info(f"✅ Medium userId via /me: {uid}")
                    return uid
        except Exception as e:
            logger.debug(f"/me?format=json error: {e}")

        raise RuntimeError(
            "Medium auth 403 — all endpoints blocked. "
            "Your sid cookie is probably expired. "
            "Log out and back in to medium.com, then re-copy the sid cookie."
        )

    def _parse_medium_content(self, content: str) -> tuple[str, str, str, list[str]]:
        """
        Parse agent-generated Medium content into (title, subtitle, body, tags).
        Expected format from content_agent:
        TITLE: ...
        SUBTITLE: ...
        [body]
        Tags: tag1, tag2, ...
        """
        lines      = content.strip().split("\n")
        title      = ""
        subtitle   = ""
        body_lines = []
        tags       = []
        in_body    = False

        for line in lines:
            if line.startswith("TITLE:"):
                title = line.replace("TITLE:", "").strip()
            elif line.startswith("SUBTITLE:"):
                subtitle = line.replace("SUBTITLE:", "").strip()
                in_body  = True
            elif line.lower().startswith("tags:"):
                raw_tags = line.split(":", 1)[1].strip()
                tags     = [t.strip() for t in raw_tags.split(",") if t.strip()]
            elif in_body:
                body_lines.append(line)

        body = "\n".join(body_lines).strip()
        if not title:
            title = body_lines[0][:80] if body_lines else "Untitled"
        if not body:
            body = content

        return title, subtitle, body, tags[:5]

    async def post(self, content: str, image_bytes: bytes | None = None) -> str:
        """
        Attempts to publish to Medium. Since Medium's write API is locked,
        raises MediumManualPostRequired with formatted content so the caller
        can forward it to Telegram for manual publish.
        """
        import re
        title, subtitle, body, tags = self._parse_medium_content(content)
        full_body = f"{subtitle}\n\n{body}" if subtitle else body
        tag_str   = "  ".join(f"#{t}" for t in tags[:5])

        # Escape markdown for Telegram display
        display_title = re.sub(r'([*_`\[\]])', r'\\\1', title)
        display_body = re.sub(r'^#{1,6}\s*', '', full_body, flags=re.MULTILINE)
        display_body = re.sub(r'([*_`\[\]])', r'\\\1', display_body)
        display_tags = re.sub(r'([*_`\[\]])', r'\\\1', tag_str)

        formatted = (
            f"📝 *Medium Draft Ready*\n\n"
            f"*{display_title}*\n\n"
            f"{display_body}\n\n"
            f"{display_tags}\n\n"
            f"👉 [Paste here (Web)](https://medium.com/new-story)"
        )
        raise MediumManualPostRequired(formatted, title)


class MediumManualPostRequired(Exception):
    """
    Raised when Medium's API can't post directly.
    Carries formatted Telegram-ready content for manual publish.
    """
    def __init__(self, telegram_text: str, title: str):
        self.telegram_text = telegram_text
        self.title = title
        super().__init__(f"Medium draft ready for manual post: {title}")

