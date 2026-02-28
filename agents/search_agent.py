"""
Trend & hashtag research agent using pytrends (Google Trends, no API key needed).
Falls back to curated defaults gracefully.
"""
import logging
from pytrends.request import TrendReq
from concurrent.futures import ThreadPoolExecutor
from googlesearch import search
from config import BRAND

logger = logging.getLogger(__name__)


class SearchAgent:
    """Fetch trending topics and generate relevant hashtags."""

    def __init__(self):
        self._pytrends_instance = None

    @property
    def pytrends(self):
        if self._pytrends_instance is None:
            # Provide higher timeout (retries=0 bypasses urllib3>2 method_whitelist crash)
            self._pytrends_instance = TrendReq(hl="en-US", tz=-330, timeout=(10, 25), retries=0)
        return self._pytrends_instance

    def get_trending_hashtags(self, topic: str) -> list[str]:
        """
        Returns a list of trending hashtag strings related to the topic.
        Falls back to curated defaults on any error.
        """
        try:
            # Build keyword list from topic + brand topics
            kws = self._extract_keywords(topic)
            self.pytrends.build_payload(kws, cat=0, timeframe="now 7-d", geo="IN")
            related = self.pytrends.related_queries()

            tags = set()
            for kw in kws:
                top_df = related.get(kw, {}).get("top")
                if top_df is not None and not top_df.empty:
                    for q in top_df["query"].head(5).tolist():
                        # Convert "machine learning" → #MachineLearning
                        tag = "#" + "".join(w.capitalize() for w in q.split())
                        tags.add(tag)

            result = list(tags)[:15]
            if not result:
                raise ValueError("No trends found")

            logger.info(f"Trends fetched: {result[:5]}")
            return result

        except Exception as e:
            logger.warning(f"Trend fetch failed ({e}), using defaults")
            return self._default_hashtags(topic)

    async def search_web_for_topic(self, topic: str, max_results: int = 3) -> str:
        """
        Use DuckDuckGo to grab the top snippets for a topic.
        Returns a single string of context to feed into the content generator.
        Should only run if the topic looks like current affairs or if explicitly needed.
        """
        try:
            logger.info(f"🔍 Searching web via Google for: {topic}")
            # advanced=True returns dictionaries with title, description, url
            results = list(search(topic, num=max_results, stop=max_results, pause=2.0, advanced=True))
            
            if not results:
                return ""
            
            snippets = []
            for i, r in enumerate(results):
                title = getattr(r, 'title', '')
                desc = getattr(r, 'description', '')
                if not title and not desc:  # Fallback for some versions of the library returning dicts
                    title = r.get("title", "") if isinstance(r, dict) else ""
                    desc = r.get("description", "") if isinstance(r, dict) else ""
                snippets.append(f"[{i+1}] {title}: {desc}")
            
            context = "\n\n".join(snippets)
            if context.strip() == "":
                raise Exception("Empty Google snippets returned")
                
            logger.info(f"✅ Web search found {len(snippets)} snippets")
            return context
        except Exception as e:
            logger.warning(f"Web search scrape failed: {e}")
            return ""

    def _extract_keywords(self, topic: str) -> list[str]:
        """Extract 1-5 keywords from topic string."""
        # Simple heuristic: use known brand topics that appear in the topic
        found = [t for t in BRAND["topics"] if t.lower() in topic.lower()]
        kws = found[:3] if found else [topic[:50]]
        # Always include at least one general keyword
        if "entrepreneur" not in " ".join(kws).lower():
            kws = (kws + ["entrepreneurship"])[:5]
        return kws[:5]

    def _default_hashtags(self, topic: str) -> list[str]:
        defaults = [
            "#BuildInPublic", "#Entrepreneur", "#TechTwitter",
            "#AI", "#Web3", "#Blockchain", "#FullStackDev",
            "#DSA", "#OpenSource", "#StartupLife",
            "#IndianTech", "#TechEntrepreneur", "#FrequnSync",
        ]
        # Add topic-specific defaults
        topic_lower = topic.lower()
        if "ai" in topic_lower or "machine learning" in topic_lower:
            defaults.insert(0, "#ArtificialIntelligence")
            defaults.insert(1, "#MachineLearning")
        if "blockchain" in topic_lower or "web3" in topic_lower:
            defaults.insert(0, "#DeFi")
            defaults.insert(1, "#Web3")
        if "dsa" in topic_lower or "algorithm" in topic_lower:
            defaults.insert(0, "#Algorithms")
            defaults.insert(1, "#CodingLife")
        return defaults[:12]
