import logging
import urllib.parse

logger = logging.getLogger(__name__)


class RedditManualPostRequired(Exception):
    """
    Raised when Reddit post is requested.
    Carries formatted Telegram-ready content for manual publish.
    """
    def __init__(self, telegram_text: str, title: str):
        self.telegram_text = telegram_text
        self.title = title
        super().__init__(f"Reddit draft ready for manual post: {title}")


class RedditPlatform:
    """
    Reddit Platform Handler.
    Raises RedditManualPostRequired with a submit link and the formatted text.
    """
    def __init__(self):
        pass

    async def post(self, content: str, image_bytes: bytes | None = None) -> str:
        """
        Parses content and provides a manual Reddit submit link.
        """
        import re
        lines = content.strip().split("\n")
        title = lines[0].replace("Title:", "").replace("**", "").strip() if lines else "New Reddit Post"
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else content
        
        # Pre-fill Reddit submit URL
        submit_url = f"https://www.reddit.com/submit?title={urllib.parse.quote(title, safe='')}&text={urllib.parse.quote(body, safe='')}"

        # Escape markdown for Telegram display
        display_title = re.sub(r'([*_`\[\]])', r'\\\1', title)
        display_body = re.sub(r'^#{1,6}\s*', '', body, flags=re.MULTILINE)
        display_body = re.sub(r'([*_`\[\]])', r'\\\1', display_body)

        formatted = (
            f"👽 *Reddit Draft Ready*\n\n"
            f"*{display_title}*\n\n"
            f"{display_body}\n\n"
            f"👉 [Paste here (Web)]({submit_url})"
        )
        raise RedditManualPostRequired(formatted, title)
