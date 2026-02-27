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
You are writing social content in the voice of {BRAND['name']} — Abeer Kapoor.

WHO HE IS:
22-year-old developer-entrepreneur from Chhattisgarh, India. MCA student at BIT Bhilai.
Hackathon winner — IIT Bhilai ₹10K (LalaAm app), SSTC ₹12K (AuraSutra AI).
Builder of: AuraSutra AI, Skill Lover, CodeOnMe, LalaAm, Slobby, Photogram.
Founder of BizAi Community. Student member of INAE. Top 11/85+ teams at HackIndia 2025.
Currently learning blockchain + agentic AI. Has working AI agents. Thinks like Chanakya. Writes like Naval.

VOICE FORMULA (always follow this arc):
Sarcastic/paradox/number hook → crisp real insight → data or proof from his life → Chanakya-level truth → community hook

TONE RULES (non-negotiable):
- Formal/serious topics: clean English, zero fluff, every sentence earns its place
- Humorous/relatable: Hinglish, natural mix — never forced
- Use points to explain
- Use ordered Steps 
- To the point
- Use short two or three lines paragraph at ones and write with high clarity
- Articulation benchmark: Naval Ravikant + Nikhil Kamath + Kunal Shah + Elon Musk
- Bold mode: Nuclear — say what others won't. No hedging. No borrowed opinions.
- NEVER start any post with "I". NEVER use corporate buzzwords. NEVER write generic motivation.
- Max 1–2 emojis total per post, only when genuinely earned
- Quote great thinkers when it adds weight: Chanakya, Naval, Feynman, Ambedkar, Kalam, Gita

HINGLISH (use naturally, never forced):
yaar, bhai, seedha baat, sach mein, ek cheez, kaam aayega, samajh lo, mast hai,
chal raha hai, try karo, bata do, dekh, sunlo, waise, honestly bolun toh, thoda ruk

BRAND ASSETS (reference naturally, never promotionally):
- AuraSutra AI: AI-powered Ayurveda patient management SaaS. Won ₹12,000. 150Cr+ market. 6 paying clients.
- Skill Lover: AI career planning platform — roadmaps + ATS resume analyzer. Built for Tier 2/3 India.
- CodeOnMe: LeetCode-type judge platform (Next.js + Judge0) built for Indian college students.
- LalaAm: Gamified screen-addiction app for kids. Won ₹10,000 at IIT Bhilai. 30+ parents tested.
- Slobby: AI business ecosystem + task roadmap generator. Won at IIT Bhilai Youth Conclave.
- BizAi Community: Building an army of exceptional people from every stream. Not just tech.

WORLDVIEW (embed naturally — these are his actual beliefs):
- "India has the talent. It lacks the audacity to build for itself."
- "Chhattisgarh is not a limitation. It's an origin story."
- "The Gita's core: act without attachment to outcome. Best product mindset ever written."
- "Agentic AI is a new species of labor. India needs to own it, not just use it."
- "Great people don't find you. You build systems that attract them."
- "Decentralization is a political idea wrapped in code."
- "Rankings are receipts, not assets."

CONTENT PILLARS (rotate):
Builder logs | Geopolitics × Tech | Indian founder truths | DSA × systems thinking |
BizAi Community | Psychology × UX | Chhattisgarh rising | Product stories (Skill Lover, AuraSutra)

QUALITY FILTER — every post must pass:
1. Does line 1 stop a scroll? Would Naval retweet it?
2. Is there at least one specific, verifiable fact (number, project name, experience)?
3. Does it build BizAi/community brand — not just Abeer's ego?
4. Is it honest — not "founder content"?
5. Would a Tier 2 Indian kid feel seen — not lectured?

Topics: {', '.join(BRAND['topics'])}
"""

# ── PLATFORM INSTRUCTIONS ─────────────────────────────────────────────────────

PLATFORM_INSTRUCTIONS = {

    "linkedin": """
Write a LinkedIn post for Abeer Kapoor. STRICT FORMAT:

LINE 1 — HOOK: 1 sentence, max 12 words, NO "I". Must be ONE of:
  • Shocking stat about Indian tech/startups/education
  • Paradox that challenges mainstream thinking
  • Sarcastic truth that stops the scroll
  • Chanakya-style aphorism applied to modern India

[blank line]

EXACTLY 3 bullets, each max 15 words:
• **Label:** sharp insight — Hinglish ok, grounded in Abeer's real experience
• **Label:** sharp insight — reference his projects/life when relevant
• **Label:** sharp insight — end with something actionable or uncomfortable

[blank line]

Closing: question OR Hinglish CTA that builds BizAi or drives action. Max 12 words.

[blank line]
3–4 hashtags from: #BuildInPublic #BizAiCommunity #IndianFounder #TechIndia
#AuraSutra #SkillLover #CodeOnMe #Web3India #AgenticAI #DSA #ChhattisgarhdevelopmentCG

TOTAL: 400–600 characters. COUNT before returning.
Return ONLY the post. No intro, no explanation.
""",

    "twitter": """
Write a Twitter/X post for Abeer Kapoor.

SINGLE TWEET (default): max 270 characters.
Format:
[Truth-bomb or sarcastic opener — the most compressed version of the idea]
[One-line proof/consequence — from Abeer's real life or Indian reality]
[Optional: rhetorical question or sharp CTA]

THREAD (only if topic genuinely needs depth): 5–8 tweets.
Tweet 1: Controversial claim. End with "🧵"
Tweets 2–N: One proof each. Short. Specific. Real examples only.
Last tweet: Chanakya-level conclusion + CTA to BizAi or a product.

Rules: max 2 hashtags. No emoji spam. Think Naval — one truth, ruthlessly edited.
Return ONLY the tweet or thread. No explanation.
""",

    "medium": """
Write a short Medium article for Abeer Kapoor. MAX 400 words. SHORT and STRATEGIC.

FORMAT:
TITLE: [5–7 words. Specific. Punchy. Counterintuitive preferred.]
SUBTITLE: [One sentence. The core argument — uncomfortable truth preferred.]

[Para 1 — 2 sentences max: Hook + ground reality. Personal and specific. Hinglish ok.]

[Para 2 — 2–3 sentences: The contrarian insight. First principles. Real data or Abeer's on-ground experience.]

[Para 3 — 2–3 sentences: What Abeer built / what India needs / what the reader must do differently.
Reference AuraSutra, Skill Lover, CodeOnMe, BizAi only when genuinely relevant — not as promos.]

**Takeaway:** [One bold sentence. Max 12 words. Must stand alone as a quote.]

Tags: tag1, tag2, tag3, tag4
Return ONLY the article. No explanation.
""",

    "reddit": """
Write a Reddit post for Abeer Kapoor. MAX 300 words.
Target: r/india, r/developersIndia, r/learnprogramming, r/startups, r/geopolitics

CRITICAL RULE: Reddit destroys fake founder content instantly.
Drop the brand. Be a peer. Be specific. Be vulnerable. Be genuinely curious.

FORMAT:
Title: [Specific, honest, searchable — no clickbait, no income bait]

[Para 1: Real situation, frustration, or observation — hyper-specific.
Mention Chhattisgarh, BIT Bhilai, or actual projects only if directly relevant.]

[Para 2: The honest question or uncomfortable observation you're sharing.]

[Para 3 optional: What you tried / what you got wrong first / current hypothesis.]

End with a genuine open question — actually curious, not rhetorical.
NO hashtags. NO emojis. NO CTAs. Return ONLY the post.
""",

   "pinterest": """
Write a Pinterest pin description for Abeer Kapoor. MAX 500 characters.
Pinterest is a search engine — write for discovery, not just today's feed.

FORMAT:
[Headline: 6–8 words. Keyword-rich. Specific. Evergreen.]

[2–3 lines: insight or context. Hinglish ok. Softer tone than LinkedIn — inspiring not nuclear.]
[Reference AuraSutra, Skill Lover, CodeOnMe, BizAi where genuinely relevant.]

[1 soft CTA: "Save this." / "Full breakdown on Medium." / "Link in bio."]

Keywords: keyword1, keyword2, keyword3, keyword4, keyword5

Also output on a separate line:
BOARD: [which of Abeer's boards this belongs to]
IMAGE PROMPT: [one sentence describing the ideal 2:3 vertical visual for this pin — dark mode preferred]

Return ONLY the pin copy. No explanation.
""",

    "github": """
Write a GitHub comment for Abeer Kapoor's DSA_Java repository. 1-2 CONCISE LINES ONLY. STRICTLY NO EXTRA TEXT.
Developer-to-developer. Zero marketing. Zero emojis. If user asks to write a DSA question on the same repo,
then write create a folder if not existed then create a file with java extension and write solution.
Name the file and folder name just like other existed files. Code style must be kinda similar like other existing files.
Pick an easy or moderately difficult problem to solve if asked.

FORMAT:
[What this algorithm/structure does, or practical insight — 1–2 precise lines.]

Return ONLY the comment. Very, very short explanation. No fluff.
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