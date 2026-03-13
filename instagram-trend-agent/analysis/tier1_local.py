"""
Tier 1 Local Analysis — Zero-cost metadata analysis.
No API calls, no external services. Pure Python + spaCy/scikit-learn.

Extracts:
- Engagement velocity per reel
- Audio tracking (which clips are accelerating)
- Hashtag co-occurrence graph
- Caption keyword extraction (TF-IDF)
- Posting time patterns
- Account growth signals
- Format detection
"""

import json
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional

from scrapers import ReelData

logger = logging.getLogger(__name__)

# Optional NLP imports
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not installed; using basic keyword extraction")

try:
    import spacy
    try:
        nlp = spacy.load("en_core_web_sm")
        SPACY_AVAILABLE = True
    except OSError:
        SPACY_AVAILABLE = False
        logger.warning("spaCy model not found. Run: python -m spacy download en_core_web_sm")
except ImportError:
    SPACY_AVAILABLE = False


class Tier1Analyzer:
    """
    Performs zero-cost local analysis on scraped reel metadata.
    All computation is local — no API calls required.
    """

    def __init__(self, config: dict, data_dir: str = "data/"):
        self.config = config
        self.data_dir = Path(data_dir)
        self.analysis_cfg = config.get("analysis", {}).get("tier1", {})
        self.hashtag_file = self.data_dir / "hashtag_clusters.json"
        self.min_cooccurrence = self.analysis_cfg.get("hashtag_cooccurrence_min", 3)
        self.tfidf_top = self.analysis_cfg.get("tfidf_top_keywords", 20)

        # Load historical hashtag co-occurrence data
        self.hashtag_cooccurrence = self._load_hashtag_clusters()

    def _load_hashtag_clusters(self) -> Dict[str, Dict[str, int]]:
        """Load hashtag co-occurrence graph from disk."""
        if self.hashtag_file.exists():
            try:
                with open(self.hashtag_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def _save_hashtag_clusters(self):
        """Persist updated hashtag co-occurrence data."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with open(self.hashtag_file, "w") as f:
            json.dump(self.hashtag_cooccurrence, f, indent=2)

    def analyze(self, reels: List[ReelData]) -> Dict:
        """
        Run full Tier 1 analysis pipeline on a batch of reels.

        Returns:
            Dict containing all analysis results
        """
        if not reels:
            return {}

        results = {
            "reel_count": len(reels),
            "analysis_timestamp": datetime.utcnow().isoformat(),
            "audio_trends": self._analyze_audio(reels),
            "hashtag_analysis": self._analyze_hashtags(reels),
            "posting_patterns": self._analyze_posting_patterns(reels),
            "caption_keywords": self._extract_caption_keywords(reels),
            "format_analysis": self._analyze_formats(reels),
            "top_accounts": self._analyze_accounts(reels),
            "engagement_stats": self._compute_engagement_stats(reels),
        }

        # Update and save hashtag co-occurrence
        self._update_hashtag_cooccurrence(reels)
        self._save_hashtag_clusters()

        return results

    def _analyze_audio(self, reels: List[ReelData]) -> List[Dict]:
        """Track which audio clips are appearing across multiple reels."""
        audio_data = defaultdict(lambda: {
            "count": 0,
            "total_engagement_velocity": 0.0,
            "reels": [],
            "artists": Counter(),
        })

        for reel in reels:
            if not reel.audio_name:
                continue
            key = reel.audio_name.strip()
            data = audio_data[key]
            data["count"] += 1
            data["total_engagement_velocity"] += reel.engagement_velocity()
            data["reels"].append(reel.shortcode)
            if reel.audio_artist:
                data["artists"][reel.audio_artist] += 1

        # Convert to list and compute averages
        audio_trends = []
        for audio_name, data in audio_data.items():
            avg_velocity = data["total_engagement_velocity"] / max(data["count"], 1)
            top_artist = data["artists"].most_common(1)[0][0] if data["artists"] else None
            audio_trends.append({
                "audio_name": audio_name,
                "artist": top_artist,
                "reuse_count": data["count"],
                "avg_engagement_velocity": round(avg_velocity, 2),
                "sample_reels": data["reels"][:5],
                "trend_strength": data["count"] * avg_velocity,
            })

        # Sort by trend strength
        audio_trends.sort(key=lambda x: x["trend_strength"], reverse=True)
        return audio_trends[:20]

    def _analyze_hashtags(self, reels: List[ReelData]) -> Dict:
        """Analyze hashtag frequency, velocity, and emerging combinations."""
        tag_counter = Counter()
        tag_velocity = defaultdict(list)
        tag_cooccurrence_today = defaultdict(Counter)

        for reel in reels:
            vel = reel.engagement_velocity()
            tags = reel.hashtags[:30]  # Cap per reel to avoid spam
            for tag in tags:
                tag_counter[tag] += 1
                tag_velocity[tag].append(vel)
                for other_tag in tags:
                    if other_tag != tag:
                        tag_cooccurrence_today[tag][other_tag] += 1

        # Build ranked hashtag list
        ranked_tags = []
        for tag, count in tag_counter.most_common(50):
            velocities = tag_velocity[tag]
            avg_vel = sum(velocities) / len(velocities) if velocities else 0
            ranked_tags.append({
                "hashtag": tag,
                "count": count,
                "avg_engagement_velocity": round(avg_vel, 2),
                "trend_score": round(count * avg_vel, 2),
            })

        # Detect emerging hashtag clusters (new combos not in historical data)
        emerging_clusters = self._detect_emerging_clusters(tag_cooccurrence_today)

        return {
            "top_hashtags": ranked_tags[:30],
            "emerging_clusters": emerging_clusters,
            "total_unique_hashtags": len(tag_counter),
        }

    def _detect_emerging_clusters(self, today_cooccurrence: Dict) -> List[Dict]:
        """Find hashtag pairs that are new or accelerating vs. historical data."""
        emerging = []
        for tag, co_tags in today_cooccurrence.items():
            for co_tag, count in co_tags.most_common(5):
                if count >= 2:
                    historical = (
                        self.hashtag_cooccurrence.get(tag, {}).get(co_tag, 0)
                    )
                    if historical == 0 or count > historical * 2:
                        emerging.append({
                            "hashtag_pair": f"#{tag} + #{co_tag}",
                            "today_count": count,
                            "historical_count": historical,
                            "is_new": historical == 0,
                        })

        emerging.sort(key=lambda x: x["today_count"], reverse=True)
        return emerging[:10]

    def _update_hashtag_cooccurrence(self, reels: List[ReelData]):
        """Update rolling hashtag co-occurrence graph with today's data."""
        for reel in reels:
            tags = reel.hashtags[:20]
            for i, tag in enumerate(tags):
                if tag not in self.hashtag_cooccurrence:
                    self.hashtag_cooccurrence[tag] = {}
                for other in tags:
                    if other != tag:
                        current = self.hashtag_cooccurrence[tag].get(other, 0)
                        # Exponential moving average to weight recent data more
                        self.hashtag_cooccurrence[tag][other] = round(current * 0.8 + 1, 2)

        # Prune hashtags with very low co-occurrence to keep file manageable
        for tag in list(self.hashtag_cooccurrence.keys()):
            self.hashtag_cooccurrence[tag] = {
                k: v for k, v in self.hashtag_cooccurrence[tag].items()
                if v >= self.min_cooccurrence * 0.5
            }
            if not self.hashtag_cooccurrence[tag]:
                del self.hashtag_cooccurrence[tag]

    def _analyze_posting_patterns(self, reels: List[ReelData]) -> Dict:
        """Analyze when viral reels are posted (day of week, hour)."""
        hour_velocity = defaultdict(list)
        day_velocity = defaultdict(list)
        hour_count = Counter()
        day_count = Counter()

        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

        for reel in reels:
            vel = reel.engagement_velocity()
            hour = reel.posted_at.hour
            day = reel.posted_at.weekday()  # 0 = Monday

            hour_velocity[hour].append(vel)
            day_velocity[day].append(vel)
            hour_count[hour] += 1
            day_count[day] += 1

        # Best hours by average velocity
        best_hours = sorted(
            [
                {
                    "hour": h,
                    "count": hour_count[h],
                    "avg_velocity": round(sum(v) / len(v), 2),
                }
                for h, v in hour_velocity.items()
                if v
            ],
            key=lambda x: x["avg_velocity"],
            reverse=True,
        )[:5]

        # Best days by average velocity
        best_days = sorted(
            [
                {
                    "day": days[d],
                    "count": day_count[d],
                    "avg_velocity": round(sum(v) / len(v), 2),
                }
                for d, v in day_velocity.items()
                if v
            ],
            key=lambda x: x["avg_velocity"],
            reverse=True,
        )

        return {
            "best_posting_hours": best_hours,
            "best_posting_days": best_days,
        }

    def _extract_caption_keywords(self, reels: List[ReelData]) -> List[Dict]:
        """
        Extract trending keywords from captions using TF-IDF or basic counting.
        No LLM needed — pure local NLP.
        """
        captions = [r.caption for r in reels if r.caption and len(r.caption) > 10]

        if not captions:
            return []

        if SKLEARN_AVAILABLE and len(captions) >= 3:
            return self._tfidf_keywords(captions)
        else:
            return self._basic_keywords(captions)

    def _tfidf_keywords(self, captions: List[str]) -> List[Dict]:
        """Extract keywords using TF-IDF."""
        try:
            # Remove hashtags for cleaner keyword extraction
            clean_captions = [re.sub(r"#\w+", "", cap) for cap in captions]

            vectorizer = TfidfVectorizer(
                max_features=self.tfidf_top,
                stop_words="english",
                ngram_range=(1, 2),
                min_df=2,
            )
            tfidf_matrix = vectorizer.fit_transform(clean_captions)
            feature_names = vectorizer.get_feature_names_out()
            scores = tfidf_matrix.sum(axis=0).A1

            keywords = [
                {"keyword": feature_names[i], "tfidf_score": round(float(scores[i]), 4)}
                for i in scores.argsort()[::-1][:self.tfidf_top]
            ]
            return keywords
        except Exception as e:
            logger.warning(f"TF-IDF extraction failed: {e}, falling back to basic")
            return self._basic_keywords(captions)

    def _basic_keywords(self, captions: List[str]) -> List[Dict]:
        """Fallback: simple word frequency counting."""
        stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
            "for", "of", "with", "by", "from", "is", "was", "are", "be",
            "it", "this", "that", "my", "your", "our", "i", "we", "you",
        }
        word_counts = Counter()
        for caption in captions:
            # Remove hashtags, URLs, special chars
            text = re.sub(r"#\w+|https?://\S+|@\w+", "", caption.lower())
            words = re.findall(r"\b[a-z]{3,}\b", text)
            for word in words:
                if word not in stop_words:
                    word_counts[word] += 1

        return [
            {"keyword": word, "tfidf_score": count}
            for word, count in word_counts.most_common(self.tfidf_top)
        ]

    def _analyze_formats(self, reels: List[ReelData]) -> Dict:
        """Analyze reel duration and format patterns among high-performers."""
        short_reels = [r for r in reels if r.duration_seconds and r.duration_seconds <= 15]
        medium_reels = [r for r in reels if r.duration_seconds and 15 < r.duration_seconds <= 30]
        long_reels = [r for r in reels if r.duration_seconds and r.duration_seconds > 30]
        unknown_dur = [r for r in reels if not r.duration_seconds]

        def avg_vel(reel_list):
            if not reel_list:
                return 0
            return round(sum(r.engagement_velocity() for r in reel_list) / len(reel_list), 2)

        return {
            "short_0_15s": {"count": len(short_reels), "avg_engagement_velocity": avg_vel(short_reels)},
            "medium_15_30s": {"count": len(medium_reels), "avg_engagement_velocity": avg_vel(medium_reels)},
            "long_30s_plus": {"count": len(long_reels), "avg_engagement_velocity": avg_vel(long_reels)},
            "unknown_duration": {"count": len(unknown_dur), "avg_engagement_velocity": avg_vel(unknown_dur)},
            "best_performing_format": self._best_format(short_reels, medium_reels, long_reels),
        }

    def _best_format(self, short, medium, long) -> str:
        avgs = [
            ("0-15s", sum(r.engagement_velocity() for r in short) / max(len(short), 1) if short else 0),
            ("15-30s", sum(r.engagement_velocity() for r in medium) / max(len(medium), 1) if medium else 0),
            ("30s+", sum(r.engagement_velocity() for r in long) / max(len(long), 1) if long else 0),
        ]
        avgs.sort(key=lambda x: x[1], reverse=True)
        return avgs[0][0] if avgs[0][1] > 0 else "unknown"

    def _analyze_accounts(self, reels: List[ReelData]) -> List[Dict]:
        """Identify accounts producing high-velocity reels."""
        account_data = defaultdict(lambda: {
            "reels": [],
            "total_velocity": 0.0,
            "followers": 0,
        })

        for reel in reels:
            data = account_data[reel.username]
            data["reels"].append(reel.shortcode)
            data["total_velocity"] += reel.engagement_velocity()
            data["followers"] = max(data["followers"], reel.follower_count)

        accounts = []
        for username, data in account_data.items():
            reel_count = len(data["reels"])
            avg_vel = data["total_velocity"] / reel_count
            accounts.append({
                "username": username,
                "reel_count": reel_count,
                "follower_count": data["followers"],
                "avg_engagement_velocity": round(avg_vel, 2),
                "quality_score": round(avg_vel * reel_count, 2),
            })

        accounts.sort(key=lambda x: x["quality_score"], reverse=True)
        return accounts[:20]

    def _compute_engagement_stats(self, reels: List[ReelData]) -> Dict:
        """Compute aggregate engagement statistics."""
        velocities = [r.engagement_velocity() for r in reels]
        likes = [r.likes for r in reels]
        views = [r.views for r in reels if r.views > 0]

        def safe_avg(lst):
            return round(sum(lst) / len(lst), 2) if lst else 0

        def safe_median(lst):
            if not lst:
                return 0
            sorted_lst = sorted(lst)
            mid = len(sorted_lst) // 2
            if len(sorted_lst) % 2 == 0:
                return round((sorted_lst[mid-1] + sorted_lst[mid]) / 2, 2)
            return round(sorted_lst[mid], 2)

        return {
            "total_reels": len(reels),
            "avg_engagement_velocity": safe_avg(velocities),
            "median_engagement_velocity": safe_median(velocities),
            "max_engagement_velocity": round(max(velocities), 2) if velocities else 0,
            "avg_likes": safe_avg(likes),
            "avg_views": safe_avg(views),
            "reels_with_audio": sum(1 for r in reels if r.audio_name),
        }
