"""
Content formatter — cleans up AI-generated content for each platform.
Ensures proper paragraph spacing, bullet/bold formatting, and indentation.
"""
import re
import logging

logger = logging.getLogger(__name__)


def _normalize_whitespace(text: str) -> str:
    """Collapse 3+ consecutive newlines into exactly 2 (one blank line)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Remove trailing whitespace on each line
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text.strip()


def _fix_bullet_points(text: str) -> str:
    """
    Ensure bullet points are consistently formatted:
    - Normalize •, -, *, → to consistent bullet style
    - Add blank line before bullet block if missing
    - Ensure single newline between bullets in the same list
    """
    lines = text.split("\n")
    result = []
    prev_was_bullet = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Detect bullet lines (•, -, *, →, numbered like 1., 2.)
        is_bullet = bool(re.match(r'^[\u2022\-\*\u2192\u2023\u25E6]\s', stripped)) or \
                    bool(re.match(r'^\d+[\.\)]\s', stripped))

        if is_bullet:
            # Normalize bullet char to • for LinkedIn/Medium, keep - for Reddit
            if not re.match(r'^\d+[\.\)]\s', stripped):
                stripped = re.sub(r'^[\u2022\-\*\u2192\u2023\u25E6]\s*', '• ', stripped)

            # Add blank line before first bullet in a block
            if not prev_was_bullet and result and result[-1].strip():
                result.append("")
            result.append(stripped)
            prev_was_bullet = True
        else:
            if prev_was_bullet and stripped:
                result.append("")
            result.append(line)
            prev_was_bullet = False

    return "\n".join(result)


def _fix_bold_text(text: str, platform: str) -> str:
    """
    Handle bold/italic markdown per platform:
    - LinkedIn: **bold** works natively in organic posts
    - Medium: Keep markdown bold for manual paste
    - Reddit: **bold** is native markdown
    - Twitter: Strip bold markers (no markdown support)
    - GitHub: Keep markdown as-is
    """
    if platform == "twitter":
        # Twitter doesn't support markdown — strip bold/italic markers
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'__(.+?)__', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'_(.+?)_', r'\1', text)
    elif platform == "linkedin":
        # Convert **bold** to Unicode math sans-serif bold
        normal = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        bold   = "𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗"
        table = str.maketrans(normal, bold)
        
        def to_unicode(m):
            return m.group(1).translate(table)
            
        text = re.sub(r'\*\*(.+?)\*\*', to_unicode, text)
        text = re.sub(r'__(.+?)__', to_unicode, text)
    elif platform in ("medium", "reddit", "github"):
        # Ensure **bold** pairs are balanced — fix orphan markers
        bold_count = text.count("**")
        if bold_count % 2 != 0:
            idx = text.rfind("**")
            text = text[:idx] + text[idx+2:]
    return text


def _fix_headings(text: str, platform: str) -> str:
    """
    Clean up markdown headings per platform:
    - LinkedIn: Convert ## to bold text (LinkedIn doesn't render #)
    - Medium: Keep headings for manual paste
    - Reddit: Keep headings (native markdown)
    - Twitter: Strip headings entirely
    """
    if platform == "linkedin":
        # Convert ## Heading to **Heading** (LinkedIn bold)
        text = re.sub(r'^#{1,6}\s*(.+)$', r'**\1**', text, flags=re.MULTILINE)
    elif platform == "twitter":
        text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    # Medium, Reddit, GitHub: keep headings as-is
    return text


def _ensure_paragraph_breaks(text: str) -> str:
    """
    Ensure short paragraphs are separated by blank lines.
    If two non-bullet, non-empty lines are adjacent and both are >40 chars,
    insert a blank line between them for readability.
    """
    lines = text.split("\n")
    result = []

    for i, line in enumerate(lines):
        result.append(line)
        if i < len(lines) - 1:
            curr = line.strip()
            nxt = lines[i + 1].strip()
            # Both are non-empty, non-bullet, substantial text lines
            is_curr_prose = curr and not curr.startswith(("•", "-", "*", "#", "**Takeaway")) \
                           and not re.match(r'^\d+[\.\)]', curr) and len(curr) > 40
            is_next_prose = nxt and not nxt.startswith(("•", "-", "*", "#", "**Takeaway")) \
                           and not re.match(r'^\d+[\.\)]', nxt) and len(nxt) > 40
            # If both are prose and no blank line between them already
            if is_curr_prose and is_next_prose and (i + 1 < len(lines)):
                # Check if next line in result would be blank
                if lines[i + 1].strip():
                    result.append("")

    return "\n".join(result)


def _fix_numbered_steps(text: str) -> str:
    """Ensure numbered steps (1. 2. 3.) have consistent formatting."""
    lines = text.split("\n")
    result = []
    prev_was_step = False

    for line in lines:
        stripped = line.strip()
        is_step = bool(re.match(r'^\d+[\.\)]\s', stripped))

        if is_step:
            if not prev_was_step and result and result[-1].strip():
                result.append("")
            result.append(stripped)
            prev_was_step = True
        else:
            if prev_was_step and stripped:
                result.append("")
            result.append(line)
            prev_was_step = False

    return "\n".join(result)


def format_content(text: str, platform: str) -> str:
    """
    Master formatter — applies all formatting fixes for the given platform.
    Does NOT alter the semantic content, only cleans up structure.
    """
    if not text or text.startswith("⚠️"):
        return text

    text = _normalize_whitespace(text)
    text = _fix_headings(text, platform)
    text = _fix_bold_text(text, platform)
    text = _fix_bullet_points(text)
    text = _fix_numbered_steps(text)
    text = _ensure_paragraph_breaks(text)
    text = _normalize_whitespace(text)  # final cleanup

    logger.debug(f"Formatted content for {platform} ({len(text)} chars)")
    return text
