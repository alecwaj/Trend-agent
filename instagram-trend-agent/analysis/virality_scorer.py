"""
Virality Scorer — Composite score for ranking Instagram Reels.

Score = (engagement_velocity * 0.4) + (audio_reuse_count * 0.3) + (hashtag_trend_score * 0.3)

All weights configurable in config.yaml.
"""

import logging
from collections import Counter
from typing import List, Dict

from scrapers import ReelData

logger = logging.getLogger(__name__)


class ViralityScorer:
    """
    Computes a composite virality score for each reel using
    engagement velocity, audio reuse frequency, and hashtag trend signals.
    """

    def __init__(self, config: dict):
        weights = config.get("analysis", {}).get("virality_weights", {})
        self.w_engagement = weights.get("engagement_velocity", 0.40)
        self.w_audio = weights.get("audio_reuse_count", 0.30)
        self.w_hashtag = weights.get("hashtag_trend_score", 0.30)

        # Validate weights sum to ~1.0
        total = self.w_engagement + self.w_audio + self.w_hashtag
        if abs(total - 1.0) > 0.01:
            logger.warning(f"Virality weights sum to {total:.2f}, normalizing")
            self.w_engagement /= total
            self.w_audio /= total
            self.w_hashtag /= total

    def score_batch(self, reels: List[ReelData]) -> List[Dict]:
        """
        Score all reels in a batch, computing cross-reel signals first
        (audio reuse counts, hashtag frequencies) then scoring each reel.

        Returns list of dicts with reel data + virality_score field, sorted by score desc.
        """
        if not reels:
            return []

        # Compute corpus-level signals
        audio_counts = self._count_audio_reuse(reels)
        hashtag_scores = self._compute_hashtag_trend_scores(reels)
        max_velocity = self._compute_max_velocity(reels)

        scored = []
        for reel in reels:
            score_data = self._score_single(reel, audio_counts, hashtag_scores, max_velocity)
            scored.append(score_data)

        # Sort by virality score descending
        scored.sort(key=lambda x: x["virality_score"], reverse=True)
        return scored

    def _count_audio_reuse(self, reels: List[ReelData]) -> Counter:
        """Count how many reels use each audio track."""
        counter = Counter()
        for reel in reels:
            if reel.audio_name:
                # Normalize audio name for counting
                key = reel.audio_name.lower().strip()
                counter[key] += 1
        return counter

    def _compute_hashtag_trend_scores(self, reels: List[ReelData]) -> Dict[str, float]:
        """
        Score each hashtag by its frequency-weighted engagement across all reels.
        Higher score = hashtag appears more in high-engagement reels.
        """
        hashtag_engagement = {}  # hashtag -> [engagement_velocities]

        for reel in reels:
            vel = reel.engagement_velocity()
            for tag in reel.hashtags:
                if tag not in hashtag_engagement:
                    hashtag_engagement[tag] = []
                hashtag_engagement[tag].append(vel)

        # Score = count * mean_velocity
        scores = {}
        max_score = 1.0
        for tag, velocities in hashtag_engagement.items():
            if velocities:
                score = len(velocities) * (sum(velocities) / len(velocities))
                scores[tag] = score
                max_score = max(max_score, score)

        # Normalize to [0, 1]
        return {tag: s / max_score for tag, s in scores.items()}

    def _compute_max_velocity(self, reels: List[ReelData]) -> float:
        """Find max engagement velocity for normalization."""
        velocities = [r.engagement_velocity() for r in reels]
        return max(velocities) if velocities else 1.0

    def _score_single(
        self,
        reel: ReelData,
        audio_counts: Counter,
        hashtag_scores: Dict[str, float],
        max_velocity: float,
    ) -> Dict:
        """Compute the virality score for a single reel."""
        # Component 1: Normalized engagement velocity (0-1)
        vel = reel.engagement_velocity()
        norm_velocity = min(vel / max(max_velocity, 1.0), 1.0)

        # Component 2: Audio reuse score (0-1)
        audio_key = reel.audio_name.lower().strip() if reel.audio_name else None
        raw_audio_count = audio_counts.get(audio_key, 0) if audio_key else 0
        max_audio = max(audio_counts.values()) if audio_counts else 1
        norm_audio = raw_audio_count / max(max_audio, 1)

        # Component 3: Hashtag trend score (0-1) = average of reel's hashtag scores
        if reel.hashtags:
            tag_scores = [hashtag_scores.get(tag, 0) for tag in reel.hashtags]
            norm_hashtag = sum(tag_scores) / max(len(tag_scores), 1)
        else:
            norm_hashtag = 0.0

        virality_score = (
            self.w_engagement * norm_velocity
            + self.w_audio * norm_audio
            + self.w_hashtag * norm_hashtag
        )

        return {
            "reel": reel,
            "virality_score": round(virality_score, 4),
            "engagement_velocity": round(vel, 2),
            "norm_engagement_velocity": round(norm_velocity, 4),
            "audio_reuse_count": raw_audio_count,
            "norm_audio_score": round(norm_audio, 4),
            "norm_hashtag_score": round(norm_hashtag, 4),
        }
