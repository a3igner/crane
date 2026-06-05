-- CRANE Database Schema
-- MySQL version: run this to set up the database from scratch.
-- SQLite version is auto-created by the pipeline on first run.

CREATE DATABASE IF NOT EXISTS crane
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE crane;

-- News events: ingested headlines with timestamps and dedup hash
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Price snapshots: concurrent multi-asset prices for each headline
CREATE TABLE IF NOT EXISTS price_snapshots (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    news_event_id BIGINT NOT NULL,
    snapshot_at DATETIME NOT NULL,
    ES DECIMAL(10,2),        -- S&P 500 E-mini Futures
    NQ DECIMAL(10,2),        -- Nasdaq 100 E-mini Futures
    CL DECIMAL(10,2),        -- Crude Oil Futures
    BTC DECIMAL(12,2),       -- Bitcoin USD
    ETH DECIMAL(12,2),       -- Ethereum USD
    KEY idx_news_id (news_event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Sentiment signals: per-signal scores for each headline
CREATE TABLE IF NOT EXISTS sentiment_signals (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    news_event_id BIGINT NOT NULL,
    signal_source VARCHAR(20) NOT NULL COMMENT 'lexicon|statistical|llm',
    sentiment_score DECIMAL(5,3),
    confidence DECIMAL(5,3),
    scored_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    impact_24h_es DECIMAL(6,3),   -- Realized 24h impact (filled by calibration)
    impact_24h_nq DECIMAL(6,3),
    impact_24h_cl DECIMAL(6,3),
    impact_24h_btc DECIMAL(6,3),
    impact_24h_eth DECIMAL(6,3),
    KEY idx_news_source (news_event_id, signal_source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Ensemble weights: calibration history
CREATE TABLE IF NOT EXISTS ensemble_weights (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    calibrated_at DATETIME NOT NULL,
    w_lexicon DECIMAL(5,3),
    w_statistical DECIMAL(5,3),
    w_llm DECIMAL(5,3),
    spearman_rho DECIMAL(5,3),
    regime_tag VARCHAR(50),
    KEY idx_calibrated (calibrated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Grant permissions
-- GRANT ALL PRIVILEGES ON crane.* TO 'crane'@'localhost';
-- FLUSH PRIVILEGES;
