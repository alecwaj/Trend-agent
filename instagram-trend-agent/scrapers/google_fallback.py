"""
Google Fallback Scraper — Last-resort discovery via Google search.
No API key required. Uses site:instagram.com/reel search + music keywords.

Priority: FALLBACK (when all other sources are exhausted or blocked)
"""

import logging
import re
import time
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

from scrapers import ReelData

logger = logging.getLogger(__name__)


class GoogleFallbackScraper:
    """
    Discovers Instagram Reels by scraping Google search results.
    Constructs reel IDs/URLs from search snippets and metadata.

    Note: This produces less metadata than direct scrapers but provides
    discovery of URLs that can be enriched later.
    """

    SEARCH_URL = "https://www.google.com/search"

    def __init__(self, config: dict):
        self.config = config
        self.sleep_between = config.get("sleep_between_requests", 5)
        self.results_per_query = config.get("results_per_query", 10)
        self.last_cost_cents = 0
        try:
            self.ua = UserAgent()
        except Exception:
            self.ua = None

    def _get_headers(self) -> dict:
        """Generate headers with a random user agent."""
        if self.ua:
            try:
                user_agent = self.ua.random
            except Exception:
                user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        else:
            user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"

        return {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    def scrape(self, keywords: List[str], max_results: int = 30) -> List[ReelData]:
        """
        Search Google for Instagram Reels matching music keywords.

        Args:
            keywords: List of hashtags or search terms
            max_results: Max reels to return

        Returns:
            List of ReelData objects (with minimal metadata from search snippets)
        """
        all_reels = []
        queries = self._build_queries(keywords)

        for query in queries:
            if len(all_reels) >= max_results:
                break

            reels = self._search_query(query)
            all_reels.extend(reels)
            logger.debug(f"Google query '{query[:50]}': {len(reels)} reels found")

            time.sleep(self.sleep_between)

        # Deduplicate by reel URL
        seen_urls = set()
        unique = []
        for r in all_reels:
            if r.url not in seen_urls:
                seen_urls.add(r.url)
                unique.append(r)

        return unique[:max_results]

    def _build_queries(self, keywords: List[str]) -> List[str]:
        """Build Google search queries from keyword list."""
        queries = []

        # Group hashtags into clusters for more efficient searches
        music_terms = " OR ".join(f'#{kw}' for kw in keywords[:5])
        queries.append(f'site:instagram.com/reel {music_terms}')

        # Direct hashtag searches for top hashtags
        for kw in keywords[:8]:
            queries.append(f'site:instagram.com/reel #{kw}')

        return queries

    def _search_query(self, query: str) -> List[ReelData]:
        """Execute a single Google search and extract Reel URLs."""
        params = {
            "q": query,
            "num": self.results_per_query,
            "hl": "en",
            "gl": "us",
        }

        try:
            resp = requests.get(
                self.SEARCH_URL,
                params=params,
                headers=self._get_headers(),
                timeout=15,
            )

            if resp.status_code == 429:
                logger.warning("Google rate limiting detected, backing off")
                time.sleep(30)
                return []

            resp.raise_for_status()
            return self._parse_search_results(resp.text, query)

        except requests.RequestException as e:
            logger.warning(f"Google search request failed: {e}")
            return []
        except Exception as e:
            logger.error(f"Google fallback unexpected error: {e}")
            return []

    def _parse_search_results(self, html: str, query: str) -> List[ReelData]:
        """Parse Google search results HTML to extract Instagram Reel URLs."""
        soup = BeautifulSoup(html, "lxml")
        reels = []

        # Find all result links
        for result in soup.find_all("a", href=True):
            href = result["href"]

            # Extract Instagram reel URLs
            reel_url = self._extract_instagram_url(href)
            if not reel_url:
                continue

            # Get snippet text for metadata extraction
            snippet = self._extract_snippet(result)
            reel = self._url_to_reel_data(reel_url, snippet, query)
            if reel:
                reels.append(reel)

        return reels

    def _extract_instagram_url(self, href: str) -> Optional[str]:
        """Extract clean Instagram reel URL from Google's redirect URL."""
        # Handle Google redirect URLs
        if "instagram.com/reel/" in href or "instagram.com/p/" in href:
            # Clean up the URL
            for prefix in ["/url?q=", "url?q="]:
                if prefix in href:
                    href = href.split(prefix)[1].split("&")[0]
                    break

            # Validate it's a real Instagram URL
            if "instagram.com" in href and ("/reel/" in href or "/p/" in href):
                # Normalize to clean URL
                parsed = urlparse(href)
                path = parsed.path.rstrip("/")
                return f"https://www.instagram.com{path}/"

        return None

    def _extract_snippet(self, element) -> str:
        """Extract text snippet from search result element."""
        parent = element.parent
        if parent:
            for _ in range(3):  # Walk up tree to find snippet container
                text = parent.get_text(separator=" ", strip=True)
                if len(text) > 30:
                    return text[:500]
                parent = parent.parent
        return ""

    def _url_to_reel_data(self, url: str, snippet: str, query: str) -> Optional[ReelData]:
        """Create a minimal ReelData from a discovered URL and snippet text."""
        try:
            # Extract shortcode from URL
            match = re.search(r"instagram\.com/(?:reel|p)/([A-Za-z0-9_-]+)", url)
            if not match:
                return None

            shortcode = match.group(1)

            # Extract hashtags from snippet
            hashtags = re.findall(r"#(\w+)", snippet.lower())

            # Extract username if present in snippet
            username_match = re.search(r"@(\w+)", snippet)
            username = username_match.group(1) if username_match else "unknown"

            return ReelData(
                reel_id=shortcode,  # Use shortcode as ID when we don't have real ID
                shortcode=shortcode,
                url=url,
                username=username,
                follower_count=0,   # Unknown from search results
                caption=snippet[:500],
                hashtags=hashtags,
                likes=0,            # Unknown from search results
                comments=0,
                views=0,
                posted_at=datetime.utcnow(),  # Unknown, use now as placeholder
                audio_name=None,
                audio_artist=None,
                duration_seconds=None,
                source="google_fallback",
                raw_metadata={"search_query": query, "discovery_method": "google_search"},
            )
        except Exception as e:
            logger.debug(f"Failed to create ReelData from URL {url}: {e}")
            return None
