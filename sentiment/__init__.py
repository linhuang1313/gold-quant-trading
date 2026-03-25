"""
Sentiment analysis package for gold quantitative trading.

Modules:
  - news_collector : Collects gold-related news from GDELT, RSS, economic calendar
  - analyzer       : Dual-model sentiment analysis (VADER + FinBERT)
  - calendar_guard : Economic event risk guard
  - sentiment_engine : Main integration engine
"""

from sentiment.news_collector import NewsCollector
from sentiment.analyzer import SentimentAnalyzer
from sentiment.calendar_guard import CalendarGuard
from sentiment.sentiment_engine import SentimentEngine

__all__ = [
    "NewsCollector",
    "SentimentAnalyzer",
    "CalendarGuard",
    "SentimentEngine",
]
