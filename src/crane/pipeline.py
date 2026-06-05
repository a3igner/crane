#!/usr/bin/env python3
"""
CRANE Pipeline — main entry point.

Orchestrates the full CRANE pipeline:
  1. INGEST — fetch new headlines + price snapshots
  2. SCORE — run all three signals on unscored headlines
  3. CALIBRATE — recompute ensemble weights (every 6 hours)

Usage:
    python -m crane.pipeline [--ingest] [--score] [--calibrate] [--all]

Examples:
    # Full pipeline run
    python -m crane.pipeline --all

    # Just ingest new data
    python -m crane.pipeline --ingest

    # Score unscored headlines
    python -m crane.pipeline --score

    # Recalibrate ensemble weights
    python -m crane.pipeline --calibrate

    # Daemon mode: run continuously
    python -m crane.pipeline --daemon
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

# Ensure the package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crane.utils.db import get_connection, init_database, get_db_config
from crane.datafeeds.rss_feed import RSSFeed
from crane.datafeeds.yahoo_feed import YahooFeed
from crane.scoring import LexiconScorer, ClusterLearner, LLMScorer, Ensemble

logger = logging.getLogger("crane.pipeline")


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def step_ingest(conn) -> int:
    """Fetch new headlines and price snapshots, store in database.

    Returns:
        Number of new headlines ingested.
    """
    logger.info("=== INGEST ===")
    news_feed = RSSFeed()
    price_feed = YahooFeed()

    # Fetch headlines
    headlines = news_feed.fetch()
    logger.info("Fetched %d headlines from RSS feeds", len(headlines))

    if not headlines:
        return 0

    # Fetch price snapshots
    prices = price_feed.fetch_snapshots()
    logger.info("Price snapshots: %s", prices)

    # Store in database
    cfg = get_db_config()
    is_sqlite = cfg["type"] == "sqlite"
    placeholders = "?" if is_sqlite else "%s"
    new_count = 0

    with conn.cursor() as cur:
        for h in headlines:
            import hashlib
            title_hash = hashlib.sha256(h["title"].encode("utf-8")).hexdigest()

            # Insert news event (skip duplicates)
            try:
                if is_sqlite:
                    cur.execute(
                        """INSERT OR IGNORE INTO news_events
                           (title, url, source, published_at, title_hash)
                           VALUES (?, ?, ?, ?, ?)""",
                        (h["title"], h["url"], h["source"],
                         h["published_at"], title_hash)
                    )
                else:
                    cur.execute(
                        """INSERT IGNORE INTO news_events
                           (title, url, source, published_at, title_hash)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (h["title"], h["url"], h["source"],
                         h["published_at"], title_hash)
                    )
                if cur.rowcount > 0:
                    new_count += 1
                    news_id = cur.lastrowid

                    # Insert price snapshot
                    if is_sqlite:
                        cur.execute(
                            """INSERT INTO price_snapshots
                               (news_event_id, snapshot_at, ES, NQ, CL, BTC, ETH)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (news_id, datetime.now(timezone.utc).isoformat(),
                             prices.get("ES"), prices.get("NQ"),
                             prices.get("CL"), prices.get("BTC"),
                             prices.get("ETH"))
                        )
                    else:
                        cur.execute(
                            """INSERT INTO price_snapshots
                               (news_event_id, snapshot_at, ES, NQ, CL, BTC, ETH)
                               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                            (news_id, datetime.now(timezone.utc),
                             prices.get("ES"), prices.get("NQ"),
                             prices.get("CL"), prices.get("BTC"),
                             prices.get("ETH"))
                        )
            except Exception as exc:
                logger.warning("Failed to insert headline: %s", exc)

    logger.info("Ingested %d new headlines", new_count)
    return new_count


def step_score(conn) -> int:
    """Score all unscored headlines.

    Runs all available signals (lexicon, cluster, optional LLM).
    Stores results in sentiment_signals table.

    Returns:
        Number of headlines scored.
    """
    logger.info("=== SCORE ===")
    cfg = get_db_config()
    is_sqlite = cfg["type"] == "sqlite"
    ph = "?" if is_sqlite else "%s"

    # Find unscored headlines
    with conn.cursor() as cur:
        if is_sqlite:
            cur.execute("""
                SELECT ne.id, ne.title, ps.ES, ps.NQ, ps.CL, ps.BTC, ps.ETH
                FROM news_events ne
                LEFT JOIN price_snapshots ps ON ne.id = ps.news_event_id
                WHERE ne.id NOT IN (
                    SELECT DISTINCT news_event_id FROM sentiment_signals
                )
                ORDER BY ne.id
                LIMIT 200
            """)
        else:
            cur.execute("""
                SELECT ne.id, ne.title, ps.ES, ps.NQ, ps.CL, ps.BTC, ps.ETH
                FROM news_events ne
                LEFT JOIN price_snapshots ps ON ne.id = ps.news_event_id
                WHERE ne.id NOT IN (
                    SELECT DISTINCT news_event_id FROM sentiment_signals
                )
                ORDER BY ne.id
                LIMIT 200
            """)

        rows = cur.fetchall()

    if not rows:
        logger.info("No unscored headlines found")
        return 0

    # Initialize scorers
    lexicon = LexiconScorer()
    cluster = ClusterLearner()
    llm = LLMScorer()
    scored_count = 0

    for row in rows:
        headline_id = row["id"]
        title = row["title"]
        returns = {
            "ES": row.get("ES"),
            "NQ": row.get("NQ"),
            "CL": row.get("CL"),
            "BTC": row.get("BTC"),
            "ETH": row.get("ETH"),
        }

        # Signal 1: Lexicon
        lex_result = lexicon.score(title)
        _store_signal(conn, headline_id, "lexicon",
                      lex_result["score"], lex_result["confidence"])

        # Signal 2: Statistical cluster
        # Cluster and get signal
        cid = cluster.add_headline(headline_id, title, returns)
        if cid >= 0:
            sig = cluster.get_cluster_signal(headline_id)
            if sig:
                # Average return across assets as signal score
                asset_scores = [sig.get(a) for a in ("ES", "NQ", "CL", "BTC", "ETH")]
                valid = [s for s in asset_scores if s is not None]
                cluster_score = sum(valid) / len(valid) if valid else 0.0
                cluster_conf = sum(
                    sig.get(f"confidence_{a.lower()}", 0) for a in ("ES", "NQ", "CL", "BTC", "ETH")
                ) / 5.0
                _store_signal(conn, headline_id, "statistical",
                              round(cluster_score, 3), round(cluster_conf, 3))

        # Signal 3: Optional LLM
        if llm.available:
            llm_result = llm.score(title)
            _store_signal(conn, headline_id, "llm",
                          llm_result["score"], llm_result["confidence"])

        scored_count += 1

    logger.info("Scored %d headlines", scored_count)
    return scored_count


def step_calibrate(conn) -> Dict:
    """Recalibrate ensemble weights using recent performance data.

    Should be called every 6 hours in production.

    Returns:
        Calibration result dict with new weights.
    """
    logger.info("=== CALIBRATE ===")
    ensemble = Ensemble()
    cfg = get_db_config()
    is_sqlite = cfg["type"] == "sqlite"

    with conn.cursor() as cur:
        # Fetch recent scored headlines with their actual impacts
        # (impacts would be filled by a separate impact_calculation step)
        if is_sqlite:
            cur.execute("""
                SELECT ss.signal_source, ss.sentiment_score,
                       COALESCE(ss.impact_24h_es, 0) as impact
                FROM sentiment_signals ss
                JOIN news_events ne ON ss.news_event_id = ne.id
                WHERE ne.published_at > datetime('now', '-7 days')
                ORDER BY ss.news_event_id
            """)
        else:
            cur.execute("""
                SELECT ss.signal_source, ss.sentiment_score,
                       COALESCE(ss.impact_24h_es, 0) as impact
                FROM sentiment_signals ss
                JOIN news_events ne ON ss.news_event_id = ne.id
                WHERE ne.published_at > NOW() - INTERVAL 7 DAY
                ORDER BY ss.news_event_id
            """)
        rows = cur.fetchall()

    if len(rows) < 10:
        logger.warning("Not enough data for calibration (%d rows)", len(rows))
        return {"weights": ensemble.weights, "spearman_rho": 0.0, "regime_tag": "insufficient_data"}

    # Group by signal source
    signal_data: Dict[str, List[float]] = {}
    actual_returns: List[float] = []

    # Use a dict to group by event_id across signals
    from collections import defaultdict
    events: Dict[int, Dict[str, float]] = defaultdict(dict)
    for row in rows:
        event_id = None
        # We need the event_id — fetch it with a more specific query next time
        # For now, use sequential grouping
        pass

    # Simplified calibration: just log weights
    logger.info("Current weights: %s", ensemble.weights)
    return {"weights": ensemble.weights, "spearman_rho": ensemble.spearman_rho}


def _store_signal(conn, news_id: int, source: str, score: float, confidence: float):
    """Store a signal result in the database."""
    cfg = get_db_config()
    is_sqlite = cfg["type"] == "sqlite"
    try:
        with conn.cursor() as cur:
            if is_sqlite:
                cur.execute(
                    """INSERT INTO sentiment_signals
                       (news_event_id, signal_source, sentiment_score, confidence)
                       VALUES (?, ?, ?, ?)""",
                    (news_id, source, score, confidence)
                )
            else:
                cur.execute(
                    """INSERT INTO sentiment_signals
                       (news_event_id, signal_source, sentiment_score, confidence)
                       VALUES (%s, %s, %s, %s)""",
                    (news_id, source, score, confidence)
                )
    except Exception as exc:
        logger.warning("Failed to store signal %s for news %d: %s",
                       source, news_id, exc)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="CRANE — Cluster-Reactive Adaptive News Ensemble Pipeline"
    )
    parser.add_argument("--ingest", action="store_true", help="Fetch new headlines")
    parser.add_argument("--score", action="store_true", help="Score unscored headlines")
    parser.add_argument("--calibrate", action="store_true", help="Recalibrate weights")
    parser.add_argument("--all", action="store_true", help="Run full pipeline")
    parser.add_argument("--daemon", action="store_true",
                       help="Run continuously (ingest every 15min, calibrate every 6h)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    return parser.parse_args()


def main():
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("CRANE Pipeline v1.0.0 starting")

    if args.daemon:
        _run_daemon()
        return

    conn = get_connection()
    init_database(conn)

    if args.ingest or args.all:
        step_ingest(conn)

    if args.score or args.all:
        step_score(conn)

    if args.calibrate or args.all:
        step_calibrate(conn)

    conn.close()
    logger.info("Pipeline complete")


def _run_daemon():
    """Run the pipeline continuously.

    - Ingest + Score every 15 minutes
    - Calibrate every 6 hours
    """
    logger.info("Starting daemon mode")
    conn = get_connection()
    init_database(conn)

    last_calibrate = 0
    cycle = 0

    try:
        while True:
            cycle += 1
            logger.info("--- Cycle %d ---", cycle)

            step_ingest(conn)
            step_score(conn)

            # Calibrate every ~6 hours (24 cycles at 15min intervals)
            if cycle - last_calibrate >= 24:
                step_calibrate(conn)
                last_calibrate = cycle

            logger.info("Sleeping for 15 minutes...")
            time.sleep(15 * 60)

    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
