"""
Sentiment analysis module using dual-model approach:
  1. VADER  — fast, lightweight, rule-based (weight 0.3)
  2. FinBERT — deep, transformer-based, finance-tuned (weight 0.7)

Falls back to VADER-only if FinBERT is unavailable.
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gold-specific keyword adjustments
# ---------------------------------------------------------------------------
# Positive for gold (safe haven, dovish, uncertainty)
BULLISH_KEYWORDS = {
    "rate cut": 0.15,
    "dovish": 0.15,
    "inflation": 0.10,
    "war": 0.20,
    "sanctions": 0.15,
    "tariff": 0.12,
    "uncertainty": 0.10,
    "recession": 0.12,
    "crisis": 0.15,
    "safe haven": 0.15,
    "debt ceiling": 0.10,
    "geopolitical": 0.10,
    "escalation": 0.12,
}

# Negative for gold (risk-on, hawkish, strong dollar)
BEARISH_KEYWORDS = {
    "rate hike": -0.15,
    "hawkish": -0.15,
    "strong dollar": -0.12,
    "peace deal": -0.15,
    "risk on": -0.10,
    "ceasefire": -0.10,
    "rally equities": -0.08,
    "stock market rally": -0.08,
    "dollar strength": -0.12,
}

# Trump-related news gets amplified
TRUMP_AMPLIFIER = 1.5

# ---------------------------------------------------------------------------
# VADER setup (lazy init)
# ---------------------------------------------------------------------------
_vader_analyzer = None


def _get_vader():
    """Lazily initialise VADER, downloading lexicon if needed."""
    global _vader_analyzer
    if _vader_analyzer is not None:
        return _vader_analyzer
    try:
        import nltk
        from nltk.sentiment.vader import SentimentIntensityAnalyzer

        # Ensure lexicon is available
        try:
            nltk.data.find("sentiment/vader_lexicon.zip")
        except LookupError:
            logger.info("[情绪分析] 正在下载VADER词典...")
            nltk.download("vader_lexicon", quiet=True)

        _vader_analyzer = SentimentIntensityAnalyzer()
        logger.info("[情绪分析] VADER模型加载成功")
        return _vader_analyzer
    except Exception as exc:
        logger.error(f"[情绪分析] VADER加载失败: {exc}")
        return None


# ---------------------------------------------------------------------------
# FinBERT setup (lazy init)
# ---------------------------------------------------------------------------
_finbert_pipeline = None
_finbert_attempted = False


def _get_finbert():
    """Lazily load FinBERT pipeline. Returns None if unavailable."""
    global _finbert_pipeline, _finbert_attempted
    if _finbert_pipeline is not None:
        return _finbert_pipeline
    if _finbert_attempted:
        return None  # Already failed, don't retry
    _finbert_attempted = True
    try:
        from transformers import pipeline as hf_pipeline

        logger.info("[情绪分析] 正在加载FinBERT模型 (首次使用会自动下载)...")
        _finbert_pipeline = hf_pipeline(
            "sentiment-analysis",
            model="ProsusAI/finbert",
            tokenizer="ProsusAI/finbert",
            truncation=True,
            max_length=512,
        )
        logger.info("[情绪分析] FinBERT模型加载成功")
        return _finbert_pipeline
    except Exception as exc:
        logger.warning(f"[情绪分析] FinBERT加载失败，将使用纯VADER模式: {exc}")
        return None


# ---------------------------------------------------------------------------
# SentimentAnalyzer
# ---------------------------------------------------------------------------
class SentimentAnalyzer:
    """Dual-model sentiment analyzer tuned for gold markets."""

    def analyze_headlines(self, headlines: List[str]) -> Dict:
        """Analyze a batch of headlines and return aggregate sentiment.

        Returns:
            {
                "vader_score": float,
                "finbert_score": float | None,
                "combined_score": float,      # -1 to 1
                "keyword_adjustment": float,
                "headline_count": int,
                "model_mode": "dual" | "vader_only",
            }
        """
        if not headlines:
            return self._empty_result()

        vader_score = self._vader_analyze(headlines)
        finbert_score = self._finbert_analyze(headlines)
        kw_adj = self._keyword_adjustment(headlines)

        # Combine scores
        if finbert_score is not None:
            raw = vader_score * 0.3 + finbert_score * 0.7
            mode = "dual"
        else:
            raw = vader_score
            finbert_score = None
            mode = "vader_only"

        # Apply keyword adjustment (clamped to [-1, 1])
        combined = max(-1.0, min(1.0, raw + kw_adj))

        return {
            "vader_score": round(vader_score, 4),
            "finbert_score": round(finbert_score, 4) if finbert_score is not None else None,
            "combined_score": round(combined, 4),
            "keyword_adjustment": round(kw_adj, 4),
            "headline_count": len(headlines),
            "model_mode": mode,
        }

    def get_sentiment_signal(self, headlines: Optional[List[str]] = None) -> Dict:
        """Return a trading-ready sentiment signal.

        Args:
            headlines: If provided, analyze these. Otherwise return neutral.

        Returns:
            {
                "score": float,          # -1 to 1
                "label": str,            # BULLISH / BEARISH / NEUTRAL
                "confidence": float,     # 0 to 1
                "details": {...},
            }
        """
        if not headlines:
            return {
                "score": 0.0,
                "label": "NEUTRAL",
                "confidence": 0.0,
                "details": self._empty_result(),
            }

        details = self.analyze_headlines(headlines)
        score = details["combined_score"]

        if score > 0.3:
            label = "BULLISH"
        elif score < -0.3:
            label = "BEARISH"
        else:
            label = "NEUTRAL"

        confidence = min(1.0, abs(score))

        return {
            "score": score,
            "label": label,
            "confidence": round(confidence, 4),
            "details": details,
        }

    # ------------------------------------------------------------------
    # Private methods
    # ------------------------------------------------------------------

    def _vader_analyze(self, headlines: List[str]) -> float:
        """Compute average VADER compound score across headlines."""
        vader = _get_vader()
        if vader is None:
            return 0.0

        total = 0.0
        for h in headlines:
            scores = vader.polarity_scores(h)
            total += scores["compound"]
        return total / len(headlines) if headlines else 0.0

    def _finbert_analyze(self, headlines: List[str]) -> Optional[float]:
        """Compute average FinBERT score. Returns None if model unavailable."""
        pipe = _get_finbert()
        if pipe is None:
            return None

        try:
            # FinBERT returns: {"label": "positive"/"negative"/"neutral", "score": float}
            results = pipe(headlines, batch_size=16)
        except Exception as exc:
            logger.warning(f"[情绪分析] FinBERT推理失败: {exc}")
            return None

        total = 0.0
        for r in results:
            label = r["label"].lower()
            prob = r["score"]
            if label == "positive":
                total += prob
            elif label == "negative":
                total -= prob
            # neutral contributes 0

        return total / len(headlines) if headlines else 0.0

    def _keyword_adjustment(self, headlines: List[str]) -> float:
        """Apply gold-specific keyword adjustments."""
        adj = 0.0
        joined = " ".join(headlines).lower()

        is_trump = "trump" in joined

        for kw, weight in BULLISH_KEYWORDS.items():
            if kw in joined:
                adj += weight
        for kw, weight in BEARISH_KEYWORDS.items():
            if kw in joined:
                adj += weight  # weight is already negative

        # Amplify if Trump-related
        if is_trump:
            adj *= TRUMP_AMPLIFIER

        # Cap adjustment to avoid overwhelming the model scores
        return max(-0.3, min(0.3, adj))

    def _empty_result(self) -> Dict:
        return {
            "vader_score": 0.0,
            "finbert_score": None,
            "combined_score": 0.0,
            "keyword_adjustment": 0.0,
            "headline_count": 0,
            "model_mode": "vader_only",
        }
