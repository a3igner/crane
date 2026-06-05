"""
Statistical cluster learner — Signal 2.

The core innovation of CRANE. Uses TF-IDF + cosine similarity to cluster
headlines into semantic neighborhoods, then tracks the average realized
price reaction for each cluster across all five tracked assets.

The cluster centroids drift over time as new headlines arrive. Every
6 hours the system recalibrates which signals to trust.

Key design:
  - Online TF-IDF with incremental vocabulary updates
  - Cosine similarity clustering with adaptive threshold
  - Rolling return buffers (last 50 events per cluster)
  - Exponential moving average for cluster centroid updates
  - Volatility-based regime detection
"""

import re
import math
import logging
from collections import defaultdict, Counter
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Cluster:
    """A semantic neighborhood of headlines with tracked price reactions."""
    id: int
    centroid: Dict[str, float]  # TF-IDF vector
    headline_count: int = 0
    # Rolling return buffers per asset (last 50)
    returns_es: List[float] = field(default_factory=list)
    returns_nq: List[float] = field(default_factory=list)
    returns_cl: List[float] = field(default_factory=list)
    returns_btc: List[float] = field(default_factory=list)
    returns_eth: List[float] = field(default_factory=list)
    # EMA of centroid
    ema_alpha: float = 0.15
    last_updated: float = 0.0

    def mean_return(self, asset: str) -> Optional[float]:
        """Average realized return for this cluster."""
        buf = getattr(self, f"returns_{asset.lower()}", None)
        if not buf:
            return None
        return sum(buf) / len(buf)

    def confidence(self, asset: str) -> float:
        """Confidence based on number of observations."""
        buf = getattr(self, f"returns_{asset.lower()}", None)
        if not buf:
            return 0.0
        return min(1.0, len(buf) / 50.0)

    def add_return(self, asset: str, ret: float):
        """Add a realized return, maintaining buffer at max 50."""
        buf = getattr(self, f"returns_{asset.lower()}")
        buf.append(ret)
        if len(buf) > 50:
            buf.pop(0)

    def update_centroid(self, new_vector: Dict[str, float]):
        """Update centroid with EMA."""
        if not self.centroid:
            self.centroid = dict(new_vector)
            return
        all_keys = set(self.centroid) | set(new_vector)
        for key in all_keys:
            old_val = self.centroid.get(key, 0.0)
            new_val = new_vector.get(key, 0.0)
            self.centroid[key] = (1 - self.ema_alpha) * old_val + self.ema_alpha * new_val


class TFIDFVectorizer:
    """Incremental TF-IDF vectorizer for headline text."""

    def __init__(self, max_features: int = 1000):
        self.max_features = max_features
        self.vocab: Dict[str, int] = {}
        self.doc_freq: Counter = Counter()
        self.num_docs: int = 0
        self._stopwords = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
            "for", "of", "by", "with", "from", "as", "is", "was", "are",
            "were", "be", "been", "has", "have", "had", "do", "does", "did",
            "will", "would", "could", "should", "may", "might", "shall",
            "can", "not", "no", "nor", "so", "if", "than", "that", "this",
            "these", "those", "it", "its", "they", "them", "their", "we",
            "our", "you", "your", "he", "she", "his", "her", "who", "which",
            "what", "when", "where", "how", "all", "each", "every", "both",
            "few", "more", "most", "some", "any", "such", "only", "own",
            "same", "into", "over", "between", "through", "during", "before",
            "after", "above", "below", "up", "down", "out", "off", "under",
            "again", "further", "once", "here", "there", "about", "against",
        }

    def tokenize(self, text: str) -> List[str]:
        """Tokenize and normalize text."""
        text = text.lower()
        tokens = re.findall(r"[a-z]+(?:'[a-z]+)?", text)
        return [t for t in tokens if t not in self._stopwords and len(t) > 2]

    def fit_transform(self, texts: List[str]) -> List[Dict[str, float]]:
        """Incremental fit and transform."""
        # Update vocabulary
        for text in texts:
            tokens = self.tokenize(text)
            seen: Set[str] = set()
            for t in tokens:
                if t not in self.vocab and len(self.vocab) < self.max_features:
                    self.vocab[t] = len(self.vocab)
                if t in self.vocab and t not in seen:
                    self.doc_freq[t] += 1
                    seen.add(t)
            self.num_docs += 1

        # Transform
        vectors = []
        for text in texts:
            tokens = self.tokenize(text)
            tf = Counter(tokens)
            vector = {}
            for word, count in tf.items():
                if word in self.vocab:
                    idf = math.log((self.num_docs + 1) / (self.doc_freq[word] + 1)) + 1
                    vector[word] = count * idf
            # Normalize
            norm = math.sqrt(sum(v * v for v in vector.values()))
            if norm > 0:
                vector = {k: v / norm for k, v in vector.items()}
            vectors.append(vector)
        return vectors


class ClusterLearner:
    """Online cluster learner for news headlines.

    Clusters headlines by semantic similarity using TF-IDF + cosine similarity.
    Maintains rolling return buffers per cluster for each tracked asset.
    """

    def __init__(
        self,
        similarity_threshold: float = 0.25,
        min_cluster_size: int = 3,
        max_clusters: int = 20,
    ):
        self.vectorizer = TFIDFVectorizer()
        self.clusters: Dict[int, Cluster] = {}
        self.similarity_threshold = similarity_threshold
        self.min_cluster_size = min_cluster_size
        self.max_clusters = max_clusters
        self.next_cluster_id = 0
        self.headline_clusters: Dict[int, int] = {}  # headline_id -> cluster_id

    def cosine_similarity(self, v1: Dict[str, float], v2: Dict[str, float]) -> float:
        """Cosine similarity between two sparse vectors."""
        common = set(v1) & set(v2)
        if not common:
            return 0.0
        dot = sum(v1[k] * v2[k] for k in common)
        norm1 = math.sqrt(sum(v * v for v in v1.values()))
        norm2 = math.sqrt(sum(v * v for v in v2.values()))
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)

    def find_best_cluster(self, vector: Dict[str, float]) -> Optional[int]:
        """Find the closest cluster, if any."""
        best_id = None
        best_sim = self.similarity_threshold
        for cid, cluster in self.clusters.items():
            sim = self.cosine_similarity(vector, cluster.centroid)
            if sim > best_sim:
                best_sim = sim
                best_id = cid
        return best_id

    def add_headline(
        self,
        headline_id: int,
        text: str,
        returns: Dict[str, float],
    ) -> int:
        """Add a headline to the cluster map.

        Args:
            headline_id: Unique ID for this headline.
            text: Headline text.
            returns: dict of asset -> realized 24h return.

        Returns:
            cluster_id the headline was assigned to.
        """
        vectors = self.vectorizer.fit_transform([text])
        vector = vectors[0]

        cid = self.find_best_cluster(vector)

        if cid is None and len(self.clusters) < self.max_clusters:
            # Create new cluster
            cid = self.next_cluster_id
            self.next_cluster_id += 1
            self.clusters[cid] = Cluster(id=cid, centroid=vector)

        if cid is not None:
            cluster = self.clusters[cid]
            cluster.headline_count += 1
            cluster.update_centroid(vector)
            for asset, ret in returns.items():
                if ret is not None:
                    cluster.add_return(asset, ret)
            cluster.last_updated = __import__("time").time()
            self.headline_clusters[headline_id] = cid

        return cid if cid is not None else -1

    def get_cluster_signal(self, headline_id: int) -> Optional[Dict]:
        """Get the signal for a previously clustered headline."""
        cid = self.headline_clusters.get(headline_id)
        if cid is None or cid not in self.clusters:
            return None

        cluster = self.clusters[cid]
        return {
            "cluster_id": cid,
            "headline_count": cluster.headline_count,
            "ES": cluster.mean_return("ES"),
            "NQ": cluster.mean_return("NQ"),
            "CL": cluster.mean_return("CL"),
            "BTC": cluster.mean_return("BTC"),
            "ETH": cluster.mean_return("ETH"),
            "confidence_es": cluster.confidence("ES"),
            "confidence_nq": cluster.confidence("NQ"),
            "confidence_cl": cluster.confidence("CL"),
            "confidence_btc": cluster.confidence("BTC"),
            "confidence_eth": cluster.confidence("ETH"),
        }

    def prune_noisy_clusters(self, sharspe_threshold: float = 0.3):
        """Remove clusters with consistently low signal quality.

        A cluster's 'Sharpe ratio' here is mean_return / std_return.
        Clusters below threshold get pruned.
        """
        to_remove = []
        for cid, cluster in self.clusters.items():
            if cluster.headline_count < self.min_cluster_size:
                to_remove.append(cid)
                continue
            # Check ES returns as a proxy for signal quality
            rets = cluster.returns_es
            if len(rets) < 3:
                continue
            mean_r = sum(rets) / len(rets)
            if mean_r == 0:
                to_remove.append(cid)
                continue
            var_r = sum((r - mean_r) ** 2 for r in rets) / len(rets)
            std_r = math.sqrt(var_r)
            sharpe = mean_r / std_r if std_r > 0 else 0
            if sharpe < sharspe_threshold:
                to_remove.append(cid)

        for cid in to_remove:
            del self.clusters[cid]
            # Remove references
            to_del = [hid for hid, c in self.headline_clusters.items() if c == cid]
            for hid in to_del:
                del self.headline_clusters[hid]

        if to_remove:
            logger.info("Pruned %d noisy clusters", len(to_remove))
