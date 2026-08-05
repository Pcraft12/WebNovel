#!/usr/bin/env python3
"""
universal_novel_scraper.py
==========================

Universal web scraper platform for Chinese web novels.

Features:
1. Multi-source search across novel websites and Google
2. Intelligent chapter list extraction with proper sorting
3. Handles various site structures:
   - Latest chapters + full list pagination
   - Expand button functionality
   - Duplicate chapter removal
   - Chapter number detection and sorting
4. Preferred sources support:
   - https://ixdzs8.com
   - https://www.xbiquge.info/
   - https://www.biquge.company/
   - https://www.ttkan.co/
   - https://m.shuhaige.net/

Usage:
    python universal_novel_scraper.py search "洪荒：我開局打造鴻蒙金榜"
    python universal_novel_scraper.py chapters <novel_url>
    python universal_novel_scraper.py extract <chapter_url>
    python universal_novel_scraper.py interactive
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urljoin, urlparse, parse_qs, quote
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup, Tag
except ImportError:
    sys.exit("Required packages: pip install requests beautifulsoup4 lxml")

# Try to import the bypasser for Cloudflare protection
try:
    from bypasser import Bypasser, fetch as bp_fetch
    BYPASSER_AVAILABLE = True
except ImportError:
    BYPASSER_AVAILABLE = False

# Try to import the existing novel_extractor for chapter content extraction
try:
    from novel_extractor import extract_chapter
except ImportError:
    extract_chapter = None


# ============================================================================
# Configuration
# ============================================================================

# Preferred novel sources with their configurations
SOURCES = {
    "ixdzs8": {
        "name": "ixdzs8",
        "base_url": "https://ixdzs8.com",
        "search_url": "https://ixdzs8.com/bsearch?q={query}",
        "search_method": "GET",
        "search_selector": ".u-list li, .book-item, .search-result",
        "chapter_list_pattern": r"/book/\d+/dir",
        "has_expand": True,
        "expand_button_selector": ".catalog-all, .catalog",
        "ajax_chapter_url": "/record/getchapters/",
        "latest_chapters_first": False,
        "duplicate_latest_count": 12,
        "feed_url": "https://ixdzs8.com/hot/day/",
        "feed_selector": ".u-list li, .book-item",
    },
    "xbiquge": {
        "name": "xbiquge",
        "base_url": "https://www.xbiquge.info",
        "search_url": "https://www.xbiquge.info/search.php?q={query}",
        "search_method": "GET",
        "search_selector": "#maincontent tr, .grid tr, .bookbox",
        "chapter_list_pattern": r"/\d+/",
        "has_expand": False,
        "latest_chapters_first": False,
        "duplicate_latest_count": 0,
        "feed_url": "https://www.xbiquge.info/top/week_0_1.html",
        "feed_selector": "#maincontent tr, .grid tr",
    },
    "biquge_company": {
        "name": "biquge.company",
        "base_url": "https://www.biquge.company",
        "search_url": "https://www.biquge.company/modules/article/search.php",
        "search_method": "POST",
        "search_data": {"searchkey": "{query}", "action": "login"},
        "search_selector": ".bookbox, .bookinfo",
        "chapter_list_pattern": r"/book/\d+/",
        "has_expand": False,
        "latest_chapters_first": False,
        "duplicate_latest_count": 0,
        "feed_url": "https://www.biquge.company/sort/0/1.html",
        "feed_selector": ".bookbox, .bookinfo",
    },
    "ttkan": {
        "name": "ttkan",
        "base_url": "https://www.ttkan.co",
        "search_url": "https://www.ttkan.co/novel/search?q={query}",
        "search_method": "GET",
        "search_selector": ".novel_cell, [data-v-2ba0104b] .pure-g > div",
        "chapter_list_pattern": r"/novels/[^/]+/",
        "has_expand": False,
        "expand_button_selector": "",
        "latest_chapters_first": False,
        "duplicate_latest_count": 0,
        "feed_url": "https://www.ttkan.co/novel/rank",
        "feed_selector": ".novel_cell, [data-v-2ba0104b] .pure-g > div",
    },
    "shuhaige": {
        "name": "shuhaige",
        "base_url": "https://m.shuhaige.net",
        "search_url": "https://m.shuhaige.net/search.html",
        "search_method": "POST",
        "search_data": {"searchkey": "{query}"},
        "search_selector": ".list li, .book-item, .search-result",
        "chapter_list_pattern": r"/read/\d+/|/shu_\d+/",
        "has_pagination": True,
        "pagination_pattern": r"/(\d+)_(\d+)/",
        "latest_chapters_first": True,
        "duplicate_latest_count": 0,
        "feed_url": "https://shuhaige.net/shuku/",
        "feed_selector": ".list li, .book-item",
    },
}

# Default headers for requests
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

# Chapter number patterns for sorting
CHAPTER_NUMBER_PATTERNS = [
    # Chinese format: 第 X 章
    (re.compile(r"第\s*([0-9〇零一二三四五六七八九十百千两\\d]+)\s*章"), "chinese"),
    # English format: Chapter X
    (re.compile(r"[Cc]hap(?:ter)?\.?\s*([0-9IVXLCDM]+)", re.I), "roman"),
    # English format: Chap X
    (re.compile(r"[Cc]hap\.?\s*([0-9]+)", re.I), "number"),
    # Volume format: 第 X 卷 第 Y 章
    (re.compile(r"第\s*([0-9〇零一二三四五六七八九十百千两\\d]+)\s*卷.*?第\s*([0-9〇零一二三四五六七八九十百千两\\d]+)\s*章"), "chinese_volume"),
    # Simple number at start
    (re.compile(r"^\s*([0-9]+)\s*[\\.、]"), "simple"),
    # Roman numeral at start
    (re.compile(r"^\s*([IVXLCDM]+)\s*[:.、]?"), "roman_simple"),
]

# Chinese number to Arabic conversion
CHINESE_NUMBERS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    "十": 10, "百": 100, "千": 1000, "万": 10000,
}

ROMAN_NUMERALS = {
    "I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000,
}


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class SearchResult:
    """Represents a novel search result."""
    title: str
    url: str
    source: str
    author: str = ""
    description: str = ""
    cover_url: str = ""
    latest_chapter: str = ""
    status: str = ""
    rating: str = ""
    word_count: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "author": self.author,
            "description": self.description,
            "cover_url": self.cover_url,
            "latest_chapter": self.latest_chapter,
            "status": self.status,
            "rating": self.rating,
            "word_count": self.word_count,
        }


@dataclass
class ChapterInfo:
    """Represents a chapter in the chapter list."""
    title: str
    url: str
    chapter_number: float = 0.0
    volume: int = 0
    original_index: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "chapter_number": self.chapter_number,
            "volume": self.volume,
        }


@dataclass
class NovelInfo:
    """Complete novel information with chapters."""
    title: str
    url: str
    source: str
    author: str = ""
    description: str = ""
    cover_url: str = ""
    status: str = ""
    chapters: List[ChapterInfo] = field(default_factory=list)
    total_chapters: int = 0
    rating: str = ""
    word_count: str = ""
    recommendations: List[Dict[str, str]] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "author": self.author,
            "description": self.description,
            "cover_url": self.cover_url,
            "status": self.status,
            "total_chapters": self.total_chapters,
            "chapters": [c.to_dict() for c in self.chapters],
            "rating": self.rating,
            "word_count": self.word_count,
            "recommendations": self.recommendations,
            "categories": self.categories,
        }


# ============================================================================
# Utility Functions
# ============================================================================

# Global bypasser instance (lazy-initialized)
_bypasser_instance: Optional[Bypasser] = None


def _get_bypasser() -> Optional[Bypasser]:
    """Get or create bypasser instance."""
    global _bypasser_instance
    if not BYPASSER_AVAILABLE:
        return None
    if _bypasser_instance is None:
        _bypasser_instance = Bypasser()
    return _bypasser_instance


def fetch_url(url: str, headers: Optional[Dict] = None, timeout: int = 30, 
              method: str = "GET", data: Optional[Dict] = None, 
              use_bypasser: bool = True) -> Optional[str]:
    """
    Fetch URL content with error handling, supporting GET and POST methods.
    
    Args:
        url: URL to fetch
        headers: Optional custom headers
        timeout: Request timeout in seconds
        method: HTTP method (GET or POST)
        data: POST data (if method is POST)
        use_bypasser: Whether to use bypasser for Cloudflare protection
    
    Returns:
        HTML content as string, or None on failure
    """
    # Try bypasser first if available and requested
    if use_bypasser and BYPASSER_AVAILABLE:
        try:
            bp = _get_bypasser()
            if bp:
                if method.upper() == "POST" and data:
                    result = bp.fetch(url, method="POST", data=data)
                else:
                    result = bp.fetch(url, method="GET")
                if result and len(result.strip()) > 100:
                    return result
        except Exception as e:
            # Fallback to regular requests
            pass
    
    # Fallback to regular requests
    try:
        if method.upper() == "POST" and data:
            response = requests.post(
                url,
                data=data,
                headers=headers or DEFAULT_HEADERS,
                timeout=timeout,
                allow_redirects=True,
            )
        else:
            response = requests.get(
                url,
                headers=headers or DEFAULT_HEADERS,
                timeout=timeout,
                allow_redirects=True,
            )
        response.encoding = response.apparent_encoding
        if response.status_code == 200:
            return response.text
        else:
            print(f"Error fetching {url}: HTTP {response.status_code}", file=sys.stderr)
            return None
    except requests.RequestException as e:
        print(f"Request error for {url}: {e}", file=sys.stderr)
        return None


def get_source_from_url(url: str) -> Optional[str]:
    """Identify which source a URL belongs to."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    
    for source_id, config in SOURCES.items():
        if source_id in domain or config["base_url"].split("//")[1].split("/")[0] in domain:
            return source_id
    return None


def chinese_to_arabic(chinese_num: str) -> int:
    """Convert Chinese numerals to Arabic numbers."""
    result = 0
    current = 0
    base = 1
    
    for char in reversed(chinese_num):
        if char in CHINESE_NUMBERS:
            val = CHINESE_NUMBERS[char]
            if val >= 10:
                base = val
                current = 0
            else:
                current += val * base
                base = 1
        elif char.isdigit():
            # Handle mixed format
            return int(chinese_num)
    
    result += current
    return result if result > 0 else 0


def roman_to_arabic(roman: str) -> int:
    """Convert Roman numerals to Arabic numbers."""
    result = 0
    prev_value = 0
    
    for char in reversed(roman.upper()):
        if char not in ROMAN_NUMERALS:
            return 0
        value = ROMAN_NUMERALS[char]
        if value < prev_value:
            result -= value
        else:
            result += value
        prev_value = value
    
    return result


def extract_chapter_number(title: str) -> Tuple[float, int]:
    """
    Extract chapter number and volume from chapter title.
    Returns (chapter_number, volume).
    """
    # Check for volume format FIRST: 第 X 卷 第 Y 章
    volume_pattern = re.compile(r"第\s*([0-9〇零一二三四五六七八九十百千两]+)\s*卷.*?第\s*([0-9〇零一二三四五六七八九十百千两]+)\s*章")
    volume_match = volume_pattern.search(title)
    if volume_match:
        volume = chinese_to_arabic(volume_match.group(1))
        chapter = chinese_to_arabic(volume_match.group(2))
        return float(chapter), volume
    
    for pattern, num_type in CHAPTER_NUMBER_PATTERNS:
        match = pattern.search(title)
        if match:
            groups = match.groups()
            
            if num_type == "chinese":
                num_str = groups[0]
                # Check if it's already Arabic
                if num_str.isdigit():
                    return float(num_str), 0
                return float(chinese_to_arabic(num_str)), 0
            
            if num_type == "roman":
                return float(roman_to_arabic(groups[0])), 0
            
            if num_type == "roman_simple":
                return float(roman_to_arabic(groups[0])), 0
            
            if num_type == "number" or num_type == "simple":
                return float(groups[0]), 0
    
    # No pattern matched, return 0
    return 0.0, 0


# ============================================================================
# Search Functions
# ============================================================================

def search_source(source_id: str, query: str) -> List[SearchResult]:
    """Search a specific source for novels."""
    if source_id not in SOURCES:
        print(f"Unknown source: {source_id}", file=sys.stderr)
        return []
    
    config = SOURCES[source_id]
    
    # Build search URL and data
    search_url = config["search_url"].format(query=quote(query))
    search_method = config.get("search_method", "GET")
    search_data = None
    
    # Handle POST data with query substitution
    if search_method.upper() == "POST" and "search_data" in config:
        search_data = {}
        for key, value in config["search_data"].items():
            search_data[key] = value.format(query=query)
        # For POST, the URL doesn't need the query parameter
        search_url = config["search_url"]
    
    html = fetch_url(search_url, method=search_method, data=search_data)
    if not html:
        return []
    
    soup = BeautifulSoup(html, "lxml")
    results = []
    
    # Get selector from config or use defaults
    selector = config.get("search_selector", ".novel-item, .book-item, .search-result")
    
    # Source-specific parsing logic
    if source_id == "ixdzs8":
        # Look for novel items in search results
        for item in soup.select(".u-list li, .book-item, .search-result"):
            title_el = item.select_one("h3 a, h2 a, .title a")
            if not title_el:
                continue
            
            title = title_el.get_text(strip=True)
            url = urljoin(config["base_url"], title_el.get("href", ""))
            
            author_el = item.select_one(".author, .book-author")
            author = author_el.get_text(strip=True) if author_el else ""
            
            desc_el = item.select_one(".desc, .description, .intro")
            description = desc_el.get_text(strip=True) if desc_el else ""
            
            latest_el = item.select_one(".latest-chapter, .last-chapter")
            latest_chapter = latest_el.get_text(strip=True) if latest_el else ""
            
            # Extract cover image
            cover_el = item.select_one("img.cover, img.book-cover, .cover img")
            cover_url = urljoin(config["base_url"], cover_el.get("src", "")) if cover_el else ""
            
            # Extract rating if available
            rating_el = item.select_one(".rating, .score, .stars")
            rating = rating_el.get_text(strip=True) if rating_el else ""
            
            results.append(SearchResult(
                title=title,
                url=url,
                source=source_id,
                author=author,
                description=description,
                cover_url=cover_url,
                latest_chapter=latest_chapter,
                rating=rating,
            ))
    
    elif source_id == "xbiquge":
        for item in soup.select("#maincontent tr, .grid tr, .bookbox"):
            cols = item.find_all("td")
            if len(cols) >= 3:
                title_el = cols[0].find("a")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                url = urljoin(config["base_url"], title_el.get("href", ""))
                author = cols[1].get_text(strip=True) if len(cols) > 1 else ""
                latest_chapter = cols[3].get_text(strip=True) if len(cols) > 3 else ""
                cover_el = cols[0].select_one("img")
                cover_url = urljoin(config["base_url"], cover_el.get("src", "")) if cover_el else ""
                results.append(SearchResult(title=title, url=url, source=source_id, author=author, cover_url=cover_url, latest_chapter=latest_chapter))
            elif item.has_attr('class') and 'bookbox' in item.get('class', []):
                title_el = item.select_one(".bookname a")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                url = urljoin(config["base_url"], title_el.get("href", ""))
                author_el = item.select_one(".author")
                author = author_el.get_text(strip=True).replace("作者：", "") if author_el else ""
                latest_el = item.select_one(".cat a")
                latest_chapter = latest_el.get_text(strip=True) if latest_el else ""
                cover_el = item.select_one("img")
                cover_url = urljoin(config["base_url"], cover_el.get("src", "")) if cover_el else ""
                results.append(SearchResult(title=title, url=url, source=source_id, author=author, cover_url=cover_url, latest_chapter=latest_chapter))
    
    elif source_id == "biquge_company":
        for item in soup.select(".bookbox, .bookinfo"):
            title_el = item.select_one(".bookname a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            url = urljoin(config["base_url"], title_el.get("href", ""))
            author_el = item.select_one(".author")
            author = author_el.get_text(strip=True).replace("作者：", "") if author_el else ""
            latest_el = item.select_one(".cat a")
            latest_chapter = latest_el.get_text(strip=True) if latest_el else ""
            desc_el = item.select_one(".update")
            description = desc_el.get_text(strip=True) if desc_el else ""
            cover_el = item.select_one("img")
            cover_url = urljoin(config["base_url"], cover_el.get("src", "")) if cover_el else ""
            results.append(SearchResult(title=title, url=url, source=source_id, author=author, description=description, cover_url=cover_url, latest_chapter=latest_chapter))
    
    elif source_id == "ttkan":
        for item in soup.select(".novel_cell, [data-v-2ba0104b] .pure-g > div"):
            title_el = item.select_one("h3 a, .title a, a[title]")
            if not title_el:
                links = item.find_all("a", href=True)
                for link in links:
                    href = link.get("href", "")
                    if "/novels/" in href or "/novel/" in href:
                        title_el = link
                        break
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if len(title) < 2:
                continue
            url = urljoin(config["base_url"], title_el.get("href", ""))
            author_el = item.select_one(".author")
            author = author_el.get_text(strip=True) if author_el else ""
            cover_el = item.select_one("img.book-cover, img.cover, .cover img")
            cover_url = urljoin(config["base_url"], cover_el.get("src", "")) if cover_el else ""
            rating_el = item.select_one(".rating, .score, .stars")
            rating = rating_el.get_text(strip=True) if rating_el else ""
            results.append(SearchResult(title=title, url=url, source=source_id, author=author, cover_url=cover_url, rating=rating))
    
    elif source_id == "shuhaige":
        for item in soup.select(".list li, .book-item, .search-result"):
            title_el = item.select_one(".bookname a, h3 a, .book-title a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            url = urljoin(config["base_url"], title_el.get("href", ""))
            author_el = item.select_one(".data a, .author")
            author = author_el.get_text(strip=True) if author_el else ""
            latest_el = item.select_one(".data a:last-child")
            latest_chapter = latest_el.get_text(strip=True) if latest_el else ""
            cover_el = item.select_one("img.book-cover, img.cover, .cover img")
            cover_url = urljoin(config["base_url"], cover_el.get("src", "")) if cover_el else ""
            results.append(SearchResult(title=title, url=url, source=source_id, author=author, cover_url=cover_url, latest_chapter=latest_chapter))
    
    else:
        # Generic fallback parsing
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if any(pattern in href for pattern in ["/book/", "/novel/", "/read/"]):
                title = link.get_text(strip=True)
                if len(title) > 5 and len(title) < 100:
                    url = urljoin(config["base_url"], href)
                    results.append(SearchResult(title=title, url=url, source=source_id))
    
    return results


def get_home_feed(source_id: str, page: int = 1) -> List[SearchResult]:
    """
    Get home feed / popular novels from a source.
    
    Args:
        source_id: Source identifier
        page: Page number for pagination
    
    Returns:
        List of SearchResult with cover images, titles, etc.
    """
    if source_id not in SOURCES:
        print(f"Unknown source: {source_id}", file=sys.stderr)
        return []
    
    config = SOURCES[source_id]
    feed_url = config.get("feed_url")
    
    if not feed_url:
        print(f"No feed URL configured for {source_id}", file=sys.stderr)
        return []
    
    # Handle pagination in feed URL
    if "{page}" in feed_url:
        feed_url = feed_url.format(page=page)
    
    html = fetch_url(feed_url)
    if not html:
        return []
    
    soup = BeautifulSoup(html, "lxml")
    results = []
    
    # Source-specific parsing logic for feeds
    if source_id == "ixdzs8":
        for item in soup.select(".burl, .u-list li, .book-item"):
            title_el = item.select_one("h3 a, h2 a, .title a, .bname a")
            if not title_el:
                continue
            
            title = title_el.get_text(strip=True)
            url = urljoin(config["base_url"], title_el.get("href", ""))
            
            author_el = item.select_one(".author, .book-author, .bauthor a")
            author = author_el.get_text(strip=True) if author_el else ""
            
            desc_el = item.select_one(".desc, .description, .intro, .l-p2")
            description = desc_el.get_text(strip=True) if desc_el else ""
            
            # Extract cover image - critical for home feed
            cover_el = item.select_one("img")
            if cover_el:
                cover_src = cover_el.get("src", "") or cover_el.get("data-src", "")
                cover_url = urljoin(config["base_url"], cover_src) if cover_src else ""
            else:
                cover_url = ""
            
            # Extract rating if available
            rating_el = item.select_one(".rating, .score, .stars")
            rating = rating_el.get_text(strip=True) if rating_el else ""
            
            results.append(SearchResult(
                title=title,
                url=url,
                source=source_id,
                author=author,
                description=description,
                cover_url=cover_url,
                rating=rating,
            ))
    
    elif source_id == "xbiquge":
        # XBiquge uses h3 tags for novel titles in top lists
        for item in soup.find_all("h3"):
            title_el = item.find("a")
            if not title_el:
                continue
            
            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            
            # Skip non-novel links (search, homepage, etc)
            if not href or href.startswith("/") and len(href) < 5:
                continue
            if "?" in href or "search" in href.lower():
                continue
                
            # Only accept /XX/XX/ pattern (novel info pages)
            if not re.match(r'^/\d+/\d+/$', href):
                continue
            
            url = urljoin(config["base_url"], href)
            
            # Get parent div to find cover image
            parent_div = item.parent
            cover_el = parent_div.select_one("img") if parent_div else None
            cover_url = urljoin(config["base_url"], cover_el.get("src", "")) if cover_el else ""
            
            results.append(SearchResult(
                title=title,
                url=url,
                source=source_id,
                cover_url=cover_url,
            ))
    
    elif source_id == "biquge_company":
        for item in soup.select(".bookbox, .bookinfo"):
            title_el = item.select_one("h3 a, h2 a, .title a")
            if not title_el:
                continue
            
            title = title_el.get_text(strip=True)
            url = urljoin(config["base_url"], title_el.get("href", ""))
            
            author_el = item.select_one(".author")
            author = author_el.get_text(strip=True) if author_el else ""
            
            # Extract cover image
            cover_el = item.select_one("img")
            cover_url = urljoin(config["base_url"], cover_el.get("src", "")) if cover_el else ""
            
            results.append(SearchResult(
                title=title,
                url=url,
                source=source_id,
                author=author,
                cover_url=cover_url,
            ))
    
    elif source_id == "ttkan":
        # TTKan uses Vue.js - try multiple selectors
        for item in soup.select(".rank-item, .novel-item, li, .item"):
            title_el = item.select_one("a[href*='/novels/'], h3 a, .title a")
            if not title_el:
                continue
            
            title = title_el.get_text(strip=True)
            if len(title) < 2 or len(title) > 100:
                continue
                
            url = urljoin(config["base_url"], title_el.get("href", ""))
            
            author_el = item.select_one(".author, .author-name")
            author = author_el.get_text(strip=True) if author_el else ""
            
            # Extract cover image
            cover_el = item.select_one("img")
            cover_url = urljoin(config["base_url"], cover_el.get("src", "") or cover_el.get("data-src", "")) if cover_el else ""
            
            # Extract rating
            rating_el = item.select_one(".rating, .score")
            rating = rating_el.get_text(strip=True) if rating_el else ""
            
            results.append(SearchResult(
                title=title,
                url=url,
                source=source_id,
                author=author,
                cover_url=cover_url,
                rating=rating,
            ))
    
    elif source_id == "shuhaige":
        # Shuhaige uses p.bookname inside li elements
        for item in soup.select("li"):
            # Look for book title in p.bookname
            title_el = item.select_one("p[class*='book'] a")
            if not title_el:
                continue
            
            title = title_el.get_text(strip=True)
            if len(title) < 2 or len(title) > 100:
                continue
                
            url = urljoin(config["base_url"], title_el.get("href", ""))
            
            # Get image from parent li
            cover_el = item.select_one("img")
            cover_url = urljoin(config["base_url"], cover_el.get("src", "") or cover_el.get("data-src", "")) if cover_el else ""
            
            results.append(SearchResult(
                title=title,
                url=url,
                source=source_id,
                cover_url=cover_url,
            ))
    
    elif source_id == "xbiquge":
        for item in soup.select("#maincontent tr, .grid tr, .bookbox"):
            # Try table row format first
            cols = item.find_all("td")
            if len(cols) >= 3:
                title_el = cols[0].find("a")
                if not title_el:
                    continue
                
                title = title_el.get_text(strip=True)
                url = urljoin(config["base_url"], title_el.get("href", ""))
                author = cols[1].get_text(strip=True) if len(cols) > 1 else ""
                latest_chapter = cols[3].get_text(strip=True) if len(cols) > 3 else ""
                
                # Extract cover image from first column if available
                cover_el = cols[0].select_one("img")
                cover_url = urljoin(config["base_url"], cover_el.get("src", "")) if cover_el else ""
                
                results.append(SearchResult(
                    title=title,
                    url=url,
                    source=source_id,
                    author=author,
                    cover_url=cover_url,
                    latest_chapter=latest_chapter,
                ))
            # Try bookbox format (from HTML samples)
            elif item.has_attr('class') and 'bookbox' in item.get('class', []):
                title_el = item.select_one(".bookname a")
                if not title_el:
                    continue
                
                title = title_el.get_text(strip=True)
                url = urljoin(config["base_url"], title_el.get("href", ""))
                
                author_el = item.select_one(".author")
                author = author_el.get_text(strip=True).replace("作者：", "") if author_el else ""
                
                latest_el = item.select_one(".cat a")
                latest_chapter = latest_el.get_text(strip=True) if latest_el else ""
                
                # Extract cover image
                cover_el = item.select_one("img")
                cover_url = urljoin(config["base_url"], cover_el.get("src", "")) if cover_el else ""
                
                results.append(SearchResult(
                    title=title,
                    url=url,
                    source=source_id,
                    author=author,
                    cover_url=cover_url,
                    latest_chapter=latest_chapter,
                ))
    
    elif source_id == "biquge_company":
        for item in soup.select(".bookbox, .bookinfo"):
            title_el = item.select_one(".bookname a")
            if not title_el:
                continue
            
            title = title_el.get_text(strip=True)
            url = urljoin(config["base_url"], title_el.get("href", ""))
            
            author_el = item.select_one(".author")
            author = author_el.get_text(strip=True).replace("作者：", "") if author_el else ""
            
            latest_el = item.select_one(".cat a")
            latest_chapter = latest_el.get_text(strip=True) if latest_el else ""
            
            desc_el = item.select_one(".update")
            description = desc_el.get_text(strip=True) if desc_el else ""
            
            # Extract cover image (biquge.company doesn't have covers in search, but try anyway)
            cover_el = item.select_one("img")
            cover_url = urljoin(config["base_url"], cover_el.get("src", "")) if cover_el else ""
            
            results.append(SearchResult(
                title=title,
                url=url,
                source=source_id,
                author=author,
                description=description,
                cover_url=cover_url,
                latest_chapter=latest_chapter,
            ))
    
    elif source_id == "ttkan":
        # Handle AMP-based search results
        for item in soup.select(".novel_cell, [data-v-2ba0104b] .pure-g > div"):
            title_el = item.select_one("h3 a, .bookname a, a[title]")
            if not title_el:
                # Try finding links with novel-like structure
                links = item.find_all("a", href=True)
                for link in links:
                    href = link.get("href", "")
                    if "/novels/" in href or "/novel/" in href:
                        title_el = link
                        break
            
            if not title_el:
                continue
            
            title = title_el.get_text(strip=True)
            if len(title) < 2:  # Skip very short titles
                continue
                
            url = urljoin(config["base_url"], title_el.get("href", ""))
            
            author_el = item.select_one(".author")
            author = author_el.get_text(strip=True) if author_el else ""
            
            # Extract cover image
            cover_el = item.select_one("img.book-cover, img.cover, .cover img")
            cover_url = urljoin(config["base_url"], cover_el.get("src", "")) if cover_el else ""
            
            # Extract rating if available
            rating_el = item.select_one(".rating, .score, .stars")
            rating = rating_el.get_text(strip=True) if rating_el else ""
            
            results.append(SearchResult(
                title=title,
                url=url,
                source=source_id,
                author=author,
                cover_url=cover_url,
                rating=rating,
            ))
    
    elif source_id == "shuhaige":
        for item in soup.select(".list li, .book-item, .search-result"):
            title_el = item.select_one(".bookname a, h3 a, .book-title a")
            if not title_el:
                continue
            
            title = title_el.get_text(strip=True)
            url = urljoin(config["base_url"], title_el.get("href", ""))
            
            author_el = item.select_one(".data a, .author")
            author = author_el.get_text(strip=True) if author_el else ""
            
            latest_el = item.select_one(".data a:last-child")
            latest_chapter = latest_el.get_text(strip=True) if latest_el else ""
            
            # Extract cover image
            cover_el = item.select_one("img.book-cover, img.cover, .cover img")
            cover_url = urljoin(config["base_url"], cover_el.get("src", "")) if cover_el else ""
            
            results.append(SearchResult(
                title=title,
                url=url,
                source=source_id,
                author=author,
                cover_url=cover_url,
                latest_chapter=latest_chapter,
            ))
    
    else:
        # Generic fallback parsing
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if any(pattern in href for pattern in ["/book/", "/novel/", "/read/"]):
                title = link.get_text(strip=True)
                if len(title) > 5 and len(title) < 100:
                    url = urljoin(config["base_url"], href)
                    results.append(SearchResult(
                        title=title,
                        url=url,
                        source=source_id,
                    ))
    
    return results


def search_google(query: str, num_results: int = 10) -> List[SearchResult]:
    """Search Google for novel sources (using a simple approach)."""
    # Note: For production use, consider using the Custom Search JSON API
    # This is a simplified version using direct search
    
    results = []
    search_query = f"{query} 小说 site:ixdzs8.com OR site:xbiquge.info OR site:biquge.company OR site:ttkan.co OR site:shuhaige.net"
    
    # Use a search engine that allows scraping (or implement proper API)
    # For now, we'll search each source individually
    print("Searching across all sources...", file=sys.stderr)
    
    for source_id in SOURCES.keys():
        source_results = search_source(source_id, query)
        results.extend(source_results)
        time.sleep(0.5)  # Be respectful to servers
    
    return results


def search_novel(query: str, sources: Optional[List[str]] = None) -> List[SearchResult]:
    """
    Search for novels across multiple sources.
    
    Args:
        query: Search query (novel title)
        sources: List of source IDs to search, or None for all sources
    
    Returns:
        List of SearchResult objects
    """
    all_results = []
    
    if sources is None:
        sources = list(SOURCES.keys())
    
    for source_id in sources:
        print(f"Searching {source_id}...", file=sys.stderr)
        try:
            results = search_source(source_id, query)
            all_results.extend(results)
            time.sleep(0.3)  # Rate limiting
        except Exception as e:
            print(f"Error searching {source_id}: {e}", file=sys.stderr)
    
    # Remove duplicates by URL
    seen_urls = set()
    unique_results = []
    for result in all_results:
        if result.url not in seen_urls:
            seen_urls.add(result.url)
            unique_results.append(result)
    
    # Sort by relevance (title match quality)
    query_lower = query.lower()
    def relevance_score(r: SearchResult) -> float:
        title_lower = r.title.lower()
        if query_lower in title_lower:
            return 1.0 - abs(len(title_lower) - len(query_lower)) / max(len(title_lower), len(query_lower))
        return 0.5
    
    unique_results.sort(key=relevance_score, reverse=True)
    
    return unique_results


# ============================================================================
# Chapter List Extraction
# ============================================================================

def handle_expand_button(soup: BeautifulSoup, config: Dict, novel_url: str = "") -> BeautifulSoup:
    """Handle sites with expand buttons for chapter lists."""
    if not config.get("has_expand"):
        return soup
    
    # For JavaScript-heavy sites, we may need to fetch the expanded content directly
    # Some sites load all chapters via AJAX when button is clicked
    
    expand_selector = config.get("expand_button_selector", "")
    source_id = config.get("name", "")
    
    # Special handling for ixdzs8 - fetch chapters via AJAX
    if source_id == "ixdzs8":
        # Extract book ID from URL
        import re
        bid_match = re.search(r'/read/(\d+)/', novel_url)
        if bid_match:
            bid = bid_match.group(1)
            ajax_url = "/novel/clist/"
            base_url = config["base_url"]
            full_url = urljoin(base_url, ajax_url)
            
            # Fetch chapter list via AJAX
            try:
                import json as json_module
                ajax_response = fetch_url(full_url, method="POST", data={"bid": bid})
                if ajax_response:
                    try:
                        data = json_module.loads(ajax_response)
                        if data.get("rs") == 200 and "data" in data:
                            # Build HTML from JSON response
                            clist_html = "<ul>"
                            for ch in data["data"]:
                                ordernum = ch.get("ordernum", "")
                                title = ch.get("title", "")
                                clist_html += f'<li><a href="/read/{bid}/p{ordernum}.html">{title}</a></li>'
                            clist_html += "</ul>"
                            return BeautifulSoup(clist_html, "lxml")
                    except Exception:
                        pass
            except Exception:
                pass
    
    if expand_selector:
        # Try to find data attributes or AJAX endpoints
        expand_btn = soup.select_one(expand_selector)
        if expand_btn:
            # Check for data attributes that might contain the full list URL
            ajax_url = expand_btn.get("data-ajax-url") or expand_btn.get("data-url")
            if ajax_url:
                base_url = config["base_url"]
                full_url = urljoin(base_url, ajax_url)
                ajax_html = fetch_url(full_url)
                if ajax_html:
                    return BeautifulSoup(ajax_html, "lxml")
    
    return soup


def extract_chapters_from_page(html: str, url: str, source_id: str) -> List[ChapterInfo]:
    """
    Extract chapter list from a novel info/dir page.
    
    Handles:
    - Latest chapters section (may be duplicated)
    - Full chapter list
    - Different ordering (recent first vs chronological)
    - Duplicate removal
    """
    if source_id not in SOURCES:
        # Try to auto-detect source
        source_id = get_source_from_url(url) or "generic"
    
    config = SOURCES.get(source_id, {})
    base_url = config.get("base_url", urlparse(url)._replace(path='').geturl())
    
    soup = BeautifulSoup(html, "lxml")
    
    # Handle expand button
    if config.get("has_expand"):
        soup = handle_expand_button(soup, config, url)
    
    chapters = []
    chapter_urls_seen = set()
    
    # Source-specific extraction
    if source_id == "ixdzs8":
        # ixdzs8: Latest 12 chapters at top, then full list in /dir
        # The latest chapters are repeated in the full list
        
        # Find all chapter links
        chapter_links = soup.select(".chapter-list a, .dir-con a, ul li a")
        
        for idx, link in enumerate(chapter_links):
            href = link.get("href", "")
            if not href:
                continue
            
            chapter_url = urljoin(base_url, href)
            
            # Skip if we've seen this URL (handles duplicate latest chapters)
            if chapter_url in chapter_urls_seen:
                continue
            chapter_urls_seen.add(chapter_url)
            
            title = link.get_text(strip=True)
            if not title or len(title) < 2:
                continue
            
            chapter_num, volume = extract_chapter_number(title)
            
            chapters.append(ChapterInfo(
                title=title,
                url=chapter_url,
                chapter_number=chapter_num,
                volume=volume,
                original_index=idx,
            ))
    
    elif source_id == "ttkan":
        # ttkan: All chapters are in the page as links with specific pattern
        # Look for all chapter links in the page
        
        chapter_links = soup.select("a[href*='/novel/pagea/']")
        
        for idx, link in enumerate(chapter_links):
            href = link.get("href", "")
            if not href:
                continue
            
            chapter_url = urljoin(base_url, href)
            
            if chapter_url in chapter_urls_seen:
                continue
            chapter_urls_seen.add(chapter_url)
            
            title = link.get_text(strip=True)
            if not title:
                continue
            
            chapter_num, volume = extract_chapter_number(title)
            
            chapters.append(ChapterInfo(
                title=title,
                url=chapter_url,
                chapter_number=chapter_num,
                volume=volume,
                original_index=idx,
            ))
    
    elif source_id == "shuhaige":
        # shuhaige: Has pagination for chapters (50 per page)
        # Need to fetch multiple pages if available
        
        # First extract chapters from current page
        chapter_links = soup.select(".booklist dd a, .chapter-list a, ul li a")
        
        for idx, link in enumerate(chapter_links):
            href = link.get("href", "")
            if not href:
                continue
            
            # Filter out non-chapter links
            if any(x in href.lower() for x in ["login", "register", "search"]):
                continue
            
            chapter_url = urljoin(base_url, href)
            
            if chapter_url in chapter_urls_seen:
                continue
            chapter_urls_seen.add(chapter_url)
            
            title = link.get_text(strip=True)
            if not title or len(title) < 2:
                continue
            
            chapter_num, volume = extract_chapter_number(title)
            
            chapters.append(ChapterInfo(
                title=title,
                url=chapter_url,
                chapter_number=chapter_num,
                volume=volume,
                original_index=idx,
            ))
        
        # Check for pagination and fetch additional pages (limit to avoid timeout)
        if config.get("has_pagination"):
            # For shuhaige, use the select dropdown to get all page URLs
            page_select = soup.select(".pagelist select option")
            if page_select:
                # Limit to first 5 pages to avoid timeout (can be configured)
                max_pages = 5
                page_count = 0
                # Get all page URLs from the select options
                for option in page_select:
                    if page_count >= max_pages:
                        break
                    page_href = option.get("value", "")
                    if not page_href:
                        continue
                    page_url = urljoin(base_url, page_href)
                    if page_url == url:
                        continue
                    # Fetch each page
                    page_html = fetch_url(page_url)
                    if page_html:
                        page_soup = BeautifulSoup(page_html, "lxml")
                        page_chapter_links = page_soup.select(".read li a")
                        for p_idx, link in enumerate(page_chapter_links):
                            p_href = link.get("href", "")
                            if not p_href:
                                continue
                            if any(x in p_href.lower() for x in ["login", "register", "search"]):
                                continue
                            p_chapter_url = urljoin(base_url, p_href)
                            if p_chapter_url in chapter_urls_seen:
                                continue
                            chapter_urls_seen.add(p_chapter_url)
                            p_title = link.get_text(strip=True)
                            if not p_title or len(p_title) < 2:
                                continue
                            p_chapter_num, p_volume = extract_chapter_number(p_title)
                            chapters.append(ChapterInfo(
                                title=p_title,
                                url=p_chapter_url,
                                chapter_number=p_chapter_num,
                                volume=p_volume,
                                original_index=len(chapters),
                            ))
                        page_count += 1
                        time.sleep(0.3)  # Rate limiting
    
    elif source_id == "xbiquge":
        # xbiquge: Standard chapter list in order
        
        chapter_links = soup.select("#list dd a, .chapter-list a")
        
        for idx, link in enumerate(chapter_links):
            href = link.get("href", "")
            if not href:
                continue
            
            chapter_url = urljoin(base_url, href)
            
            if chapter_url in chapter_urls_seen:
                continue
            chapter_urls_seen.add(chapter_url)
            
            title = link.get_text(strip=True)
            if not title:
                continue
            
            chapter_num, volume = extract_chapter_number(title)
            
            chapters.append(ChapterInfo(
                title=title,
                url=chapter_url,
                chapter_number=chapter_num,
                volume=volume,
                original_index=idx,
            ))
    
    else:
        # Generic extraction
        # Look for common chapter list patterns
        chapter_links = soup.select(
            "ul li a, "
            ".chapter-list a, "
            ".book-chapter a, "
            "#chapters a, "
            "[class*='chapter'] a"
        )
        
        for idx, link in enumerate(chapter_links):
            href = link.get("href", "")
            if not href:
                continue
            
            # Filter out non-chapter links
            if any(x in href.lower() for x in ["login", "register", "search", "profile"]):
                continue
            
            chapter_url = urljoin(base_url, href)
            
            if chapter_url in chapter_urls_seen:
                continue
            chapter_urls_seen.add(chapter_url)
            
            title = link.get_text(strip=True)
            if not title or len(title) < 2:
                continue
            
            chapter_num, volume = extract_chapter_number(title)
            
            chapters.append(ChapterInfo(
                title=title,
                url=chapter_url,
                chapter_number=chapter_num,
                volume=volume,
                original_index=idx,
            ))
    
    return chapters


def sort_chapters(chapters: List[ChapterInfo], reverse: bool = False) -> List[ChapterInfo]:
    """
    Sort chapters properly based on chapter numbers.
    
    Handles:
    - Chapters with extracted numbers (sorted numerically)
    - Chapters without numbers (sorted by original index or title)
    - Volumes (sorted by volume then chapter)
    """
    # Separate chapters with and without detected numbers
    numbered = [c for c in chapters if c.chapter_number > 0]
    unnumbered = [c for c in chapters if c.chapter_number == 0]
    
    # Sort numbered chapters by volume then chapter number
    numbered.sort(key=lambda c: (c.volume, c.chapter_number))
    
    # Sort unnumbered chapters by original index (preserve site order)
    # or try to sort by title
    unnumbered.sort(key=lambda c: c.original_index)
    
    # Combine: numbered first, then unnumbered
    if reverse:
        return list(reversed(numbered)) + list(reversed(unnumbered))
    return numbered + unnumbered


def fetch_novel_info(novel_url: str) -> Optional[NovelInfo]:
    """
    Fetch complete novel information including chapter list.
    
    Handles:
    - Info page with basic novel details
    - Chapter list page (/dir or similar)
    - Automatic source detection
    """
    source_id = get_source_from_url(novel_url)
    if not source_id:
        print(f"Could not identify source for URL: {novel_url}", file=sys.stderr)
        return None
    
    config = SOURCES.get(source_id, {})
    base_url = config.get("base_url", "")
    
    # Fetch the main novel page
    html = fetch_url(novel_url)
    if not html:
        return None
    
    soup = BeautifulSoup(html, "lxml")
    
    # Extract novel metadata
    title = ""
    author = ""
    description = ""
    cover_url = ""
    status = ""
    
    # Source-specific metadata extraction
    rating = ""
    word_count = ""
    categories = []
    recommendations = []
    
    if source_id == "ixdzs8":
        title_el = soup.select_one("h1.book-title, h1.title")
        title = title_el.get_text(strip=True) if title_el else ""
        
        author_el = soup.select_one(".author, .book-author")
        author = author_el.get_text(strip=True).replace("作者：", "") if author_el else ""
        
        desc_el = soup.select_one(".intro, .description, .summary")
        description = desc_el.get_text(strip=True) if desc_el else ""
        
        cover_el = soup.select_one(".book-cover img, .cover img")
        cover_url = urljoin(base_url, cover_el.get("src", "")) if cover_el else ""
        
        status_el = soup.select_one(".status, .book-status")
        status = status_el.get_text(strip=True) if status_el else ""
        
        # Extract rating
        rating_el = soup.select_one(".rating, .score, .stars")
        rating = rating_el.get_text(strip=True) if rating_el else ""
        
        # Extract word count
        wc_el = soup.select_one(".word-count, .words")
        word_count = wc_el.get_text(strip=True) if wc_el else ""
        
        # Extract categories/tags
        for cat_el in soup.select(".category a, .tag a, .cate a"):
            cat_text = cat_el.get_text(strip=True)
            if cat_text:
                categories.append(cat_text)
        
        # Extract recommendations (大家还在看 / similar novels)
        rec_section = soup.select_one(".recommendations, .similar-books, .related-novels")
        if not rec_section:
            # Try to find section by heading
            for h in soup.select("h2, h3"):
                if any(x in h.get_text() for x in ["推荐", "在看", "相关", "similar", "recommend"]):
                    rec_section = h.find_next_sibling() or h.parent
                    break
        
        if rec_section:
            for rec_item in rec_section.select("li, .book-item, .novel-item")[:10]:
                rec_title_el = rec_item.select_one("a[title], h3 a, .title a")
                rec_url_el = rec_item.select_one("a[href]")
                if rec_title_el and rec_url_el:
                    rec_title = rec_title_el.get_text(strip=True)
                    rec_href = rec_url_el.get("href", "")
                    if rec_title and rec_href:
                        recommendations.append({
                            "title": rec_title,
                            "url": urljoin(base_url, rec_href),
                        })
    
    elif source_id == "ttkan":
        title_el = soup.select_one("h1.novel-title, h1.title")
        title = title_el.get_text(strip=True) if title_el else ""
        
        author_el = soup.select_one(".author-info")
        author = author_el.get_text(strip=True).replace("作者：", "") if author_el else ""
        
        desc_el = soup.select_one(".novel-intro, .description")
        description = desc_el.get_text(strip=True) if desc_el else ""
        
        # Extract cover image
        cover_el = soup.select_one(".book-cover img, .cover img, img.book-cover")
        cover_url = urljoin(base_url, cover_el.get("src", "")) if cover_el else ""
        
        # Extract rating
        rating_el = soup.select_one(".rating, .score, .stars")
        rating = rating_el.get_text(strip=True) if rating_el else ""
        
        # Extract categories
        for cat_el in soup.select(".category a, .tag a, .cate a"):
            cat_text = cat_el.get_text(strip=True)
            if cat_text:
                categories.append(cat_text)
        
        # Extract recommendations
        rec_section = soup.select_one(".recommendations, .similar-books, .related-novels")
        if not rec_section:
            for h in soup.select("h2, h3"):
                if any(x in h.get_text() for x in ["推荐", "在看", "相关", "similar", "recommend"]):
                    rec_section = h.find_next_sibling() or h.parent
                    break
        
        if rec_section:
            for rec_item in rec_section.select("li, .book-item, .novel-item")[:10]:
                rec_title_el = rec_item.select_one("a[title], h3 a, .title a")
                rec_url_el = rec_item.select_one("a[href]")
                if rec_title_el and rec_url_el:
                    rec_title = rec_title_el.get_text(strip=True)
                    rec_href = rec_url_el.get("href", "")
                    if rec_title and rec_href:
                        recommendations.append({
                            "title": rec_title,
                            "url": urljoin(base_url, rec_href),
                        })
    
    elif source_id == "xbiquge":
        title_el = soup.select_one("#info h1")
        title = title_el.get_text(strip=True) if title_el else ""
        
        # Author is usually in #info p
        for p in soup.select("#info p"):
            text = p.get_text(strip=True)
            if "作者：" in text:
                author = text.replace("作者：", "").strip()
            elif "状态：" in text:
                status = text.replace("状态：", "").strip()
        
        desc_el = soup.select_one("#intro")
        description = desc_el.get_text(strip=True) if desc_el else ""
        
        cover_el = soup.select_one("#fmimg img")
        cover_url = urljoin(base_url, cover_el.get("src", "")) if cover_el else ""
        
        # Extract rating if available
        rating_el = soup.select_one(".rating, .score, .stars")
        rating = rating_el.get_text(strip=True) if rating_el else ""
        
        # Extract categories
        for cat_el in soup.select(".category a, .tag a"):
            cat_text = cat_el.get_text(strip=True)
            if cat_text:
                categories.append(cat_text)
        
        # Extract recommendations
        rec_section = soup.select_one(".recommendations, .similar-books, .related-novels")
        if not rec_section:
            for h in soup.select("h2, h3"):
                if any(x in h.get_text() for x in ["推荐", "在看", "相关", "similar", "recommend"]):
                    rec_section = h.find_next_sibling() or h.parent
                    break
        
        if rec_section:
            for rec_item in rec_section.select("li, .book-item, .novel-item")[:10]:
                rec_title_el = rec_item.select_one("a[title], h3 a, .title a")
                rec_url_el = rec_item.select_one("a[href]")
                if rec_title_el and rec_url_el:
                    rec_title = rec_title_el.get_text(strip=True)
                    rec_href = rec_url_el.get("href", "")
                    if rec_title and rec_href:
                        recommendations.append({
                            "title": rec_title,
                            "url": urljoin(base_url, rec_href),
                        })
    
    elif source_id == "biquge_company":
        title_el = soup.select_one("h1.book-title, h1.title")
        title = title_el.get_text(strip=True) if title_el else ""
        
        author_el = soup.select_one(".author, .book-author")
        author = author_el.get_text(strip=True).replace("作者：", "") if author_el else ""
        
        desc_el = soup.select_one(".intro, .description, .summary")
        description = desc_el.get_text(strip=True) if desc_el else ""
        
        # biquge.company doesn't have cover images typically
        cover_el = soup.select_one(".book-cover img, .cover img")
        cover_url = urljoin(base_url, cover_el.get("src", "")) if cover_el else ""
        
        status_el = soup.select_one(".status, .book-status")
        status = status_el.get_text(strip=True) if status_el else ""
        
        # Extract rating
        rating_el = soup.select_one(".rating, .score, .stars")
        rating = rating_el.get_text(strip=True) if rating_el else ""
        
        # Extract word count
        wc_el = soup.select_one(".word-count, .words")
        word_count = wc_el.get_text(strip=True) if wc_el else ""
        
        # Extract categories
        for cat_el in soup.select(".category a, .tag a, .cate a"):
            cat_text = cat_el.get_text(strip=True)
            if cat_text:
                categories.append(cat_text)
        
        # Extract recommendations
        rec_section = soup.select_one(".recommendations, .similar-books, .related-novels")
        if not rec_section:
            for h in soup.select("h2, h3"):
                if any(x in h.get_text() for x in ["推荐", "在看", "相关", "similar", "recommend"]):
                    rec_section = h.find_next_sibling() or h.parent
                    break
        
        if rec_section:
            for rec_item in rec_section.select("li, .book-item, .novel-item")[:10]:
                rec_title_el = rec_item.select_one("a[title], h3 a, .title a")
                rec_url_el = rec_item.select_one("a[href]")
                if rec_title_el and rec_url_el:
                    rec_title = rec_title_el.get_text(strip=True)
                    rec_href = rec_url_el.get("href", "")
                    if rec_title and rec_href:
                        recommendations.append({
                            "title": rec_title,
                            "url": urljoin(base_url, rec_href),
                        })
    
    elif source_id == "shuhaige":
        title_el = soup.select_one("h1.book-title, h1.title")
        title = title_el.get_text(strip=True) if title_el else ""
        
        author_el = soup.select_one(".author, .book-author")
        author = author_el.get_text(strip=True).replace("作者：", "") if author_el else ""
        
        desc_el = soup.select_one(".intro, .description, .summary")
        description = desc_el.get_text(strip=True) if desc_el else ""
        
        cover_el = soup.select_one(".book-cover img, .cover img")
        cover_url = urljoin(base_url, cover_el.get("src", "")) if cover_el else ""
        
        status_el = soup.select_one(".status, .book-status")
        status = status_el.get_text(strip=True) if status_el else ""
        
        # Extract rating
        rating_el = soup.select_one(".rating, .score, .stars")
        rating = rating_el.get_text(strip=True) if rating_el else ""
        
        # Extract word count
        wc_el = soup.select_one(".word-count, .words")
        word_count = wc_el.get_text(strip=True) if wc_el else ""
        
        # Extract categories
        for cat_el in soup.select(".category a, .tag a, .cate a"):
            cat_text = cat_el.get_text(strip=True)
            if cat_text:
                categories.append(cat_text)
        
        # Extract recommendations
        rec_section = soup.select_one(".recommendations, .similar-books, .related-novels")
        if not rec_section:
            for h in soup.select("h2, h3"):
                if any(x in h.get_text() for x in ["推荐", "在看", "相关", "similar", "recommend"]):
                    rec_section = h.find_next_sibling() or h.parent
                    break
        
        if rec_section:
            for rec_item in rec_section.select("li, .book-item, .novel-item")[:10]:
                rec_title_el = rec_item.select_one("a[title], h3 a, .title a")
                rec_url_el = rec_item.select_one("a[href]")
                if rec_title_el and rec_url_el:
                    rec_title = rec_title_el.get_text(strip=True)
                    rec_href = rec_url_el.get("href", "")
                    if rec_title and rec_href:
                        recommendations.append({
                            "title": rec_title,
                            "url": urljoin(base_url, rec_href),
                        })
    
    # If title still empty, try generic extraction
    if not title:
        title_el = soup.select_one("h1")
        title = title_el.get_text(strip=True) if title_el else "Unknown Novel"
    
    # Extract chapters
    chapters = extract_chapters_from_page(html, novel_url, source_id)
    
    # Check if we need to fetch a separate chapter list page
    if len(chapters) < 10 and config.get("chapter_list_pattern"):
        # Try to find and fetch the chapter list page
        dir_link = soup.select_one(f"a[href*='/dir'], a[href*='/chapters'], a:contains('目录')")
        if dir_link:
            dir_url = urljoin(base_url, dir_link.get("href", ""))
            dir_html = fetch_url(dir_url)
            if dir_html:
                dir_chapters = extract_chapters_from_page(dir_html, dir_url, source_id)
                if len(dir_chapters) > len(chapters):
                    chapters = dir_chapters
    
    # Sort chapters properly
    sorted_chapters = sort_chapters(chapters)
    
    # Remove duplicates that might have slipped through
    seen_urls = set()
    unique_chapters = []
    for chapter in sorted_chapters:
        if chapter.url not in seen_urls:
            seen_urls.add(chapter.url)
            unique_chapters.append(chapter)
    
    return NovelInfo(
        title=title,
        url=novel_url,
        source=source_id,
        author=author,
        description=description,
        cover_url=cover_url,
        status=status,
        chapters=unique_chapters,
        total_chapters=len(unique_chapters),
        rating=rating,
        word_count=word_count,
        recommendations=recommendations,
        categories=categories,
    )


# ============================================================================
# Chapter Content Extraction
# ============================================================================

def extract_chapter_content(chapter_url: str) -> Optional[Dict[str, Any]]:
    """
    Extract the actual content of a chapter.
    
    Uses the existing novel_extractor.py if available,
    otherwise falls back to basic extraction.
    Special handling for ixdzs8.com with challenge token resolution.
    """
    source_id = get_source_from_url(chapter_url)
    config = SOURCES.get(source_id, {})
    
    # Special handling for ixdzs8.com - resolve challenge token first
    html = None
    if source_id == "ixdzs8":
        html = fetch_ixdzs8_with_challenge(chapter_url)
    
    if not html:
        html = fetch_url(chapter_url)
    
    if not html:
        return None
    
    # Use the existing novel_extractor if available
    if extract_chapter:
        result = extract_chapter(html, url=chapter_url)
        if result:
            return {
                "title": result.get("title", ""),
                "content": result.get("content", ""),
                "confidence": result.get("confidence", 0.0),
                "url": chapter_url,
                "source": source_id,
            }
    
    # Fallback: basic extraction
    soup = BeautifulSoup(html, "lxml")
    
    # Try to find chapter title
    title_el = soup.select_one("h1, h2, .chapter-title, .title, .page-d-name")
    title = title_el.get_text(strip=True) if title_el else ""
    
    # Try to find chapter content
    content_selectors = [
        ".chapter-content", "#chapter-content", ".content", "#content",
        ".article-content", "#article-content", ".read-content",
        ".page-content section", "[class*='chapter']", "[id*='chapter']",
    ]
    
    content_el = None
    for selector in content_selectors:
        content_el = soup.select_one(selector)
        if content_el:
            break
    
    if content_el:
        # Remove unwanted elements
        for tag in content_el(["script", "style", "div[class*='ad']", ".comment"]):
            tag.decompose()
        
        content = content_el.get_text("\n", strip=True)
    else:
        content = soup.get_text("\n", strip=True)
    
    return {
        "title": title,
        "content": content[:10000],  # Limit content length
        "confidence": 0.5,
        "url": chapter_url,
        "source": source_id,
    }


def fetch_ixdzs8_with_challenge(url: str, max_attempts: int = 3) -> Optional[str]:
    """
    Fetch ixdzs8.com URL by resolving the challenge token.
    
    The site uses a JavaScript-based challenge that redirects with a token.
    We need to extract the token and follow the redirect manually.
    
    Args:
        url: The URL to fetch
        max_attempts: Maximum number of challenge attempts
    
    Returns:
        HTML content or None if failed
    """
    import re
    
    headers = DEFAULT_HEADERS.copy()
    headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    headers["Accept-Language"] = "zh-CN,zh;q=0.9,en;q=0.8"
    
    try:
        session = requests.Session()
        
        for attempt in range(max_attempts):
            # First request - get challenge page
            response = session.get(url, headers=headers, timeout=30, allow_redirects=False)
            
            # Check if we got the actual content (no challenge)
            if response.status_code == 200 and "正在验证浏览器" not in response.text:
                response.encoding = response.apparent_encoding
                return response.text
            
            # Extract challenge token from JavaScript
            token_match = re.search(r'let\s+token\s*=\s*"([^"]+)"', response.text)
            if not token_match:
                # Maybe already have content
                if len(response.text) > 5000:
                    response.encoding = response.apparent_encoding
                    return response.text
                return None
            
            token = token_match.group(1)
            
            # Build challenge URL
            from urllib.parse import urlparse, parse_qs, urlencode
            parsed = urlparse(url)
            path = parsed.path
            
            # Make second request with token
            challenge_url = f"https://ixdzs8.com{path}?challenge={token}"
            response = session.get(challenge_url, headers=headers, timeout=30, allow_redirects=True)
            
            if response.status_code == 200 and "正在验证浏览器" not in response.text:
                response.encoding = response.apparent_encoding
                return response.text
            
            # If still challenged, the token might have changed - try again
            time.sleep(0.5 * (attempt + 1))
        
        return None
        
    except Exception as e:
        print(f"Error fetching ixdzs8 with challenge: {e}", file=sys.stderr)
        return None


# ============================================================================
# Interactive CLI
# ============================================================================

def display_search_results(results: List[SearchResult], separate: bool = False):
    """Display search results in a formatted way."""
    if not results:
        print("No results found.")
        return
    
    if separate:
        # Group by source
        from collections import defaultdict
        by_source = defaultdict(list)
        for result in results:
            by_source[result.source].append(result)
        
        for source_id, source_results in sorted(by_source.items()):
            print(f"\n{'='*80}")
            print(f"Source: {source_id} ({len(source_results)} results)")
            print(f"{'='*80}")
            for i, result in enumerate(source_results, 1):
                print(f"\n[{i}] {result.title}")
                print(f"    URL: {result.url}")
                if result.cover_url:
                    print(f"    Cover: {result.cover_url}")
                if result.author:
                    print(f"    Author: {result.author}")
                if result.rating:
                    print(f"    Rating: {result.rating}")
                if result.latest_chapter:
                    print(f"    Latest: {result.latest_chapter}")
                if result.description:
                    desc = result.description[:100] + "..." if len(result.description) > 100 else result.description
                    print(f"    Description: {desc}")
    else:
        print(f"\n{'='*80}")
        print(f"Found {len(results)} results:\n")
        
        for i, result in enumerate(results, 1):
            print(f"[{i}] {result.title}")
            print(f"    Source: {result.source}")
            print(f"    URL: {result.url}")
            if result.cover_url:
                print(f"    Cover: {result.cover_url}")
            if result.author:
                print(f"    Author: {result.author}")
            if result.rating:
                print(f"    Rating: {result.rating}")
            if result.latest_chapter:
                print(f"    Latest: {result.latest_chapter}")
            if result.description:
                desc = result.description[:100] + "..." if len(result.description) > 100 else result.description
                print(f"    Description: {desc}")
            print()


def display_feed_results(results: List[SearchResult]):
    """Display home feed results with cover images."""
    if not results:
        print("No results found.")
        return
    
    print(f"\n{'='*80}")
    print(f"Home Feed - {len(results)} popular novels:\n")
    
    for i, result in enumerate(results, 1):
        print(f"[{i}] {result.title}")
        print(f"    Source: {result.source}")
        print(f"    URL: {result.url}")
        if result.cover_url:
            print(f"    📚 Cover: {result.cover_url}")
        if result.author:
            print(f"    ✍️  Author: {result.author}")
        if result.rating:
            print(f"    ⭐ Rating: {result.rating}")
        if result.latest_chapter:
            print(f"    📖 Latest: {result.latest_chapter}")
        if result.description:
            desc = result.description[:100] + "..." if len(result.description) > 100 else result.description
            print(f"    📝 Description: {desc}")
        print()


def display_chapter_list(novel_info: NovelInfo, show_all: bool = False, limit: int = 50):
    """Display chapter list with full novel info including recommendations."""
    print(f"\n{'='*80}")
    print(f"Novel: {novel_info.title}")
    print(f"Author: {novel_info.author}")
    print(f"Source: {novel_info.source}")
    print(f"Total Chapters: {novel_info.total_chapters}")
    if novel_info.cover_url:
        print(f"Cover URL: {novel_info.cover_url}")
    if novel_info.status:
        print(f"Status: {novel_info.status}")
    if novel_info.rating:
        print(f"Rating: {novel_info.rating}")
    if novel_info.word_count:
        print(f"Word Count: {novel_info.word_count}")
    if novel_info.categories:
        print(f"Categories: {', '.join(novel_info.categories)}")
    if novel_info.description:
        print(f"\nDescription:\n{novel_info.description}")
    
    # Display recommendations (大家还在看 / similar novels)
    if novel_info.recommendations:
        print(f"\nRecommendations (大家还在看):")
        print(f"{'-'*40}")
        for i, rec in enumerate(novel_info.recommendations[:10], 1):
            print(f"  {i}. {rec.get('title', 'Unknown')}")
            print(f"     URL: {rec.get('url', '')}")
    
    print(f"\nChapter List:")
    print(f"{'-'*80}")
    
    chapters_to_show = novel_info.chapters
    if not show_all and len(chapters_to_show) > limit:
        chapters_to_show = chapters_to_show[:limit]
        print(f"(Showing first {limit} chapters, use --all to show all)")
    
    for i, chapter in enumerate(chapters_to_show, 1):
        vol_prefix = f"[Vol.{chapter.volume}] " if chapter.volume > 0 else ""
        print(f"{i:4d}. {vol_prefix}{chapter.title}")
        print(f"      URL: {chapter.url}")
    
    if len(chapters_to_show) < len(novel_info.chapters):
        print(f"... and {len(novel_info.chapters) - len(chapters_to_show)} more chapters")


def interactive_mode():
    """Run in interactive mode."""
    print("="*80)
    print("Universal Novel Scraper - Interactive Mode")
    print("="*80)
    print("\nCommands:")
    print("  search <query>     - Search for novels")
    print("  info <url>         - Get novel info and chapter list")
    print("  chapter <url>      - Extract chapter content")
    print("  export <url>       - Export all chapters to files")
    print("  quit               - Exit program")
    print()
    
    while True:
        try:
            cmd = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break
        
        if not cmd:
            continue
        
        parts = cmd.split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        
        if command in ("quit", "exit", "q"):
            print("Goodbye!")
            break
        
        elif command == "search" and arg:
            print(f"Searching for: {arg}")
            results = search_novel(arg)
            display_search_results(results)
        
        elif command == "info" and arg:
            print(f"Fetching novel info: {arg}")
            novel_info = fetch_novel_info(arg)
            if novel_info:
                display_chapter_list(novel_info, show_all=False)
            else:
                print("Failed to fetch novel info.")
        
        elif command == "chapter" and arg:
            print(f"Extracting chapter: {arg}")
            content = extract_chapter_content(arg)
            if content:
                print(f"\nTitle: {content['title']}")
                print(f"Confidence: {content['confidence']:.2f}")
                print(f"\nContent:\n{content['content'][:500]}...")
            else:
                print("Failed to extract chapter.")
        
        elif command == "export" and arg:
            print(f"Exporting all chapters from: {arg}")
            novel_info = fetch_novel_info(arg)
            if novel_info:
                output_dir = Path(f"./{novel_info.title}_chapters")
                output_dir.mkdir(exist_ok=True)
                
                print(f"Exporting {novel_info.total_chapters} chapters to {output_dir}")
                
                for i, chapter in enumerate(novel_info.chapters, 1):
                    print(f"  [{i}/{novel_info.total_chapters}] {chapter.title}")
                    content = extract_chapter_content(chapter.url)
                    if content:
                        filename = output_dir / f"{i:04d}_{chapter.title}.txt"
                        # Sanitize filename
                        filename = Path(str(filename).replace("/", "_").replace("\\", "_"))
                        try:
                            with open(filename, "w", encoding="utf-8") as f:
                                f.write(f"Title: {content['title']}\n\n")
                                f.write(content['content'])
                        except Exception as e:
                            print(f"    Error saving: {e}")
                    time.sleep(0.5)  # Rate limiting
                
                print(f"\nExport complete! Files saved to: {output_dir}")
            else:
                print("Failed to fetch novel info.")
        
        else:
            print("Unknown command. Available commands: search, info, chapter, export, quit")


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Universal Novel Scraper - Search and extract web novels",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s search "洪荒：我開局打造鴻蒙金榜"
  %(prog)s chapters https://ixdzs8.com/book/123/dir
  %(prog)s extract https://ixdzs8.com/book/123/chapter-1
  %(prog)s feed ixdzs8
  %(prog)s interactive
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Search command
    search_parser = subparsers.add_parser("search", help="Search for novels")
    search_parser.add_argument("query", help="Search query (novel title)")
    search_parser.add_argument("--sources", nargs="+", choices=list(SOURCES.keys()),
                               help="Specific sources to search")
    search_parser.add_argument("--json", action="store_true", help="Output as JSON")
    search_parser.add_argument("--sep", action="store_true", help="Separate results by source")
    
    # Feed command (home feed / popular novels)
    feed_parser = subparsers.add_parser("feed", help="Get home feed / popular novels")
    feed_parser.add_argument("source", nargs="?", choices=list(SOURCES.keys()), help="Source to get feed from (optional if --all is used)")
    feed_parser.add_argument("--page", type=int, default=1, help="Page number")
    feed_parser.add_argument("--json", action="store_true", help="Output as JSON")
    feed_parser.add_argument("--all", action="store_true", dest="show_all", help="Show all sources combined")
    
    # Chapters command
    chapters_parser = subparsers.add_parser("chapters", help="Get chapter list")
    chapters_parser.add_argument("url", help="Novel URL or info page URL")
    chapters_parser.add_argument("--all", action="store_true", help="Show all chapters")
    chapters_parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    # Extract command
    extract_parser = subparsers.add_parser("extract", help="Extract chapter content")
    extract_parser.add_argument("url", help="Chapter URL")
    extract_parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    # Export command
    export_parser = subparsers.add_parser("export", help="Export all chapters")
    export_parser.add_argument("url", help="Novel URL")
    export_parser.add_argument("--output-dir", "-o", default="./chapters",
                               help="Output directory")
    
    # Interactive command
    subparsers.add_parser("interactive", help="Run in interactive mode")
    
    args = parser.parse_args()
    
    if args.command == "search":
        results = search_novel(args.query, sources=args.sources)
        if args.json:
            print(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2))
        else:
            display_search_results(results, separate=args.sep)
    
    elif args.command == "feed":
        if args.show_all:
            # Get feed from all sources
            all_results = []
            for source_id in SOURCES.keys():
                results = get_home_feed(source_id, page=args.page)
                all_results.extend(results)
            
            if args.json:
                print(json.dumps([r.to_dict() for r in all_results], ensure_ascii=False, indent=2))
            else:
                display_feed_results(all_results)
        else:
            # Get feed from specific source
            results = get_home_feed(args.source, page=args.page)
            if args.json:
                print(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2))
            else:
                display_feed_results(results)
    
    elif args.command == "chapters":
        novel_info = fetch_novel_info(args.url)
        if novel_info:
            if args.json:
                print(json.dumps(novel_info.to_dict(), ensure_ascii=False, indent=2))
            else:
                display_chapter_list(novel_info, show_all=args.all)
        else:
            print("Failed to fetch novel information.", file=sys.stderr)
            sys.exit(1)
    
    elif args.command == "extract":
        content = extract_chapter_content(args.url)
        if content:
            if args.json:
                print(json.dumps(content, ensure_ascii=False, indent=2))
            else:
                print(f"Title: {content['title']}")
                print(f"Source: {content['source']}")
                print(f"Confidence: {content['confidence']:.2f}")
                print(f"\n{content['content']}")
        else:
            print("Failed to extract chapter content.", file=sys.stderr)
            sys.exit(1)
    
    elif args.command == "export":
        novel_info = fetch_novel_info(args.url)
        if not novel_info:
            print("Failed to fetch novel information.", file=sys.stderr)
            sys.exit(1)
        
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Sanitize novel title for directory name
        safe_title = re.sub(r'[<>:"/\\|？*]', '_', novel_info.title)[:50]
        novel_dir = output_dir / f"{safe_title}_{novel_info.source}"
        novel_dir.mkdir(exist_ok=True)
        
        print(f"Exporting {novel_info.total_chapters} chapters to {novel_dir}")
        
        success_count = 0
        for i, chapter in enumerate(novel_info.chapters, 1):
            print(f"  [{i:4d}/{novel_info.total_chapters}] {chapter.title}")
            
            content = extract_chapter_content(chapter.url)
            if content:
                # Create safe filename
                safe_chapter_title = re.sub(r'[<>:"/\\|？*]', '_', chapter.title)[:100]
                filename = novel_dir / f"{i:04d}_{safe_chapter_title}.txt"
                
                try:
                    with open(filename, "w", encoding="utf-8") as f:
                        f.write(f"Title: {content['title']}\n")
                        f.write(f"URL: {content['url']}\n")
                        f.write(f"Source: {content['source']}\n\n")
                        f.write(content['content'])
                    success_count += 1
                except Exception as e:
                    print(f"    Error saving: {e}", file=sys.stderr)
            
            time.sleep(0.3)  # Rate limiting
        
        print(f"\nExport complete! {success_count}/{novel_info.total_chapters} chapters saved to: {novel_dir}")
    
    elif args.command == "interactive":
        interactive_mode()
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
