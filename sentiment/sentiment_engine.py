"""
Sentiment engine — main integration point for the sentiment analysis system.

Combines news collection, sentiment analysis, and calendar risk into a single
trading context that the main trading system can consume.
"""

import logging
import time
from typing import Dict, Optional

from sentiment.news_collector import NewsCollector
from sentiment.analyzer import SentimentAnalyzer
from sentiment.calendar_guard import CalendarGuard

logger = logging.getLogger(__name__)


class SentimentEngine:
    """Unified sentiment engine providing trading context."""

    def __init__(self, cache_ttl: int = 300):
        """
        Args:
            cache_ttl: Cache time-to-live in seconds (default 5 minutes).
        """
        self.collector = NewsCollector()
        self.analyzer = SentimentAnalyzer()
        self.calendar = CalendarGuard(news_collector=self.collector)
        self._cache: Dict = {}
        self._cache_ts: float = 0.0
        self._cache_ttl = cache_ttl

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_trading_context(self) -> Dict:
        """Get full sentiment-based trading context.

        Returns a dict with keys:
          - sentiment: score/label/confidence
          - calendar: risk_level, pause flag, next event
          - news_summary: short text summary
          - trade_modifier: allow_trading, direction_bias, lot_multiplier
        """
        # Return cache if still fresh
        now = time.time()
        if self._cache and (now - self._cache_ts) < self._cache_ttl:
            logger.debug("[舆情引擎] 返回缓存结果")
            return self._cache

        logger.info("[舆情引擎] 开始采集舆情数据...")

        # 1. Calendar risk check (fast, no network needed for calendar)
        calendar_pause, pause_reason = self.calendar.should_pause_trading()
        risk_level = self.calendar.get_risk_level()
        next_event = self.calendar.get_next_event()

        calendar_info = {
            "risk_level": risk_level,
            "pause": calendar_pause,
            "pause_reason": pause_reason,
            "next_event": _format_event(next_event),
        }

        # 2. Collect news
        headlines = self._collect_all_headlines()

        # 3. Sentiment analysis
        sentiment = self.analyzer.get_sentiment_signal(headlines)

        # 4. Build news summary
        news_summary = self._build_summary(headlines, sentiment)

        # 5. Compute trade modifier
        trade_modifier = self._compute_trade_modifier(
            sentiment, calendar_pause, risk_level
        )

        result = {
            "sentiment": {
                "score": sentiment["score"],
                "label": sentiment["label"],
                "confidence": sentiment["confidence"],
            },
            "calendar": calendar_info,
            "news_summary": news_summary,
            "trade_modifier": trade_modifier,
        }

        # Update cache
        self._cache = result
        self._cache_ts = now

        logger.info(
            f"[舆情引擎] 分析完成 — "
            f"情绪: {sentiment['label']}({sentiment['score']:.2f}), "
            f"风险: {risk_level}, "
            f"允许交易: {trade_modifier['allow_trading']}, "
            f"方向偏好: {trade_modifier['direction_bias']}, "
            f"仓位系数: {trade_modifier['lot_multiplier']:.2f}"
        )

        return result

    def invalidate_cache(self):
        """Force next call to re-collect and re-analyze."""
        self._cache = {}
        self._cache_ts = 0.0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _collect_all_headlines(self) -> list:
        """Collect headlines from all sources. Never raises."""
        headlines: list = []
        try:
            gold_news = self.collector.collect_gold_news()
            headlines.extend(a["title"] for a in gold_news if a.get("title"))
        except Exception as exc:
            logger.warning(f"[舆情引擎] 黄金新闻采集失败: {exc}")

        try:
            trump_news = self.collector.collect_trump_posts()
            headlines.extend(a["title"] for a in trump_news if a.get("title"))
        except Exception as exc:
            logger.warning(f"[舆情引擎] 特朗普新闻采集失败: {exc}")

        # Deduplicate while preserving order
        seen: set = set()
        unique: list = []
        for h in headlines:
            h_lower = h.lower().strip()
            if h_lower and h_lower not in seen:
                seen.add(h_lower)
                unique.append(h)

        return unique

    def _build_summary(self, headlines: list, sentiment: Dict) -> str:
        """Build a concise Chinese-language summary of the news."""
        if not headlines:
            return "当前无相关新闻数据"

        label_cn = {
            "BULLISH": "看涨",
            "BEARISH": "看跌",
            "NEUTRAL": "中性",
        }
        label = label_cn.get(sentiment["label"], "中性")
        count = len(headlines)
        score = sentiment["score"]

        # Pick up to 3 representative headlines
        samples = headlines[:3]
        sample_text = " | ".join(samples)

        return (
            f"分析{count}条新闻，整体情绪{label}(得分{score:.2f})。"
            f"代表性标题: {sample_text}"
        )

    def _compute_trade_modifier(
        self,
        sentiment: Dict,
        calendar_pause: bool,
        risk_level: str,
    ) -> Dict:
        """Decide trading adjustments based on sentiment + calendar.

        Decision logic:
          1. Calendar says pause → allow_trading=False
          2. Extreme BULLISH (>0.5) → direction_bias=BUY, lot_multiplier=1.2
          3. Extreme BEARISH (<-0.5) → direction_bias=SELL, lot_multiplier=1.2
          4. Otherwise → neutral
          5. HIGH calendar risk → lot_multiplier *= 0.5
        """
        # Default
        allow_trading = True
        direction_bias: Optional[str] = None
        lot_multiplier = 1.0

        # 1. Calendar pause overrides everything
        if calendar_pause:
            return {
                "allow_trading": False,
                "direction_bias": None,
                "lot_multiplier": 0.0,
            }

        # 2-3. Sentiment-based direction bias
        score = sentiment["score"]
        if score > 0.5:
            direction_bias = "BUY"
            lot_multiplier = 1.2
        elif score < -0.5:
            direction_bias = "SELL"
            lot_multiplier = 1.2

        # 5. Calendar risk scaling
        if risk_level == "HIGH":
            lot_multiplier *= 0.5
        elif risk_level == "EXTREME":
            lot_multiplier *= 0.3

        lot_multiplier = round(lot_multiplier, 2)

        return {
            "allow_trading": allow_trading,
            "direction_bias": direction_bias,
            "lot_multiplier": lot_multiplier,
        }


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------
def _format_event(event: Optional[Dict]) -> Optional[str]:
    """Format an event dict into a readable string."""
    if event is None:
        return None
    dt = event["datetime_utc"]
    return f"{event['name']} @ {dt.strftime('%Y-%m-%d %H:%M')} UTC ({event['impact']})"
