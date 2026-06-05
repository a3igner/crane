"""
Database utilities for CRANE.

Connects to MySQL using credentials from environment variables or .env file.
Handles schema creation and connection pooling.
"""

import os
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone

try:
    import pymysql
    HAS_MYSQL = True
except ImportError:
    pymysql = None
    HAS_MYSQL = False

try:
    import sqlite3
    HAS_SQLITE = True
except ImportError:
    sqlite3 = None
    HAS_SQLITE = False

logger = logging.getLogger(__name__)


def get_db_config() -> Dict[str, Any]:
    """Read database configuration from environment.

    CRANE supports MySQL (production) and SQLite (development/testing).
    Set CRANE_DB_TYPE=sqlite for zero-install SQLite mode.

    Returns:
        dict with db connection parameters.
    """
    db_type = os.environ.get("CRANE_DB_TYPE", "mysql").lower()

    if db_type == "sqlite":
        db_path = os.environ.get("CRANE_SQLITE_PATH", "crane_dev.db")
        return {"type": "sqlite", "path": db_path}

    # MySQL config
    return {
        "type": "mysql",
        "host": os.environ.get("CRANE_MYSQL_HOST", "127.0.0.1"),
        "port": int(os.environ.get("CRANE_MYSQL_PORT", "3306")),
        "user": os.environ.get("CRANE_MYSQL_USER", "crane"),
        "password": os.environ.get("CRANE_MYSQL_PASSWORD", ""),
        "database": os.environ.get("CRANE_MYSQL_DATABASE", "crane"),
    }


def get_connection():
    """Get a database connection based on config."""
    cfg = get_db_config()

    if cfg["type"] == "sqlite":
        if not HAS_SQLITE:
            raise ImportError("sqlite3 is required for SQLite mode")
        conn = sqlite3.connect(cfg["path"])
        conn.row_factory = sqlite3.Row
        return conn

    if not HAS_MYSQL:
        raise ImportError("pymysql is required for MySQL mode. Install: pip install pymysql")

    return pymysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def init_database(conn) -> None:
    """Create tables if they don't exist.

    Idempotent — safe to run on every startup.
    """
    cfg = get_db_config()
    is_sqlite = cfg["type"] == "sqlite"

    if is_sqlite:
        _init_sqlite(conn)
    else:
        _init_mysql(conn)

    logger.info("Database initialized successfully")


def _init_mysql(conn) -> None:
    with conn.cursor() as cur:
        # News events table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS news_events (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT,
                source VARCHAR(100),
                published_at DATETIME NOT NULL,
                ingested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                title_hash CHAR(64) NOT NULL UNIQUE,
                cluster_id INT DEFAULT NULL,
                KEY idx_published (published_at),
                KEY idx_hash (title_hash)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # Price snapshots table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS price_snapshots (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                news_event_id BIGINT NOT NULL,
                snapshot_at DATETIME NOT NULL,
                ES DECIMAL(10,2),
                NQ DECIMAL(10,2),
                CL DECIMAL(10,2),
                BTC DECIMAL(12,2),
                ETH DECIMAL(12,2),
                KEY idx_news_id (news_event_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # Sentiment signals table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sentiment_signals (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                news_event_id BIGINT NOT NULL,
                signal_source VARCHAR(20) NOT NULL,
                sentiment_score DECIMAL(5,3),
                confidence DECIMAL(5,3),
                scored_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                impact_24h_es DECIMAL(6,3),
                impact_24h_nq DECIMAL(6,3),
                impact_24h_cl DECIMAL(6,3),
                impact_24h_btc DECIMAL(6,3),
                impact_24h_eth DECIMAL(6,3),
                KEY idx_news_source (news_event_id, signal_source)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # Ensemble weights table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ensemble_weights (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                calibrated_at DATETIME NOT NULL,
                w_lexicon DECIMAL(5,3),
                w_statistical DECIMAL(5,3),
                w_llm DECIMAL(5,3),
                spearman_rho DECIMAL(5,3),
                regime_tag VARCHAR(50),
                KEY idx_calibrated (calibrated_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)


def _init_sqlite(conn) -> None:
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS news_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT,
            source TEXT,
            published_at TEXT NOT NULL,
            ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
            title_hash TEXT NOT NULL UNIQUE,
            cluster_id INTEGER DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS price_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_event_id INTEGER NOT NULL,
            snapshot_at TEXT NOT NULL,
            ES REAL, NQ REAL, CL REAL, BTC REAL, ETH REAL
        );
        CREATE TABLE IF NOT EXISTS sentiment_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_event_id INTEGER NOT NULL,
            signal_source TEXT NOT NULL,
            sentiment_score REAL,
            confidence REAL,
            scored_at TEXT NOT NULL DEFAULT (datetime('now')),
            impact_24h_es REAL, impact_24h_nq REAL,
            impact_24h_cl REAL, impact_24h_btc REAL, impact_24h_eth REAL
        );
        CREATE TABLE IF NOT EXISTS ensemble_weights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            calibrated_at TEXT NOT NULL,
            w_lexicon REAL, w_statistical REAL, w_llm REAL,
            spearman_rho REAL, regime_tag TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_news_hash ON news_events(title_hash);
        CREATE INDEX IF NOT EXISTS idx_news_pub ON news_events(published_at);
        CREATE INDEX IF NOT EXISTS idx_sig_news ON sentiment_signals(news_event_id, signal_source);
    """)
    conn.commit()
