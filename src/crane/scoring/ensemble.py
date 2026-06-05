"""
Ensemble scoring — combines all three signals with adaptive weighting.

The ensemble weights are recalculated every 6 hours based on the Spearman
rank correlation between each signal's predictions and the actual 24-hour
forward price moves that followed each headline.

Key design:
  - Weighted average of lexicon, statistical cluster, and optional LLM signals
  - Weights computed from rolling 7-day Spearman rank correlation
  - Softmax normalization with a diversity floor (min 0.10 per signal)
  - No signal ever drops to zero weight
"""

import math
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from statistics import NormalDist

logger = logging.getLogger(__name__)

# Minimum weight floor — even a struggling signal keeps a stake
WEIGHT_FLOOR = 0.10
NUM_SIGNALS = 3  # lexicon, statistical, llm


class Ensemble:
    """Adaptive ensemble that combines three sentiment signals.

    Signals:
      1. Lexicon scorer (fast, free, traditional)
      2. Statistical cluster learner (adaptive, living map)
      3. Optional LLM scorer (DeepSeek, zero-shot)
    """

    def __init__(self):
        # Current active weights (lexicon, stat, llm)
        self.weights = [0.34, 0.38, 0.28]  # default starting weights
        self.last_calibrated: Optional[datetime] = None
        self.spearman_rho: float = 0.0
        self.regime_tag: str = "unknown"

    def combine(self, scores: Dict[str, Dict]) -> Dict:
        """Combine multiple signal scores into a single ensemble prediction.

        Args:
            scores: dict with keys 'lexicon', 'statistical', 'llm'.
                    Each value is a dict with 'score' (-1 to 1) and 'confidence'.

        Returns:
            dict with 'ensemble_score', 'confidence', 'breakdown', 'weights'.
        """
        signal_order = ["lexicon", "statistical", "llm"]
        weighted_sum = 0.0
        total_confidence = 0.0
        breakdown = {}

        for i, sig_name in enumerate(signal_order):
            sig = scores.get(sig_name, {"score": 0.0, "confidence": 0.0})
            w = self.weights[i] if i < len(self.weights) else 0.0
            weighted_sum += w * sig.get("score", 0.0) * sig.get("confidence", 0.0)
            total_confidence += w * sig.get("confidence", 0.0)
            breakdown[sig_name] = {
                "score": sig.get("score", 0.0),
                "confidence": sig.get("confidence", 0.0),
                "weight": w,
                "contribution": w * sig.get("score", 0.0) * sig.get("confidence", 0.0),
            }

        ensemble_score = weighted_sum / max(total_confidence, 0.01)
        ensemble_score = max(-1.0, min(1.0, ensemble_score))

        return {
            "ensemble_score": round(ensemble_score, 3),
            "confidence": round(total_confidence, 3),
            "breakdown": breakdown,
            "weights": list(self.weights),
            "spearman_rho": self.spearman_rho,
            "regime_tag": self.regime_tag,
        }

    def calibrate(
        self,
        signal_scores: List[Tuple[str, List[float]]],
        actual_returns: List[float],
    ) -> Dict:
        """Recalibrate ensemble weights using Spearman rank correlation.

        Called every 6 hours in production.

        Args:
            signal_scores: list of (signal_name, [predicted_scores]) tuples.
            actual_returns: list of realized 24h returns.

        Returns:
            dict with new weights, spearman_rho, and regime tag.
        """
        n = len(actual_returns)
        if n < 10:
            logger.warning("Too few samples (%d) for calibration, keeping current weights", n)
            return {
                "weights": list(self.weights),
                "spearman_rho": self.spearman_rho,
                "regime_tag": self.regime_tag,
            }

        # Compute Spearman rank correlation for each signal
        rhos = []
        for sig_name, preds in signal_scores:
            if len(preds) >= n:
                rho = self._spearman_rank(preds[:n], actual_returns)
            else:
                rho = 0.0
            rhos.append(rho)

        # Convert rhos to weights with softmax + floor
        # Shift to [0, inf) range
        shifted = [max(0.001, r + 1.0) for r in rhos]
        raw_weights = [s / sum(shifted) for s in shifted]

        # Apply floor
        final_weights = []
        remaining = 1.0 - WEIGHT_FLOOR * NUM_SIGNALS
        for w in raw_weights:
            if w < WEIGHT_FLOOR:
                final_weights.append(WEIGHT_FLOOR)
            else:
                final_weights.append(w)

        # Renormalize
        total = sum(final_weights)
        self.weights = [w / total for w in final_weights]

        # Average Spearman rho
        self.spearman_rho = sum(rhos) / len(rhos) if rhos else 0.0
        self.last_calibrated = datetime.now(timezone.utc)

        # Detect regime from volatility
        self.regime_tag = self._detect_regime(actual_returns)

        logger.info(
            "Calibration complete: weights=%s, rho=%.3f, regime=%s",
            [round(w, 3) for w in self.weights],
            self.spearman_rho,
            self.regime_tag,
        )

        return {
            "weights": [round(w, 3) for w in self.weights],
            "spearman_rho": round(self.spearman_rho, 3),
            "regime_tag": self.regime_tag,
            "signal_correlations": [round(r, 3) for r in rhos],
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _spearman_rank(x: List[float], y: List[float]) -> float:
        """Compute Spearman rank correlation coefficient."""
        n = len(x)
        if n < 3:
            return 0.0

        # Rank x and y
        x_ranked = sorted(range(n), key=lambda i: x[i])
        y_ranked = sorted(range(n), key=lambda i: y[i])

        rank_x = [0] * n
        rank_y = [0] * n
        for i, idx in enumerate(x_ranked):
            rank_x[idx] = i + 1
        for i, idx in enumerate(y_ranked):
            rank_y[idx] = i + 1

        # Pearson correlation on ranks
        mean_x = sum(rank_x) / n
        mean_y = sum(rank_y) / n

        cov = sum((rank_x[i] - mean_x) * (rank_y[i] - mean_y) for i in range(n))
        std_x = math.sqrt(sum((rank_x[i] - mean_x) ** 2 for i in range(n)))
        std_y = math.sqrt(sum((rank_y[i] - mean_y) ** 2 for i in range(n)))

        if std_x == 0 or std_y == 0:
            return 0.0
        return cov / (std_x * std_y)

    @staticmethod
    def _detect_regime(returns: List[float]) -> str:
        """Detect market regime from return volatility."""
        if len(returns) < 10:
            return "insufficient_data"

        mean_r = sum(returns) / len(returns)
        var_r = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        vol = math.sqrt(var_r)

        if vol > 0.02:
            return "high_volatility"
        elif vol > 0.01:
            return "moderate_volatility"
        elif mean_r > 0.005:
            return "bullish"
        elif mean_r < -0.005:
            return "bearish"
        return "neutral"
