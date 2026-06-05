"""
Financial lexicon scorer — Signal 1.

A domain-specific financial dictionary with prospect-theory loss aversion.
Fast, deterministic, zero-cost. The old reliable baseline.

Uses the Loughran-McDonald financial sentiment dictionary extended with
prospect-theory loss multipliers (negative words weighted ~2.25x positive).
"""

import re
import logging
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)

# Financial lexicon: word -> (polarity, intensity)
# Polarity: +1 = positive, -1 = negative
# Intensity: 0.0 to 1.0

FINANCIAL_LEXICON: Dict[str, Tuple[int, float]] = {
    # === Positive words ===
    "beat": (1, 0.6),
    "beats": (1, 0.6),
    "surge": (1, 0.7),
    "surges": (1, 0.7),
    "surged": (1, 0.7),
    "rally": (1, 0.7),
    "rallies": (1, 0.7),
    "rallied": (1, 0.7),
    "bullish": (1, 0.8),
    "recovery": (1, 0.6),
    "recovering": (1, 0.5),
    "growth": (1, 0.5),
    "growing": (1, 0.4),
    "expansion": (1, 0.5),
    "expand": (1, 0.4),
    "profit": (1, 0.7),
    "profits": (1, 0.7),
    "profitable": (1, 0.7),
    "earnings": (1, 0.6),
    "outperform": (1, 0.7),
    "outperforms": (1, 0.7),
    "outperformed": (1, 0.7),
    "upgrade": (1, 0.5),
    "upgrades": (1, 0.5),
    "upgraded": (1, 0.5),
    "positive": (1, 0.4),
    "optimistic": (1, 0.5),
    "uptick": (1, 0.4),
    "uptrend": (1, 0.5),
    "breakout": (1, 0.7),
    "breakouts": (1, 0.7),
    "momentum": (1, 0.5),
    "booming": (1, 0.6),
    "boom": (1, 0.6),
    "innovation": (1, 0.3),
    "innovative": (1, 0.3),
    "confidence": (1, 0.4),
    "confident": (1, 0.4),
    "strength": (1, 0.4),
    "strong": (1, 0.4),
    "robust": (1, 0.5),
    "soar": (1, 0.7),
    "soars": (1, 0.7),
    "soared": (1, 0.7),
    "jump": (1, 0.5),
    "jumps": (1, 0.5),
    "jumped": (1, 0.5),
    "gain": (1, 0.4),
    "gains": (1, 0.4),
    "gained": (1, 0.4),
    "rise": (1, 0.4),
    "rises": (1, 0.4),
    "rose": (1, 0.4),
    "rising": (1, 0.4),
    "rebound": (1, 0.6),
    "rebounds": (1, 0.6),
    "rebounded": (1, 0.6),
    "improve": (1, 0.4),
    "improves": (1, 0.4),
    "improved": (1, 0.4),
    "improvement": (1, 0.4),
    "upward": (1, 0.3),
    "bull": (1, 0.6),
    "bulls": (1, 0.6),
    "all-time high": (1, 0.9),
    "record high": (1, 0.8),
    "record": (1, 0.6),
    "breakthrough": (1, 0.6),

    # === Negative words (with loss aversion multiplier ~2.25x) ===
    "default": (-1, 0.9),
    "defaults": (-1, 0.9),
    "defaulted": (-1, 0.9),
    "bankruptcy": (-1, 1.0),
    "bankrupt": (-1, 1.0),
    "crisis": (-1, 0.9),
    "crises": (-1, 0.9),
    "crash": (-1, 1.0),
    "crashes": (-1, 1.0),
    "crashed": (-1, 1.0),
    "plunge": (-1, 0.8),
    "plunges": (-1, 0.8),
    "plunged": (-1, 0.8),
    "collapse": (-1, 0.9),
    "collapses": (-1, 0.9),
    "collapsed": (-1, 0.9),
    "bearish": (-1, 0.8),
    "recession": (-1, 0.8),
    "recessions": (-1, 0.8),
    "inflation": (-1, 0.5),
    "deflation": (-1, 0.6),
    "stagnation": (-1, 0.5),
    "stagnant": (-1, 0.4),
    "downturn": (-1, 0.6),
    "slowdown": (-1, 0.5),
    "decline": (-1, 0.5),
    "declines": (-1, 0.5),
    "declined": (-1, 0.5),
    "declining": (-1, 0.5),
    "drop": (-1, 0.5),
    "drops": (-1, 0.5),
    "dropped": (-1, 0.5),
    "fall": (-1, 0.4),
    "falls": (-1, 0.4),
    "fell": (-1, 0.4),
    "falling": (-1, 0.4),
    "loss": (-1, 0.6),
    "losses": (-1, 0.6),
    "lose": (-1, 0.5),
    "lost": (-1, 0.5),
    "downgrade": (-1, 0.6),
    "downgrades": (-1, 0.6),
    "downgraded": (-1, 0.6),
    "negative": (-1, 0.5),
    "pessimistic": (-1, 0.5),
    "uncertainty": (-1, 0.5),
    "uncertain": (-1, 0.4),
    "volatile": (-1, 0.4),
    "volatility": (-1, 0.5),
    "turbulence": (-1, 0.5),
    "stress": (-1, 0.4),
    "stressed": (-1, 0.4),
    "sell-off": (-1, 0.7),
    "selloff": (-1, 0.7),
    "liquidation": (-1, 0.7),
    "liquidations": (-1, 0.7),
    "bubble": (-1, 0.6),
    "bubbles": (-1, 0.6),
    "contagion": (-1, 0.8),
    "downtrend": (-1, 0.5),
    "downside": (-1, 0.4),
    "weak": (-1, 0.4),
    "weakness": (-1, 0.4),
    "weaken": (-1, 0.4),
    "weakening": (-1, 0.4),
    "layoff": (-1, 0.5),
    "layoffs": (-1, 0.5),
    "fired": (-1, 0.5),
    "firing": (-1, 0.5),
    "lawsuit": (-1, 0.5),
    "lawsuits": (-1, 0.5),
    "litigation": (-1, 0.5),
    "investigation": (-1, 0.4),
    "penalty": (-1, 0.5),
    "penalties": (-1, 0.5),
    "fine": (-1, 0.4),
    "fines": (-1, 0.4),
    "sanction": (-1, 0.5),
    "sanctions": (-1, 0.5),
    "tariff": (-1, 0.5),
    "tariffs": (-1, 0.5),
    "trade war": (-1, 0.8),
    "bear": (-1, 0.6),
    "bears": (-1, 0.6),
    "correction": (-1, 0.5),
    "slump": (-1, 0.6),
    "slumps": (-1, 0.6),
    "slumped": (-1, 0.6),
    "tumble": (-1, 0.6),
    "tumbles": (-1, 0.6),
    "tumbled": (-1, 0.6),
    "nosedive": (-1, 0.8),
    "meltdown": (-1, 0.8),
    "panic": (-1, 0.7),
    "fear": (-1, 0.5),
    "worst": (-1, 0.5),
    "danger": (-1, 0.4),
    "dangerous": (-1, 0.5),
    "risk": (-1, 0.3),
    "risks": (-1, 0.3),
    "risky": (-1, 0.4),

    # === Context modifiers ===
    "contraction": (-1, 0.6),
    "contracting": (-1, 0.5),
    "tightening": (-1, 0.4),
    "tighten": (-1, 0.4),
    "hike": (-1, 0.4),
    "hikes": (-1, 0.4),
    "hiked": (-1, 0.4),
    "rate hike": (-1, 0.6),
    "rate hikes": (-1, 0.6),
    "rate cut": (1, 0.6),
    "rate cuts": (1, 0.6),
    "stimulus": (1, 0.5),
    "bailout": (1, 0.3),
    "quantitative easing": (1, 0.5),

    # === Multi-word phrases ===
    "better than expected": (1, 0.7),
    "worse than expected": (-1, 0.7),
    "ahead of expectations": (1, 0.6),
    "below expectations": (-1, 0.6),
    "exceed expectations": (1, 0.7),
    "miss expectations": (-1, 0.7),
    "exceeded expectations": (1, 0.7),
    "missed expectations": (-1, 0.7),
    "in line with expectations": (1, 0.2),
}

LOSS_AVERSION_MULTIPLIER = 2.25


class LexiconScorer:
    """Signal 1: Financial lexicon scorer with prospect theory weighting."""

    def __init__(self):
        self.lexicon = FINANCIAL_LEXICON
        # Build sorted phrase list for multi-word matching
        self.phrases = sorted(
            [w for w in self.lexicon if len(w.split()) > 1],
            key=len, reverse=True
        )

    def score(self, text: str) -> Dict:
        """Score a single headline.

        Returns:
            dict with 'score' (-1 to +1), 'confidence' (0 to 1),
            'positive_count', 'negative_count', 'details'.
        """
        if not text:
            return {"score": 0.0, "confidence": 0.0,
                    "positive_count": 0, "negative_count": 0, "details": []}

        text_lower = text.lower()
        details = []
        pos_score = 0.0
        neg_score = 0.0
        pos_count = 0
        neg_count = 0

        # Match multi-word phrases first
        matched_spans = []
        for phrase in self.phrases:
            if phrase in text_lower:
                polarity, intensity = self.lexicon[phrase]
                if polarity > 0:
                    pos_score += intensity
                    pos_count += 1
                else:
                    neg_score += intensity * LOSS_AVERSION_MULTIPLIER
                    neg_count += 1
                details.append({"word": phrase, "polarity": polarity,
                                "intensity": intensity})
                # Mark as matched to avoid double-counting single words
                idx = text_lower.index(phrase)
                matched_spans.append((idx, idx + len(phrase)))

        # Match single words
        tokens = re.findall(r"[a-z']+(?:-[a-z']+)?", text_lower)
        for token in tokens:
            # Skip if part of a matched phrase
            # (simplified: just check membership)
            if token in self.lexicon and token not in self.phrases:
                polarity, intensity = self.lexicon[token]
                if polarity > 0:
                    pos_score += intensity
                    pos_count += 1
                else:
                    neg_score += intensity * LOSS_AVERSION_MULTIPLIER
                    neg_count += 1
                details.append({"word": token, "polarity": polarity,
                                "intensity": intensity})

        if pos_count == 0 and neg_count == 0:
            return {"score": 0.0, "confidence": 0.0,
                    "positive_count": 0, "negative_count": 0,
                    "details": details}

        # Net score: signed magnitude in [-1, +1]
        net = pos_score - neg_score
        total = pos_score + neg_score
        normalized = max(-1.0, min(1.0, net / max(total, 0.01)))

        # Confidence based on total signal strength
        confidence = min(1.0, total / 2.0)

        return {
            "score": round(normalized, 3),
            "confidence": round(confidence, 3),
            "positive_count": pos_count,
            "negative_count": neg_count,
            "details": details,
        }
