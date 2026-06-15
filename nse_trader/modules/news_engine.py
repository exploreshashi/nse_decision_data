"""
News Collection and Scoring Module
Collects news from RSS feeds and scores using keyword-based sentiment analysis.
No LLM dependency — uses curated keyword dictionaries.
"""

import re
import sys
import os
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    POSITIVE_KEYWORDS, NEGATIVE_KEYWORDS,
    NEWS_FRESHNESS_DECAY, NEWS_MAX_AGE_DAYS, STOCK_UNIVERSE
)
from modules.database import get_connection, log_system_event

# ── Try importing feedparser; provide fallback ────────────────────────────────
try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# ── RSS Feed Sources ──────────────────────────────────────────────────────────
RSS_FEEDS = [
    {
        'name': 'MoneyControl Markets',
        'url': 'https://www.moneycontrol.com/rss/marketreports.xml',
        'category': 'market'
    },
    {
        'name': 'MoneyControl Business',
        'url': 'https://www.moneycontrol.com/rss/business.xml',
        'category': 'business'
    },
    {
        'name': 'Economic Times Markets',
        'url': 'https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms',
        'category': 'market'
    },
    {
        'name': 'Economic Times Stocks',
        'url': 'https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms',
        'category': 'stocks'
    },
    {
        'name': 'Livemint Markets',
        'url': 'https://www.livemint.com/rss/markets',
        'category': 'market'
    },
    {
        'name': 'Pulse by Zerodha',
        'url': 'https://pulse.zerodha.com/feed',
        'category': 'aggregated'
    },
]


def fetch_rss_feeds() -> list:
    """Fetch headlines from all configured RSS feeds."""
    if not HAS_FEEDPARSER:
        log_system_event("news", "WARNING", "feedparser not installed. Skipping RSS.")
        return []

    all_entries = []
    for feed_config in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_config['url'])
            for entry in feed.entries[:30]:  # Max 30 per feed
                published = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6]).strftime('%Y-%m-%d %H:%M')
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    published = datetime(*entry.updated_parsed[:6]).strftime('%Y-%m-%d %H:%M')
                else:
                    published = datetime.now().strftime('%Y-%m-%d %H:%M')

                all_entries.append({
                    'headline': entry.get('title', '').strip(),
                    'summary': entry.get('summary', '').strip(),
                    'source': feed_config['name'],
                    'url': entry.get('link', ''),
                    'published_date': published,
                    'category': feed_config['category']
                })

        except Exception as e:
            log_system_event("news", "WARNING", f"Failed to fetch {feed_config['name']}: {e}")

    log_system_event("news", "INFO", f"Fetched {len(all_entries)} news entries from RSS")
    return all_entries


def match_stock_to_headline(headline: str, summary: str = "") -> list:
    """
    Match a headline to stock symbols from our universe.
    Returns list of matched symbols.
    """
    text = f"{headline} {summary}".upper()
    matched = []

    # Common company name → symbol mapping
    COMPANY_ALIASES = {
        'RELIANCE': ['RELIANCE', 'RIL', 'MUKESH AMBANI', 'RELIANCE INDUSTRIES'],
        'TCS': ['TCS', 'TATA CONSULTANCY'],
        'INFY': ['INFOSYS', 'INFY'],
        'HDFCBANK': ['HDFC BANK'],
        'ICICIBANK': ['ICICI BANK'],
        'SBIN': ['SBI', 'STATE BANK'],
        'BHARTIARTL': ['BHARTI AIRTEL', 'AIRTEL'],
        'WIPRO': ['WIPRO'],
        'HCLTECH': ['HCL TECH', 'HCLTECH'],
        'TATAMOTORS': ['TATA MOTORS', 'TATAMOTORS'],
        'MARUTI': ['MARUTI SUZUKI', 'MARUTI'],
        'SUNPHARMA': ['SUN PHARMA', 'SUNPHARMA'],
        'BAJFINANCE': ['BAJAJ FINANCE', 'BAJFINANCE'],
        'KOTAKBANK': ['KOTAK MAHINDRA', 'KOTAK BANK'],
        'AXISBANK': ['AXIS BANK'],
        'LT': ['LARSEN', 'L&T'],
        'TITAN': ['TITAN'],
        'ITC': ['ITC'],
        'HINDUNILVR': ['HINDUSTAN UNILEVER', 'HUL'],
        'ADANIENT': ['ADANI ENTERPRISES', 'ADANIENT'],
        'ADANIPORTS': ['ADANI PORTS', 'ADANIPORTS'],
        'TATASTEEL': ['TATA STEEL', 'TATASTEEL'],
        'JSWSTEEL': ['JSW STEEL', 'JSWSTEEL'],
        'NTPC': ['NTPC'],
        'POWERGRID': ['POWER GRID', 'POWERGRID'],
        'COALINDIA': ['COAL INDIA', 'COALINDIA'],
        'ONGC': ['ONGC'],
        'BPCL': ['BPCL', 'BHARAT PETROLEUM'],
        'HINDPETRO': ['HPCL', 'HINDUSTAN PETROLEUM'],
        'GAIL': ['GAIL'],
        'HAL': ['HAL', 'HINDUSTAN AERONAUTICS'],
        'BEL': ['BEL', 'BHARAT ELECTRONICS'],
        'IRCTC': ['IRCTC'],
        'ZOMATO': ['ZOMATO'],
        'PAYTM': ['PAYTM', 'ONE97'],
        'DLF': ['DLF'],
        'M&M': ['MAHINDRA', 'M&M'],
        'DRREDDY': ['DR REDDY', "DR. REDDY"],
        'CIPLA': ['CIPLA'],
        'DIVISLAB': ['DIVI\'S LAB', 'DIVIS'],
        'APOLLOHOSP': ['APOLLO HOSPITAL', 'APOLLOHOSP'],
        'PERSISTENT': ['PERSISTENT'],
        'DMART': ['DMART', 'AVENUE SUPERMARTS'],
        'NAUKRI': ['NAUKRI', 'INFO EDGE'],
    }

    # Check aliases
    for symbol, aliases in COMPANY_ALIASES.items():
        for alias in aliases:
            if alias in text:
                matched.append(symbol)
                break

    # Direct symbol match for remaining stocks
    for symbol in STOCK_UNIVERSE:
        if symbol not in matched and len(symbol) >= 3:
            # Check if symbol appears as a word boundary
            pattern = r'\b' + re.escape(symbol) + r'\b'
            if re.search(pattern, text):
                matched.append(symbol)

    return list(set(matched))


def score_headline(headline: str, summary: str = "") -> dict:
    """
    Score a headline using keyword matching.
    Returns sentiment, score, and matched keywords.
    """
    text = f"{headline} {summary}".lower()
    pos_score = 0
    neg_score = 0
    pos_matches = []
    neg_matches = []

    for keyword, weight in POSITIVE_KEYWORDS.items():
        if keyword.lower() in text:
            pos_score += weight
            pos_matches.append(keyword)

    for keyword, weight in NEGATIVE_KEYWORDS.items():
        if keyword.lower() in text:
            neg_score += abs(weight)
            neg_matches.append(keyword)

    net_score = pos_score - neg_score

    if net_score > 2:
        sentiment = 'POSITIVE'
    elif net_score < -2:
        sentiment = 'NEGATIVE'
    else:
        sentiment = 'NEUTRAL'

    # Normalize to 0-100 scale
    # Max possible keyword score is roughly 20, so scale accordingly
    normalized_score = max(0, min(100, 50 + (net_score * 5)))

    # Magnitude (1-5 based on total keyword matches)
    total_matches = len(pos_matches) + len(neg_matches)
    magnitude = min(5, max(1, total_matches))

    return {
        'sentiment': sentiment,
        'score': normalized_score,
        'raw_score': net_score,
        'magnitude': magnitude,
        'positive_keywords': pos_matches,
        'negative_keywords': neg_matches,
    }


def apply_freshness_decay(score: float, published_date: str) -> float:
    """Apply time decay to news score. Fresher news = higher score."""
    try:
        pub_date = datetime.strptime(published_date[:10], '%Y-%m-%d')
        days_old = (datetime.now() - pub_date).days

        if days_old > NEWS_MAX_AGE_DAYS:
            return 0

        decay_factor = NEWS_FRESHNESS_DECAY ** days_old
        return score * decay_factor
    except Exception:
        return score * 0.5  # Default to 50% if date parsing fails


def aggregate_stock_news_score(symbol: str) -> dict:
    """
    Get aggregated news score for a stock from database.
    Combines all recent news for the stock.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cutoff = (datetime.now() - timedelta(days=NEWS_MAX_AGE_DAYS)).strftime('%Y-%m-%d')
    cursor.execute("""
        SELECT headline, sentiment, sentiment_score, magnitude, published_date, source
        FROM news
        WHERE symbol = ? AND published_date >= ?
        ORDER BY published_date DESC
    """, (symbol, cutoff))

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return {
            'score': 20,  # Low score for no news
            'news_count': 0,
            'sentiment': 'NO_NEWS',
            'headlines': [],
            'latest_trigger': 'No recent news catalyst'
        }

    total_score = 0
    headlines = []
    sentiments = []

    for row in rows:
        decayed_score = apply_freshness_decay(
            float(row['sentiment_score']),
            row['published_date']
        )
        total_score += decayed_score
        sentiments.append(row['sentiment'])
        headlines.append({
            'headline': row['headline'],
            'source': row['source'],
            'sentiment': row['sentiment'],
            'score': round(decayed_score, 1),
            'date': row['published_date']
        })

    # Average score, capped at 100
    avg_score = min(100, total_score / len(rows))

    # Overall sentiment
    pos_count = sentiments.count('POSITIVE')
    neg_count = sentiments.count('NEGATIVE')
    if pos_count > neg_count:
        overall = 'POSITIVE'
    elif neg_count > pos_count:
        overall = 'NEGATIVE'
    else:
        overall = 'NEUTRAL'

    # Latest trigger description
    if headlines:
        latest = headlines[0]
        trigger = f"{latest['headline']} ({latest['source']}, {latest['date'][:10]})"
    else:
        trigger = 'No specific trigger'

    return {
        'score': round(avg_score, 1),
        'news_count': len(rows),
        'sentiment': overall,
        'headlines': headlines[:5],  # Top 5 most recent
        'latest_trigger': trigger
    }


def process_and_store_news():
    """Fetch news, match to stocks, score, and store in database."""
    entries = fetch_rss_feeds()
    if not entries:
        log_system_event("news", "WARNING", "No news entries to process")
        return 0

    conn = get_connection()
    cursor = conn.cursor()
    stored = 0

    for entry in entries:
        headline = entry['headline']
        summary = entry.get('summary', '')
        
        # Skip empty headlines
        if not headline:
            continue

        # Score the headline
        score_result = score_headline(headline, summary)

        # Match to stocks
        matched_symbols = match_stock_to_headline(headline, summary)

        if matched_symbols:
            for symbol in matched_symbols:
                try:
                    cursor.execute("""
                        INSERT OR IGNORE INTO news
                        (symbol, headline, source, url, published_date,
                         sentiment, sentiment_score, magnitude, category, is_processed)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """, (
                        symbol,
                        headline,
                        entry['source'],
                        entry['url'],
                        entry['published_date'],
                        score_result['sentiment'],
                        score_result['score'],
                        score_result['magnitude'],
                        entry['category']
                    ))
                    stored += 1
                except Exception:
                    continue
        else:
            # Store as unmatched market news
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO news
                    (symbol, headline, source, url, published_date,
                     sentiment, sentiment_score, magnitude, category, is_processed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """, (
                    '_MARKET_',
                    headline,
                    entry['source'],
                    entry['url'],
                    entry['published_date'],
                    score_result['sentiment'],
                    score_result['score'],
                    score_result['magnitude'],
                    entry['category']
                ))
                stored += 1
            except Exception:
                continue

    conn.commit()
    conn.close()

    log_system_event("news", "INFO", f"Processed and stored {stored} news entries")
    return stored


def get_market_news_summary() -> dict:
    """Get overall market news sentiment."""
    conn = get_connection()
    cursor = conn.cursor()

    cutoff = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
    cursor.execute("""
        SELECT headline, sentiment, sentiment_score, source, published_date
        FROM news
        WHERE symbol = '_MARKET_' AND published_date >= ?
        ORDER BY published_date DESC
        LIMIT 20
    """, (cutoff,))

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return {'sentiment': 'NEUTRAL', 'score': 50, 'headlines': []}

    scores = [float(r['sentiment_score']) for r in rows]
    avg = sum(scores) / len(scores) if scores else 50

    headlines = [
        {'headline': r['headline'], 'source': r['source'], 'sentiment': r['sentiment']}
        for r in rows[:10]
    ]

    return {
        'sentiment': 'POSITIVE' if avg > 55 else ('NEGATIVE' if avg < 45 else 'NEUTRAL'),
        'score': round(avg, 1),
        'headlines': headlines
    }
