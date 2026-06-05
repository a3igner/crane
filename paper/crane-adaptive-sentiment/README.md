= CRANE Paper ================================================================

Directory: /home/a3/agentic-trading/paper/crane-adaptive-sentiment/

## Files

  main.tex                   -- ecrc/journal version (requires ecrc.sty)
  arxiv_submission/main.tex  -- arXiv-compatible version (no ecrc)
  01-introduction.tex        -- Motivation, contributions, roadmap
  02-related-work.tex        -- Literature review + research gaps
  03-system-architecture.tex -- Data source, pipeline, MySQL schema
  04-technical-approach.tex  -- 3 signals (lexicon, cluster, LLM) + ensemble + calibration
  05-novelty-and-comparison.tex -- Tradeoff tables, regime shift performance
  06-implementation.tex      -- Cron pipeline, gauge widget, code structure
  07-conclusion.tex          -- Summary, limitations, future work
  references.bib             -- 26 references from Semantic Scholar
  figures/pipeline-flowchart.pdf -- Pipeline architecture diagram
  elsarticle.cls             -- Elsevier article class
  elsarticle-num.bst         -- Numeric bibliography style

## Compilation

arXiv version (recommended for sharing):
  cd arxiv_submission/
  pdflatex main.tex && bibtex main && pdflatex main.tex && pdflatex main.tex

ecrc/journal version:
  Requires ecrc.sty (part of Elsevier's ecrc package)
  cd ../
  pdflatex main.tex && bibtex main && pdflatex main.tex && pdflatex main.tex

## Full title

CRANE: Cluster-Reactive Adaptive News Ensemble
Zero-Shot Market Regime Adaptation in Real-Time News Sentiment
via a CPU-Native Ensemble Without Neural Retraining

## arXiv categories

Primary: cs.LG (Machine Learning)
Cross-list: q-fin.ST (Statistical Finance), cs.IR (Information Retrieval)

## Key facts

- CPU-native (no GPU needed)
- 3-signal ensemble: FinBERT lexicon + TF-IDF cluster + DeepSeek LLM
- Auto-calibration every 6h via Spearman rank correlation
- Multi-asset: ES, NQ, CL, BTC, ETH (22 price snapshot fields)
- 5-asset cluster return buffers
- 24h forward price impact computation
- ~1,800 lines Python, 9 source files
- MySQL at 10.0.0.44:3306 (database: stocks)
- Hermes cron pipeline (every 3h)
- HTML gauge with dark theme tradeflags.com style
- IC rho = 0.35 (post-convergence) vs GPT-4o-mini rho = 0.40 at 1/400th cost
- 74.2% directional accuracy during regime shocks
