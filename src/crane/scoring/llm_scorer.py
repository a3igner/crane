"""
Optional LLM scorer — Signal 3.

Provides DeepSeek zero-shot sentiment classification for headlines.
This is an OPTIONAL signal — CRANE runs fine without it.

Configure via environment variable:
  DEEPSEEK_API_KEY=sk-your-key-here

Or leave unset — the scorer gracefully degrades and returns neutral scores,
and the ensemble calibration will assign it zero weight.
"""

import os
import json
import logging
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_MODEL = "deepseek-chat"

# System prompt for zero-shot financial sentiment
SYSTEM_PROMPT = """You are a financial sentiment analyzer. Analyze the following news headline and respond with ONLY a JSON object containing:
{
  "sentiment": "positive" | "negative" | "neutral",
  "score": <float between -1.0 and 1.0>,
  "confidence": <float between 0.0 and 1.0>,
  "reasoning": "<one-sentence explanation>"
}

Consider:
- Positive: bullish developments, earnings beats, economic strength, accommodative policy
- Negative: bearish developments, earnings misses, economic weakness, tightening policy
- Neutral: mixed signals, routine announcements, no clear directional implication

Respond with ONLY the JSON object, no other text."""


class LLMScorer:
    """Optional DeepSeek-based LLM sentiment scorer.

    Gracefully degrades if API key is not configured.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_MODEL):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.model = model
        self._available = bool(self.api_key)

        if not self._available:
            logger.warning(
                "LLMScorer: No DEEPSEEK_API_KEY configured. "
                "LLM signal will return neutral scores. "
                "Set DEEPSEEK_API_KEY in environment to enable."
            )

    @property
    def available(self) -> bool:
        return self._available

    def score(self, text: str) -> Dict:
        """Score a single headline using DeepSeek zero-shot classification.

        Returns dict with score (-1 to 1), confidence, and reasoning.
        Falls back to neutral if API is unavailable.
        """
        if not self._available:
            return {"score": 0.0, "confidence": 0.0,
                    "reasoning": "LLM scorer not configured", "source": "fallback"}

        try:
            resp = requests.post(
                DEEPSEEK_API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": text},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 150,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            # Parse JSON from response
            result = self._parse_response(content)
            result["source"] = "deepseek"
            return result

        except Exception as exc:
            logger.error("LLM scoring failed: %s", exc)
            return {"score": 0.0, "confidence": 0.0,
                    "reasoning": f"API error: {exc}", "source": "error"}

    def score_batch(self, texts: List[str]) -> List[Dict]:
        """Score multiple headlines.

        For large batches, consider rate limiting.
        """
        return [self.score(t) for t in texts]

    @staticmethod
    def _parse_response(content: str) -> Dict:
        """Extract JSON from LLM response (handles markdown fences)."""
        # Strip markdown code fences if present
        content = content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]

        try:
            result = json.loads(content)
            score = float(result.get("score", 0.0))
            confidence = float(result.get("confidence", 0.0))
            return {
                "score": max(-1.0, min(1.0, score)),
                "confidence": max(0.0, min(1.0, confidence)),
                "sentiment": result.get("sentiment", "neutral"),
                "reasoning": result.get("reasoning", ""),
            }
        except (json.JSONDecodeError, ValueError, KeyError):
            logger.warning("Failed to parse LLM response: %s", content[:100])
            return {"score": 0.0, "confidence": 0.0,
                    "reasoning": "Parse error", "sentiment": "neutral"}
