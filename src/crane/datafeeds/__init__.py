"""
Base classes and interfaces for CRANE datafeeds.

To add a new datafeed source, subclass NewsFeed or PriceFeed
and implement the required methods.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any


class NewsFeed(ABC):
    """Abstract base for news headline ingestion.

    Subclasses must implement fetch() to return a list of news items.
    """

    @abstractmethod
    def fetch(self) -> List[Dict[str, Any]]:
        """Fetch new headlines since the last poll.

        Returns:
            List of dicts with keys:
                - title (str): headline text
                - url (str): source URL
                - published_at (str): ISO-8601 timestamp
                - source (str): source name
                - body (str, optional): full article text
        """
        ...


class PriceFeed(ABC):
    """Abstract base for market price snapshots.

    Subclasses must implement fetch_snapshots().
    """

    @abstractmethod
    def fetch_snapshots(self) -> Dict[str, Optional[float]]:
        """Fetch latest prices for tracked assets.

        Returns:
            dict mapping canonical symbol (ES, NQ, CL, BTC, ETH)
            to price or None.
        """
        ...
