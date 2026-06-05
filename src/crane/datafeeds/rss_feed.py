"""
RSS News Feed — polls RSS/Atom feeds for headlines.

Zero-cost alternative to proprietary news APIs.
Configured via config.yaml or environment variables.

Supports:
  - Standard RSS 2.0 feeds
  - Atom feeds
  - JSON feeds
  - Custom API endpoints (via requests)
"""

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from xml.etree import ElementTree

import requests
import yaml

from crane.datafeeds import NewsFeed

logger = logging.getLogger(__name__)

# Default feeds if none configured
DEFAULT_FEEDS = [
    {
        "name": "reuters-business",
        "url": "https://feeds.reuters.com/reuters/businessNews",
        "type": "rss",
    },
    {
        "name": "cnbc-finance",
        "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
        "type": "rss",
    },
    {
        "name": "marketwatch-latest",
        "url": "https://feeds.marketwatch.com/marketwatch/topstories/",
        "type": "rss",
    },
]


class RSSFeed(NewsFeed):
    """Polls RSS, Atom, or JSON feeds for news headlines.

    Deduplicates by SHA-256 hash of the headline title.
    Filters out items older than max_age_hours.
    """

    def __init__(
        self,
        feeds: Optional[List[Dict[str, Any]]] = None,
        user_agent: Optional[str] = None,
        timeout: int = 15,
        max_age_hours: int = 48,
    ):
        """
        Args:
            feeds: List of feed config dicts (name, url, type).
                   Defaults to a curated set of free financial RSS feeds.
            user_agent: HTTP User-Agent header.
            timeout: HTTP request timeout.
            max_age_hours: Skip items older than this.
        """
        self.feeds = feeds or DEFAULT_FEEDS
        self.timeout = timeout
        self.max_age_hours = max_age_hours
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent or (
                "Mozilla/5.0 (compatible; CRANE/1.0; "
                "+https://github.com/a3igner/crane)"
            ),
        })
        self._seen_hashes: set = set()

    def fetch(self) -> List[Dict[str, Any]]:
        """Fetch all configured feeds and return deduplicated headlines."""
        all_items = []
        cutoff = time.time() - (self.max_age_hours * 3600)

        for feed_cfg in self.feeds:
            try:
                items = self._fetch_feed(feed_cfg, cutoff)
                all_items.extend(items)
                logger.info(
                    "Fetched %d items from %s", len(items), feed_cfg["name"]
                )
            except Exception as exc:
                logger.error(
                    "Failed to fetch feed %s: %s", feed_cfg["name"], exc
                )

        # Deduplicate
        seen: set = set()
        unique = []
        for item in all_items:
            h = hashlib.sha256(item["title"].encode("utf-8")).hexdigest()
            if h not in seen:
                seen.add(h)
                unique.append(item)

        logger.info(
            "RSSFeed: %d unique headlines from %d feeds",
            len(unique),
            len(self.feeds),
        )
        return unique

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fetch_feed(
        self, cfg: Dict[str, Any], cutoff: float
    ) -> List[Dict[str, Any]]:
        url = cfg["url"]
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        text = resp.text

        if cfg.get("type") == "json" or "json" in content_type:
            return self._parse_json_feed(text, cfg, cutoff)
        else:
            return self._parse_xml_feed(text, cfg, cutoff)

    def _parse_xml_feed(
        self, xml_text: str, cfg: Dict, cutoff: float
    ) -> List[Dict[str, Any]]:
        items = []
        root = ElementTree.fromstring(xml_text)

        # RSS 2.0: /rss/channel/item
        for item_elem in root.iter("item"):
            title = self._get_text(item_elem, "title")
            link = self._get_text(item_elem, "link")
            pub_date_str = self._get_text(item_elem, "pubDate")
            description = self._get_text(item_elem, "description")

            if not title or not link:
                continue

            published = self._parse_date(pub_date_str) if pub_date_str else datetime.now(timezone.utc)

            # Filter old items
            if published.timestamp() < cutoff:
                continue

            items.append({
                "title": title.strip(),
                "url": link.strip(),
                "published_at": published.isoformat(),
                "source": cfg.get("name", "rss"),
                "body": description.strip() if description else "",
            })

        # Atom: /feed/entry
        if not items:
            for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
                title = self._get_text(entry, "{http://www.w3.org/2005/Atom}title")
                link_elem = entry.find("{http://www.w3.org/2005/Atom}link")
                link = link_elem.get("href") if link_elem is not None else None
                published_str = self._get_text(entry, "{http://www.w3.org/2005/Atom}published")
                if not title or not link:
                    continue
                published = self._parse_date(published_str) if published_str else datetime.now(timezone.utc)
                if published.timestamp() < cutoff:
                    continue
                items.append({
                    "title": title.strip(),
                    "url": link,
                    "published_at": published.isoformat(),
                    "source": cfg.get("name", "atom"),
                    "body": "",
                })

        return items

    def _parse_json_feed(
        self, json_text: str, cfg: Dict, cutoff: float
    ) -> List[Dict[str, Any]]:
        import json
        data = json.loads(json_text)
        items = []
        for entry in data.get("items", []):
            title = entry.get("title") or entry.get("title_text", "")
            url = entry.get("url") or entry.get("external_url", "")
            published_str = entry.get("date_published") or entry.get("created_at", "")
            if not title or not url:
                continue
            published = self._parse_date(published_str) if published_str else datetime.now(timezone.utc)
            if published.timestamp() < cutoff:
                continue
            items.append({
                "title": title.strip(),
                "url": url,
                "published_at": published.isoformat(),
                "source": cfg.get("name", "json"),
                "body": entry.get("content_text", ""),
            })
        return items

    @staticmethod
    def _get_text(parent, tag: str) -> Optional[str]:
        elem = parent.find(tag)
        return elem.text if elem is not None and elem.text else None

    @staticmethod
    def _parse_date(date_str: str) -> datetime:
        """Parse various RSS date formats."""
        from email.utils import parsedate_to_datetime
        try:
            return parsedate_to_datetime(date_str)
        except (ValueError, TypeError):
            pass
        # Try ISO format
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass
        return datetime.now(timezone.utc)
