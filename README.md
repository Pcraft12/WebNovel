# Universal Novel Scraper & Extractor

**Complete web novel scraping platform with Cloudflare bypass, multi-source search, parallel processing, and intelligent chapter extraction.**

## Table of Contents
- [Overview](#overview)
- [Key Features](#key-features)
- [What's New](#whats-new)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Usage](#usage)
  - [Search for Novels](#search-for-novels)
  - [Get Chapter List](#get-chapter-list)
  - [Extract Chapter Content](#extract-chapter-content)
  - [Export All Chapters](#export-all-chapters)
  - [Interactive Mode](#interactive-mode)
- [Cloudflare Bypasser](#cloudflare-bypasser)
- [API Reference](#api-reference)
- [Supported Sources](#supported-sources)
- [Quality of Life Features](#quality-of-life-features)

---

## Overview

This project provides a complete solution for scraping Chinese web novels from multiple sources. It includes:

1. **Universal Novel Scraper** (`universal_novel_scraper.py`) - Search across multiple novel websites, extract chapter lists, and download content
2. **Novel Extractor** (`novel_extractor.py`) - Intelligent chapter content extraction that works across different website layouts
3. **Cloudflare Bypasser** (`bypasser.py`) - 4-tier architecture to bypass Cloudflare protection and other anti-bot measures

---

## Key Features

### Scraper Features
- **Multi-Source Search**: Search across 5+ novel websites simultaneously
- **Parallel Processing**: Concurrent searches for faster results (5x speedup)
- **Intelligent Chapter Sorting**: Automatic detection and sorting by chapter numbers (Chinese & Arabic numerals)
- **Duplicate Removal**: Smart deduplication of chapters across sources
- **Expand Button Handling**: Automatic handling of JavaScript-loaded chapter lists

### Extractor Features
- **Language-Agnostic**: Works equally well with English and Chinese text
- **High Accuracy**: 60-95% confidence scoring for extracted content
- **Clean Output**: Removes ads, navigation, comments, and site chrome
- **Title Detection**: Smart chapter title extraction from multiple sources

### Bypasser Features
- **4-Tier Architecture**: Progressive fallback strategy for maximum success
- **Browser Emulation**: Realistic User-Agent rotation and headers
- **Session Caching**: Cookie replay for faster subsequent requests
- **Rate Limiting**: Built-in delay management to avoid bans
- **Challenge Detection**: Automatic detection of Cloudflare and other protections

---

## What's New

### Latest Updates
1. **☁️ Cloudflare Bypasser Integration** - New `bypasser.py` module with 4-tier architecture
2. **⚡ Parallel Search** - Multi-threaded source searching (5x faster)
3. **🔄 Auto-Retry Logic** - Exponential backoff for failed requests
4. **📊 Better Progress Reporting** - Real-time search status updates
5. **🛡️ Enhanced Headers** - Browser-like header emulation for all requests

---

## Installation

```bash
# Required dependencies
pip install requests beautifulsoup4 lxml

# Optional: Test the bypasser
python bypasser.py --help
```

---

## Quick Start

```bash
# Search for a novel
python universal_novel_scraper.py search "洪荒：我開局打造鴻蒙金榜"

# Get chapter list from a novel URL
python universal_novel_scraper.py chapters "https://ixdzs8.com/book/123/dir"

# Extract a single chapter
python universal_novel_scraper.py extract "https://ixdzs8.com/book/123/chapter/1"

# Export all chapters to files
python universal_novel_scraper.py export "https://ixdzs8.com/book/123/dir" -o ./my_novel

# Interactive mode
python universal_novel_scraper.py interactive
```

---

## Usage

### Search for Novels

Search across all sources in parallel:

```bash
python universal_novel_scraper.py search "novel title"
```

Search specific sources only:

```bash
python universal_novel_scraper.py search "novel title" --sources ixdzs8 xbiquge
```

Output as JSON:

```bash
python universal_novel_scraper.py search "novel title" --json
```

### Get Chapter List

```bash
python universal_novel_scraper.py chapters "https://ixdzs8.com/book/123/dir"
```

Show all chapters (not just first 20):

```bash
python universal_novel_scraper.py chapters "https://ixdzs8.com/book/123/dir" --all
```

### Extract Chapter Content

```bash
python universal_novel_scraper.py extract "https://ixdzs8.com/book/123/chapter/1"
```

Output as JSON:

```bash
python universal_novel_scraper.py extract "https://ixdzs8.com/book/123/chapter/1" --json
```

### Export All Chapters

Export with default directory:

```bash
python universal_novel_scraper.py export "https://ixdzs8.com/book/123/dir"
```

Export to custom directory:

```bash
python universal_novel_scraper.py export "https://ixdzs8.com/book/123/dir" -o ./my_novels
```

### Interactive Mode

```bash
python universal_novel_scraper.py interactive
```

Available commands:
- `search <query>` - Search for novels
- `info <url>` - Get novel info and chapter list
- `chapter <url>` - Extract single chapter
- `export <url>` - Export all chapters
- `quit` - Exit

---

## Cloudflare Bypasser

The bypasser module (`bypasser.py`) provides advanced protection bypass capabilities:

### Basic Usage

```python
from bypasser import fetch, Bypasser

# Simple usage
html = fetch("https://protected-site.com")

# With debug output
html = fetch("https://protected-site.com", debug=True)

# Advanced usage with custom config
bp = Bypasser()
html = bp.fetch("https://protected-site.com", method="GET")

# POST request
result = bp.post("https://protected-site.com/search", {"q": "novel"})
```

### How It Works

The bypasser uses a 4-tier strategy:

1. **Tier 1** (<200ms): Plain HTTP with browser-like headers
2. **Tier 2** (~300ms): Cached session/cookie replay
3. **Tier 3** (3-12s): Retry with exponential backoff and UA rotation
4. **Tier 4**: Best-effort fallback

### API Reference

```python
# Module-level functions
fetch(url, method="GET", data=None, options=None, debug=False) -> str
smart_fetch(url, options=None) -> str
get(url, options=None) -> dict
post(url, data, options=None) -> dict
search(url, data, options=None) -> str
clear_cache()
get_status() -> dict

# Bypasser class
bp = Bypasser(config)
bp.fetch(url, method, data, options) -> str
bp.get(url, options) -> dict
bp.post(url, data, options) -> dict
bp.clear_cache()
bp.get_status() -> dict
```

---

## API Reference

### Search Functions

```python
from universal_novel_scraper import search_novel, SearchResult

# Search all sources in parallel
results: List[SearchResult] = search_novel("novel title")

# Search specific sources sequentially
results = search_novel("novel title", sources=["ixdzs8", "xbiquge"], parallel=False)

# Access result properties
for r in results:
    print(f"Title: {r.title}")
    print(f"URL: {r.url}")
    print(f"Source: {r.source}")
    print(f"Author: {r.author}")
    print(f"Latest: {r.latest_chapter}")
```

### Chapter Extraction

```python
from universal_novel_scraper import fetch_novel_info, extract_chapter_content

# Get novel info with chapters
novel = fetch_novel_info("https://ixdzs8.com/book/123/dir")
print(f"Title: {novel.title}")
print(f"Chapters: {novel.total_chapters}")

# Extract chapter content
content = extract_chapter_content("https://ixdzs8.com/book/123/chapter/1")
print(f"Chapter: {content['title']}")
print(f"Confidence: {content['confidence']}")
print(f"Content: {content['content'][:500]}")
```

### Bypasser Integration

The scraper automatically uses the bypasser when available:

```python
# Automatically enabled if bypasser.py is present
from universal_novel_scraper import fetch_url

# Uses bypasser internally
html = fetch_url("https://protected-site.com")

# Disable bypasser if needed
html = fetch_url("https://site.com", use_bypasser=False)
```

---

## Supported Sources

| Source | Base URL | Search Method | Notes |
|--------|----------|---------------|-------|
| ixdzs8 | https://ixdzs8.com | GET | Has expand button |
| xbiquge | https://www.xbiquge.info | GET | Classic layout |
| biquge.company | https://www.biquge.company | POST | POST search |
| ttkan | https://www.ttkan.co | GET | Modern UI |
| shuhaige | https://m.shuhaige.net | POST | Mobile site |

---

## Quality of Life Features

### Automatic Improvements
1. **Parallel Search**: No more waiting for each source sequentially
2. **Better Error Messages**: Clear feedback on what went wrong
3. **Progress Indicators**: See which sources are being searched
4. **Smart Filename Sanitization**: Safe filenames for exported chapters
5. **Rate Limiting**: Built-in delays to avoid IP bans
6. **Automatic Encoding Detection**: Handles various character encodings
7. **Graceful Fallbacks**: If one source fails, others continue

### CLI Improvements
- Colored output support (when available)
- JSON output option for programmatic use
- Verbose mode for debugging
- Interruptible operations (Ctrl+C)

### Code Quality
- Type hints throughout
- PEP 8 compliant
- Comprehensive docstrings
- Modular architecture

---

## Troubleshooting

### Common Issues

**No results from search:**
- Try different sources with `--sources` flag
- Check if the novel title is correct
- Some sources may be temporarily down

**Cloudflare protection detected:**
- The bypasser should handle this automatically
- Try again after a few seconds (rate limiting)
- Use `--debug` flag to see what's happening

**Chapter extraction has low confidence:**
- This is normal for some site layouts
- The content is still extracted, just with lower certainty
- Check the output manually if confidence < 0.5

---

## License

This project is provided as-is for educational and personal use.

## Credits

- Bypasser inspired by [Parasgaming122/external-sources](https://github.com/Parasgaming122/external-sources/tree/main/bypasser)
- Novel extractor synthesizes best practices from multiple AI-generated scripts
