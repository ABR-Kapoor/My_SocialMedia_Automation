"""
Twitter / X Platform — Manual intent posting only.
Returns a direct link to post the drafted content.
"""
import logging
import urllib.parse

logger = logging.getLogger(__name__)

class TwitterManualPostRequired(Exception):
    """
    Raised when Twitter post is requested.
    Carries formatted Telegram-ready content for manual publish.
    """
    def __init__(self, telegram_text: str, title: str):
        self.telegram_text = telegram_text
        self.title = title
        super().__init__(f"Twitter draft ready for manual post: {title}")

class TwitterPlatform:
    """
    Twitter Platform Handler.
    Raises TwitterManualPostRequired with an intent link and the formatted text.
    """
    def __init__(self):
        pass

    async def post(self, content: str, image_bytes: bytes | None = None) -> str:
        """
        Parses content and provides a manual Twitter intent link.
        """
        import re
        text_encoded = urllib.parse.quote(content, safe='')
        intent_url = f"https://twitter.com/intent/tweet?text={text_encoded}"
        
        # Escape markdown for Telegram display
        display_content = re.sub(r'^#{1,6}\s*', '', content, flags=re.MULTILINE)
        display_content = re.sub(r'([*_`\[\]])', r'\\\1', display_content)

        formatted = (
            f"🐦 *Twitter Draft Ready*\n\n"
            f"{display_content}\n\n"
            f"👉 [Paste here (Web)]({intent_url})"
        )
        raise TwitterManualPostRequired(formatted, "Twitter Draft")
