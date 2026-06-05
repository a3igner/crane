"""
Yahoo Finance datafeed — fetches live price snapshots for CRANE's tracked assets.

Provides a zero-cost alternative to proprietary market data APIs by scraping
Yahoo Finance HTML pages. This is the DEFAULT datafeed; users can swap in
any datafeed by implementing the same interface.

Tracked symbols:
  ES=F      — S&P 500 E-mini Futures
  NQ=F      — Nasdaq 100 E-mini Futures
  CL=F      — Crude Oil Futures
  BTC-USD   — Bitcoin / USD
  ETH-USD   — Ethereum / USD

Usage:
    from crane.datafeeds.yahoo_feed import YahooFeed
    feed = YahooFeed()
    prices = feed.fetch_snapshots()
    # returns dict: {'ES=F': 5432.50, 'NQ=F': 19234.75, ...}
"""

import re
import time
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

SYMBOLS = {
    "ES=F": "ES=F",
    "NQ=F": "NQ=F",
    "CL=F": "CL=F",
    "BTC-USD": "BTC-USD",
    "ETH-USD": "ETH-USD",
}

# Mapping from Yahoo symbol to our canonical short names
CANONICAL = {
    "ES=F": "ES",
    "NQ=F": "NQ",
    "CL=F": "CL",
    "BTC-USD": "BTC",
    "ETH-USD": "ETH",
}

YAHOO_QUERY_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1m"
YAHOO_SCRAPE_URL = "https://finance.yahoo.com/quote/{symbol}/"


class YahooFeed:
    """Fetches live price snapshots from Yahoo Finance.

    Uses the public Yahoo Finance query API (no auth required).
    Implements rate-limiting and fallback to HTML scraping.
    """

    def __init__(self, rate_limit: float = 1.0, timeout: int = 10):
        """
        Args:
            rate_limit: Minimum seconds between API calls (Yahoo rate limiting).
            timeout: HTTP request timeout in seconds.
        """
        self._last_call = 0.0
        self.rate_limit = rate_limit
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
        })

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def fetch_snapshots(self) -> Dict[str, Optional[float]]:
        """Fetch current prices for all tracked assets.

        Returns:
            dict mapping canonical symbol name (ES, NQ, CL, BTC, ETH)
            to its latest price, or None if the fetch failed for that symbol.
        """
        result: Dict[str, Optional[float]] = {}
        for yahoo_symbol in SYMBOLS:
            price = self._fetch_single(yahoo_symbol)
            canonical = CANONICAL[yahoo_symbol]
            result[canonical] = price
            if price is not None:
                logger.debug("Fetched %s = %.2f", canonical, price)
            else:
                logger.warning("Failed to fetch %s", canonical)
        return result

    def fetch_snapshot(self, symbol: str) -> Optional[float]:
        """Fetch a single symbol's price.

        Args:
            symbol: Yahoo symbol (e.g. 'ES=F', 'BTC-USD').

        Returns:
            Latest price as float, or None on failure.
        """
        return self._fetch_single(symbol)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rate_limit(self):
        """Ensure minimum interval between API calls."""
        elapsed = time.time() - self._last_call
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self._last_call = time.time()

    def _fetch_single(self, symbol: str) -> Optional[float]:
        """Try JSON API first, fall back to HTML scraping."""
        self._rate_limit()

        # Primary: JSON query API
        price = self._fetch_json(symbol)
        if price is not None:
            return price

        # Fallback: HTML scrape
        logger.info("JSON API failed for %s, trying HTML scrape", symbol)
        return self._fetch_html(symbol)

    def _fetch_json(self, symbol: str) -> Optional[float]:
        """Fetch price via Yahoo Finance chart API (JSON endpoint)."""
        url = YAHOO_QUERY_URL.format(symbol=symbol)
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()

            # Navigate: chart -> result[0] -> meta -> regularMarketPrice
            meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
            price = meta.get("regularMarketPrice")
            if price is not None:
                return float(price)

            # Fallback: extract from indicators -> quote
            indicators = data.get("chart", {}).get("result", [{}])[0].get("indicators", {})
            quote = indicators.get("quote", [{}])[0]
            closes = quote.get("close", [])
            # Get the last non-None close
            for c in reversed(closes):
                if c is not None:
                    return float(c)
            return None

        except (requests.RequestException, ValueError, IndexError, TypeError) as exc:
            logger.debug("JSON fetch failed for %s: %s", symbol, exc)
            return None

    def _fetch_html(self, symbol: str) -> Optional[float]:
        """Fallback: scrape price from Yahoo Finance HTML page."""
        url = YAHOO_SCRAPE_URL.format(symbol=symbol)
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            html = resp.text

            # Try multiple regex patterns for the price
            patterns = [
                r'data-test="market-trading-symbol-price"[^>]*>\$?([\d,]+\.?\d*)',
                r'data-field="regularMarketPrice"[^>]*value="([\d.]+)"',
                r'<fin-streamer[^>]*data-symbol="' + re.escape(symbol) + r'"[^>]*>([\d,]+\.?\d*)',
                r'<span class="Trsdu\(0\.3s\)[^"]*"[^>]*>([\d,]+\.?\d*)',
            ]
            for pattern in patterns:
                match = re.search(pattern, html)
                if match:
                    raw = match.group(1).replace(",", "")
                    return float(raw)

            logger.debug("No price pattern matched in HTML for %s", symbol)
            return None

        except (requests.RequestException, ValueError) as exc:
            logger.debug("HTML scrape failed for %s: %s", symbol, exc)
            return None


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    feed = YahooFeed()
    prices = feed.fetch_snapshots()
    ts = datetime.now(timezone.utc).isoformat()
    print(f"[{ts}] CRANE Price Snapshots:")
    for sym, price in prices.items():
        status = f"${price:,.2f}" if price is not None else "N/A"
        print(f"  {sym:8s}  {status}")
