import logging
import os
import httpx
import asyncio
import google.generativeai as genai
from config import GEMINI_API_KEY, GEMINI_MODEL, BRAND
from agents.content_formatter import format_content

logger = logging.getLogger(__name__)
genai.configure(api_key=GEMINI_API_KEY)

# ── Groq fallback client (lazy) ───────────────────────────────────────────────

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_PAT", "")
GITHUB_USERNAME = "ABR-Kapoor"

_groq_client = None


def _get_groq():
    global _groq_client
    if _groq_client is None and GROQ_API_KEY:
        try:
            from groq import AsyncGroq
            _groq_client = AsyncGroq(api_key=GROQ_API_KEY)
        except ImportError:
            logger.warning("groq package not installed — run: pip install groq")
    return _groq_client


def _is_quota_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(k in msg for k in ["429", "quota", "resource_exhausted", "resourceexhausted", "rate limit"])


async def _call_groq(system: str, user: str, model: str = "llama-3.3-70b-versatile") -> str:
    client = _get_groq()
    if client is None:
        raise RuntimeError("Groq fallback unavailable — add GROQ_API_KEY to .env")
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        max_tokens=2048,
        temperature=0.8,
    )
    return resp.choices[0].message.content.strip()


# ── GitHub Fetcher ─────────────────────────────────────────────────────────────

_GH_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    **({"Authorization": f"Bearer {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}),
}


async def fetch_github_repos(limit: int = 12) -> list[dict]:
    """
    Fetch Abeer's public repos from GitHub API, sorted by last pushed.
    Returns list of dicts: name, description, language, topics, stars, url.
    """
    url = f"https://api.github.com/users/{GITHUB_USERNAME}/repos"
    params = {"sort": "pushed", "direction": "desc", "per_page": limit, "type": "public"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=_GH_HEADERS, params=params)
            r.raise_for_status()
            repos = r.json()
            return [
                {
                    "name":        repo["name"],
                    "description": repo.get("description") or "",
                    "language":    repo.get("language") or "Unknown",
                    "topics":      repo.get("topics", []),
                    "stars":       repo.get("stargazers_count", 0),
                    "url":         repo["html_url"],
                }
                for repo in repos
            ]
    except Exception as e:
        logger.error(f"GitHub repo fetch failed: {e}")
        return []


async def fetch_repo_readme(repo_name: str) -> str:
    """
    Fetch README content for a specific repo. Returns raw text (max 3000 chars).
    Falls back to empty string on failure.
    """
    url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{repo_name}/readme"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers={**_GH_HEADERS, "Accept": "application/vnd.github.raw+json"})
            if r.status_code == 404:
                return ""
            r.raise_for_status()
            return r.text[:3000]
    except Exception as e:
        logger.warning(f"README fetch failed for {repo_name}: {e}")
        return ""


async def fetch_repos_with_readmes(limit: int = 8) -> list[dict]:
    """
    Fetch repos + their READMEs concurrently. Used for rich topic suggestions.
    """
    repos = await fetch_github_repos(limit=limit)
    if not repos:
        return []
    readmes = await asyncio.gather(*[fetch_repo_readme(r["name"]) for r in repos])
    for repo, readme in zip(repos, readmes):
        repo["readme"] = readme
    return repos


# ── SYSTEM PROMPT ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""
Main Abeer Kapoor hoon. 22 saal ka developer-entrepreneur from Chhattisgarh, India. BIT Bhilai mein MCA kar raha hoon.

MERI JOURNEY:
- IIT Bhilai hackathon jeeta — LalaAm app ke liye ₹10K mila
- SSTC hackathon — AuraSutra AI ke liye ₹12K
- HackIndia 2025 mein 85+ teams mein se Top 11
- INAE ka student member
- BizAi Community banai — exceptional log har stream se

MERI PRODUCTS (ye maine khud banaye hain):
- AuraSutra AI: Ayurveda patient management SaaS. 6 paying clients. 150Cr+ market potential.
- Skill Lover: AI career planning for Tier 2/3 India — roadmaps + ATS resume analyzer.
- CodeOnMe: LeetCode-type judge for Indian college students. Next.js + Judge0.
- LalaAm: Kids ke screen addiction ke liye gamified app. 30+ parents tested it.
- Slobby: AI business ecosystem + task roadmap generator.

MERA STYLE (non-negotiable):
- Seedha baat karta hoon. Fluff nahi deta.
- Hinglish naturally aata hai — forced nahi.
- Short paragraphs — 2-3 lines max at a time.
- Points use karta hoon to explain complex stuff.
- Naval + Nikhil Kamath + Kunal Shah — ye mera articulation benchmark hai.
- Nuclear bold — jo sach hai wo bolunga, hedging nahi karunga.
- "I" se post start nahi karta. Corporate buzzwords se allergy hai.
- Emojis? Max 1-2, sirf jab genuinely fit kare.
- Chanakya, Naval, Feynman, Ambedkar, Kalam, Gita — inhe quote karta hoon jab weight add ho.

HINGLISH VOCABULARY (naturally use karo):
yaar, bhai, seedha baat, sach mein, ek cheez, kaam aayega, samajh lo, mast hai,
chal raha hai, try karo, bata do, dekh, sunlo, waise, honestly bolun toh, thoda ruk

MERI BELIEFS (ye embed karo naturally):
- "India mein talent hai. Audacity ki kami hai."
- "Chhattisgarh limitation nahi hai. Origin story hai."
- "Gita ka core: outcome se detach raho. Best product mindset ever."
- "Agentic AI ek new species of labor hai. India ko own karna chahiye, sirf use nahi."
- "Great log tumhe nahi milte. Systems banao jo unhe attract kare."
- "Decentralization is a political idea wrapped in code."
- "Rankings receipts hain, assets nahi."

CONTENT PILLARS:
Builder logs | Geopolitics × Tech | Indian founder truths | DSA × systems thinking |
BizAi Community | Psychology × UX | Chhattisgarh rising | Product stories

QUALITY CHECK — har post pass kare:
1. Line 1 scroll rok de? Naval retweet kare?
2. Ek specific fact ho — number, project name, real experience?
3. BizAi/community ka brand bane — sirf mera ego nahi?
4. Honest ho — "founder content" nahi?
5. Tier 2 Indian kid seen feel kare — lectured nahi?

Topics: {', '.join(BRAND['topics'])}
"""

# ── PLATFORM INSTRUCTIONS ─────────────────────────────────────────────────────

PLATFORM_INSTRUCTIONS = {

    "linkedin": """
LinkedIn post likhna hai mujhe. STRICT CONSTRAINTS:

WORD LIMIT: 80-120 words. Isse zyada nahi.
CHARACTER LIMIT: 500-700 characters max.

FORMAT:
LINE 1 — HOOK (max 12 words, "I" se start nahi):
Shocking stat / paradox / sarcastic truth / Chanakya-style opening

[blank line]

3 BULLETS (har ek max 15 words):
• **Label:** insight — meri real experience se
• **Label:** insight — project ya life reference
• **Label:** insight — actionable ya uncomfortable

[blank line]

CLOSING: Question ya Hinglish CTA. Max 12 words.

[blank line]

3-4 hashtags: #BuildInPublic #BizAiCommunity #IndianFounder #TechIndia #AgenticAI

FORMATTING:
- Proper line breaks between sections
- Bold for labels using **text**
- Single blank line between paragraphs
- No wall of text

Return ONLY the post. No intro.
""",

    "twitter": """
Twitter/X post. HARD LIMIT: 270 characters max. Seriously count.

FORMAT:
[Truth-bomb opener — compressed, punchy]
[One-line proof from my life or Indian reality]
[Optional: sharp question]

RULES:
- NO markdown (Twitter doesn't support it)
- Max 1-2 hashtags at end
- No emoji spam
- Line breaks allowed but keep it tight
- Think Naval — one truth, ruthlessly edited

THREAD (only if depth needed): 5-8 tweets, each under 270 chars.
Tweet 1: Controversial claim + 🧵
Tweet 2-N: One proof each
Last: Conclusion + CTA

Return ONLY the tweet. No explanation.
""",

    "reddit": """
Reddit post. MAX 200 words. Reddit hates founder content.

FORMAT:
Title: [Honest, specific, searchable — no clickbait]

[Para 1: Real situation/frustration — hyper-specific. 2-3 sentences.]

[Para 2: My honest question or observation. 2-3 sentences.]

[Para 3 optional: What I tried / got wrong. 1-2 sentences.]

Ending: Genuine open question — actually curious.

STRICT RULES:
- NO hashtags ever
- NO emojis ever
- NO CTAs or self-promo
- NO bold/italic markdown abuse
- Write like a peer, not a founder
- Proper paragraph breaks (double newline)
- Each paragraph 2-3 sentences max

Return ONLY the post.
""",

    "medium": """
Medium article. MAX 350 words. Short and strategic.

FORMAT:
TITLE: [5-7 words, punchy, counterintuitive]
SUBTITLE: [One sentence core argument]

[Para 1: Hook + ground reality. 2 sentences. Personal.]

[Para 2: Contrarian insight. First principles. 2-3 sentences.]

[Para 3: What I built / what India needs. 2-3 sentences. Reference products only if genuinely relevant.]

**Takeaway:** [One bold sentence. Max 12 words. Quotable.]

Tags: tag1, tag2, tag3, tag4

FORMATTING:
- Proper paragraph spacing
- Bold for emphasis sparingly
- Short paragraphs (2-3 sentences each)
- No walls of text

Return ONLY the article.
""",

   "pinterest": """
Pinterest pin description. MAX 400 characters.

FORMAT:
[Headline: 6-8 words, keyword-rich]

[2-3 lines insight. Softer tone — inspiring not nuclear.]

[Soft CTA: "Save this." / "Link in bio."]

Keywords: keyword1, keyword2, keyword3, keyword4, keyword5

BOARD: [board name]
IMAGE PROMPT: [one sentence visual description, dark mode preferred]

Return ONLY the pin copy.
""",

    "github": """
GitHub commit comment for DSA_Java repo. STRICTLY 1-2 lines.

FORMAT:
[What this does + time/space complexity OR practical insight]

RULES:
- Developer tone only
- Zero marketing
- Zero emojis
- No fluff
- Max 50 words

If creating new DSA file: match existing code style, proper Java naming.

Return ONLY the comment.
""",
}

# ── TELEGRAM PREVIEW LIMIT ────────────────────────────────────────────────────

TELEGRAM_MAX = 3800


def _safe_truncate(text: str, platform: str) -> str:
    if len(text) <= TELEGRAM_MAX:
        return text
    return text[:TELEGRAM_MAX] + f"\n\n_[... truncated for preview — full {platform} post will be posted]_"


# ── MAIN AGENT ────────────────────────────────────────────────────────────────

class ContentAgent:
    def __init__(self):
        self.model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=SYSTEM_PROMPT,
        )

    async def _generate_text(self, prompt: str, label: str = "") -> str:
        """Try Gemini first. On quota error auto-fallback to Groq llama-3."""
        try:
            response = await self.model.generate_content_async(prompt)
            return response.text.strip()
        except Exception as e:
            if _is_quota_error(e):
                logger.warning(f"Gemini quota hit{' for ' + label if label else ''} — switching to Groq ⚡")
                return await _call_groq(SYSTEM_PROMPT, prompt)
            raise

    async def generate(
        self,
        topic: str,
        platforms: list[str],
        context: str = "",
        style_override: str = "",
        web_context: str = "",
    ) -> dict[str, str]:
        """Generate content for each selected platform."""
        results: dict[str, str] = {}
        context_str = f"\n\nContext (natural continuation of previous post):\n{context}\n" if context else ""
        style_str   = f"\n\nStyle override:\n{style_override}\n" if style_override else ""
        web_context_str = f"\n\nWEB SEARCH CONTEXT (factual grounding):\n{web_context}\n(Use this factual data naturally if relevant, DO NOT hallucinate facts.)\n" if web_context else ""

        for platform in platforms:
            instruction = PLATFORM_INSTRUCTIONS.get(platform, "")
            prompt = f"{instruction}{context_str}{style_str}{web_context_str}\n\nTOPIC: {topic}"
            try:
                raw = await self._generate_text(prompt, label=platform)
                raw = format_content(raw, platform)
                results[platform] = _safe_truncate(raw, platform)
                logger.info(f"✅ Content generated for {platform} ({len(raw)} chars)")
            except Exception as e:
                logger.error(f"Content generation failed for {platform}: {e}")
                results[platform] = f"⚠️ Generation failed: {e}"

        return results

    async def regenerate(
        self,
        topic: str,
        platform: str,
        previous_content: str,
        edit_instruction: str,
    ) -> str:
        """Rewrite content based on user's edit instruction."""
        instr = PLATFORM_INSTRUCTIONS.get(platform, "")
        prompt = f"""
{instr}

ORIGINAL POST:
{previous_content}

ABEER SAYS: {edit_instruction}
TOPIC: {topic}

Rewrite following ALL platform rules. Keep Abeer's voice: nuclear boldness, real projects,
Hinglish where natural. Return ONLY the rewritten content. No explanation.
"""
        try:
            result = await self._generate_text(prompt, label=f"regenerate/{platform}")
            result = format_content(result, platform)
            return _safe_truncate(result, platform)
        except Exception as e:
            logger.error(f"Regeneration failed: {e}")
            return previous_content

    async def generate_hashtags(self, topic: str, trending: list[str]) -> list[str]:
        prompt = f"""
Generate 7 relevant hashtags for Abeer Kapoor's post about: "{topic}"

Context: Indian developer-entrepreneur, BizAi Community founder, builder of AuraSutra AI,
Skill Lover, CodeOnMe, LalaAm. Chhattisgarh. Geopolitics, agentic AI, blockchain.

Trending to consider: {', '.join(trending[:5]) if trending else 'none'}

Rules:
- Mix niche + broad
- Always include one from: #BuildInPublic #BizAiCommunity #IndianFounder
- Include product tag if relevant: #AuraSutra #SkillLover #CodeOnMe
- No generic spam tags
Return ONLY hashtags, one per line, with # symbol. No explanation.
"""
        try:
            text = await self._generate_text(prompt, label="hashtags")
            tags = [ln.strip() for ln in text.split("\n") if ln.strip().startswith("#")]
            return tags[:8]
        except Exception as e:
            logger.error(f"Hashtag generation failed: {e}")
            return ["#BuildInPublic", "#BizAiCommunity", "#IndianFounder", "#TechIndia", "#AgenticAI"]

    async def suggest_topics(
        self,
        repos: list[dict] | None = None,
        recent_posts: list[dict] | None = None,
        use_github: bool = True,
        web_context: str = "",
    ) -> list[str]:
        """
        Suggest 5 content topics. If use_github=True (default), fetches Abeer's
        latest repos + READMEs directly from GitHub API for rich context.
        Falls back to passed-in repos list if GitHub fetch fails.
        """
        # ── Fetch from GitHub if enabled ──────────────────────────────────────
        if use_github:
            logger.info("Fetching repos + READMEs from GitHub...")
            fetched = await fetch_repos_with_readmes(limit=8)
            if fetched:
                repos = fetched
                logger.info(f"✅ Fetched {len(repos)} repos from GitHub")
            else:
                logger.warning("GitHub fetch returned nothing — using passed-in repos")

        repos = repos or []
        recent_posts = recent_posts or []

        # ── Build repo context string ─────────────────────────────────────────
        repo_lines = []
        for r in repos[:8]:
            readme_snippet = r.get("readme", "")[:400].replace("\n", " ").strip()
            line = f"- [{r['language']}] {r['name']}: {r['description']}"
            if readme_snippet:
                line += f"\n  README: {readme_snippet}"
            repo_lines.append(line)
        repo_info = "\n".join(repo_lines) if repo_lines else "No repos available."

        recent = "\n".join([f"- {p['topic']}" for p in recent_posts[:3]]) if recent_posts else "None"

        prompt = f"""
Suggest 5 extremely punchy content topics for Abeer Kapoor's personal brand (LinkedIn, X, Medium, Reddit).

ABOUT ABEER:
- 22, developer-entrepreneur, Chhattisgarh, India. MCA at BIT Bhilai.
- Products: AuraSutra AI, Skill Lover, CodeOnMe, LalaAm, Slobby
- Community: BizAi — exceptional people from every stream
- Interests: Geopolitics × Tech, agentic AI, blockchain, human psychology, UX systems
- Voice: Nuclear bold. Chanakya × Naval. No generic motivation. Specific + real.

CURRENT INTERNET TRENDS:
{web_context if web_context else "None provided"}

GITHUB REPOS (latest, with README context):
{repo_info}

RECENT POSTS (avoid these angles exactly):
{recent}

CRITICAL RULES:
- EXACTLY 5 WORDS OR LESS per suggestion. (e.g. "Local LLMs killing SaaS costs")
- Each connects at least 2 of: tech, geopolitics, entrepreneurship, India, psychology.
- Start with a relevant single emoji.
- Relate strongly to Current Internet Trends if provided.

Return ONLY 5 lines. No numbering. No explanation.
"""
        try:
            text = await self._generate_text(prompt, label="suggest_topics")
            return [ln.strip() for ln in text.split("\n") if ln.strip()][:5]
        except Exception as e:
            logger.error(f"Topic suggestion failed: {e}")
            return [
                "🏥 Why I chose a Local LLM over GPT-4 for AuraSutra — and what it cost me",
                "🎯 Skill Lover: fixing career guidance for 40 crore Tier 2/3 students with ₹0 coaching",
                "⚔️ Semiconductor export wars — and why every Indian dev should care right now",
                "🧠 What 50+ psychology studies taught me before I built LalaAm's UX",
                "🔥 BizAi isn't a community. It's a selection algorithm for great people.",
            ]