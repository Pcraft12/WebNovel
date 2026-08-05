# Usage Guide

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd universal_novel_scraper

# Install dependencies
pip install -r requirements.txt
```

## Quick Start

### Extract a Chapter

```bash
# Extract chapter as JSON
python3 universal_novel_scraper.py extract https://ixdzs8.com/read/328181/p2.html --json

# Extract chapter as plain text
python3 universal_novel_scraper.py extract https://ixdzs8.com/read/328181/p2.html
```

**Example Output (JSON):**
```json
{
  "title": "Chapter 1: Rebirth of the Eastern Prince",
  "content": "The primordial world!\n\nA mysterious island deep in the East China Sea...",
  "confidence": 0.95,
  "url": "https://ixdzs8.com/read/328181/p2.html",
  "source": "ixdzs8"
}
```

### Search for Novels

```bash
# Search across all sources
python3 universal_novel_scraper.py search "cultivation" --all

# Search with JSON output
python3 universal_novel_scraper.py search "rebirth" --json

# Search with results separated by source
python3 universal_novel_scraper.py search "xianxia" --sep --json

# Paginate through results
python3 universal_novel_scraper.py search "fantasy" --page 2
```

**Example Output:**
```
📚 Search Results for "cultivation":

[shuhaige] 
├─ 📖 Immortal Cultivation Journey
│  ├─ 🔗 https://shuhaige.net/novel/12345
│  ├─ 🖼️ Cover: https://...
│  └─ 📝 Latest: Chapter 500
│
[ixdzs8]
├─ 📖 Supreme Cultivator
│  ├─ 🔗 https://ixdzs8.com/novel/67890
│  ├─ 🖼️ Cover: https://...
│  └─ 📝 Latest: Chapter 1200
```

### Get Home Feed / Recommendations

```bash
# Get feed from specific source
python3 universal_novel_scraper.py feed ixdzs8

# Get feed from all sources (combined)
python3 universal_novel_scraper.py feed --all

# Get feed with JSON output
python3 universal_novel_scraper.py feed shuhaige --json

# Get feed from specific page
python3 universal_novel_scraper.py feed biquge --page 2 --json
```

**Feed Sources:**
- `ixdzs8` → Hot novels of the day (`/hot/day/`)
- `shuhaige` → Library recommendations (`/shuku/`)
- `biquge` → Sorted novels (`/sort/0/1.html`)
- `ttkan` → Ranked novels (`/novel/rank`)
- `xbiquge` → Weekly top (`/top/week_0_1.html`)

### Get Novel Information

```bash
# Get detailed novel info
python3 universal_novel_scraper.py info https://ixdzs8.com/novel/328181/ --json
```

**Example Info Output:**
```json
{
  "title": "The Eastern King of the Primordial World",
  "author": "Some Author",
  "status": "Ongoing",
  "description": "A story about rebirth in the primordial world...",
  "cover_url": "https://...",
  "latest_chapter": "Chapter 1500",
  "chapters": [
    {"title": "Chapter 1", "url": "..."},
    {"title": "Chapter 2", "url": "..."}
  ]
}
```

## Command Reference

### `extract`
Extract chapter content from a URL.

```bash
python3 universal_novel_scraper.py extract <URL> [--json]
```

| Argument | Description |
|----------|-------------|
| `<URL>` | Chapter URL to extract |
| `--json` | Output as JSON instead of plain text |

### `search`
Search for novels across sources.

```bash
python3 universal_novel_scraper.py search <QUERY> [--all] [--sep] [--json] [--page N]
```

| Argument | Description |
|----------|-------------|
| `<QUERY>` | Search query (novel title, author, keywords) |
| `--all` | Search across all supported sources |
| `--sep` | Separate results by source |
| `--json` | Output as JSON |
| `--page N` | Page number for pagination |

### `feed`
Get home feed / recommendations.

```bash
python3 universal_novel_scraper.py feed [SOURCE] [--all] [--json] [--page N]
```

| Argument | Description |
|----------|-------------|
| `[SOURCE]` | Specific source (ixdzs8, shuhaige, biquge, ttkan, xbiquge) |
| `--all` | Combine feeds from all sources |
| `--json` | Output as JSON |
| `--page N` | Page number for pagination |

### `info`
Get detailed novel information.

```bash
python3 universal_novel_scraper.py info <NOVEL_URL> [--json]
```

| Argument | Description |
|----------|-------------|
| `<NOVEL_URL>` | Novel detail page URL |
| `--json` | Output as JSON |

## Supported Sources

| Source | Base URL | Features |
|--------|----------|----------|
| **ixdzs8** | https://ixdzs8.com | ✅ Feed, ✅ Search, ✅ Chapters, ✅ Covers |
| **shuhaige** | https://shuhaige.net | ✅ Feed, ✅ Search, ✅ Chapters, ✅ Covers |
| **biquge.company** | https://www.biquge.company | ✅ Feed, ✅ Search, ✅ Chapters, ✅ Covers |
| **ttkan** | https://www.ttkan.co | ✅ Feed, ✅ Search, ✅ Chapters, ✅ Covers |
| **xbiquge** | https://www.xbiquge.info | ✅ Feed, ✅ Search, ✅ Chapters, ✅ Covers |

## Tips & Tricks

### 1. Bypass Browser Verification
The scraper automatically handles Cloudflare-style browser verification. If you encounter issues:
```bash
# The bypasser will automatically detect and solve challenges
python3 universal_novel_scraper.py extract <URL> --json
```

### 2. High Confidence Extraction
Check the `confidence` score in JSON output:
- `> 0.8`: High quality extraction
- `0.5 - 0.8`: Moderate quality, may need manual review
- `< 0.5`: Low quality, likely failed extraction

### 3. Batch Processing
Combine with shell scripts for batch operations:
```bash
# Extract multiple chapters
while read url; do
  python3 universal_novel_scraper.py extract "$url" --json >> output.jsonl
done < urls.txt
```

### 4. Filter by Source
Use `--sep` to see which source provides the best results:
```bash
python3 universal_novel_scraper.py search "your query" --sep --json
```

## Troubleshooting

### "正在验证浏览器" (Browser Verification)
✅ **Fixed**: The bypasser now automatically handles JavaScript challenges. No action needed.

### Low Confidence Score
- The chapter might be protected or use unusual formatting
- Try a different source using `--all` flag
- Check if the URL is correct

### No Results in Search
- Try different keywords (Chinese titles work better for Chinese sites)
- Use `--all` to search across all sources
- Check if the website is temporarily down

### Missing Cover Images
- Some sources don't provide cover images on list pages
- Use `info` command to get full novel details including covers

## API-like Usage

For programmatic use, import the modules directly:

```python
from bypasser import Bypasser
from extractors.ixdzs8 import Ixdzs8Extractor

# Initialize
bypasser = Bypasser()
extractor = Ixdzs8Extractor(bypasser)

# Extract chapter
result = extractor.extract_chapter(url="https://ixdzs8.com/read/328181/p2.html")
print(result.title)
print(result.content)

# Search
results = extractor.search("cultivation")
for r in results:
    print(f"{r.title} - {r.url}")

# Get feed
feed = extractor.get_home_feed(page=1)
for item in feed:
    print(f"{item.title} - Cover: {item.cover_url}")
```
