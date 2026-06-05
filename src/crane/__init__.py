"""
CRANE — Cluster-Reactive Adaptive News Ensemble
Zero-Shot Market Regime Adaptation in Real-Time News Sentiment

Copyright (c) 2026 Andreas A. Aigner
License: MIT (see LICENSE file)

A CPU-native, self-adapting news sentiment engine that:
  • Polls any configured news API or RSS feed
  • Scrapes Yahoo Finance for live price snapshots (ES, NQ, CL, BTC, ETH)
  • Runs three parallel sentiment signals (lexicon, cluster learner, optional LLM)
  • Calibrates ensemble weights every 6 hours against realized price moves
  • Operates at zero marginal cost on a single CPU core
"""

__version__ = "1.0.0"
__author__ = "Andreas A. Aigner"
__url__ = "https://github.com/a3igner/crane"
