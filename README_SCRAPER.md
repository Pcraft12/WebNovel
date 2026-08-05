# Universal Novel Scraper Platform

A comprehensive web scraping platform for Chinese web novels with intelligent chapter extraction and sorting.

## Overview

This platform extends the existing `novel_extractor.py` (which extracts chapter content from raw HTML) with a complete search, discovery, and chapter management system. It allows users to:

1. **Search** for novels across multiple preferred sources
2. **View** search results with source information
3. **Select** a novel to see its complete chapter list
4. **Extract** individual chapters or export entire novels

## Features

### 1. Multi-Source Search
Searches across preferred novel sources simultaneously:
- https://ixdzs8.com
- https://www.xbiquge.info/
- https://www.biquge.company/
- https://www.ttkan.co/
- https://m.shuhaige.net/

### 2. Intelligent Chapter List Extraction
Handles complex site structures:
- **Latest chapters + full list**: Many sites show 12 recent chapters at the top, then the complete list below (with duplicates)
- **Separate chapter pages**: Some sites have info pages and separate `/dir` pages for chapters
- **Expand buttons**: Sites like ttkan.co and ixdzs8.com require expanding a button to load all chapters
- **Duplicate removal**: Automatically detects and removes duplicate chapter entries

### 3. Smart Chapter Sorting
Properly sorts chapters using:
- Chinese numeral detection (第 X 章 format)
- Roman numeral detection (Chapter IV format)
- Volume-aware sorting (第 X 卷 第 Y 章)
- Preserves original order for unnumbered chapters

### 4. Integration with novel_extractor.py
Uses the existing universal text extractor for clean chapter content extraction, providing:
- Clean chapter titles
- Body text without ads/navigation
- Confidence scores for quality assessment

## Installation

```bash
pip install requests beautifulsoup4 lxml
```

## Usage

### Search for Novels

```bash
# Search across all sources
python universal_novel_scraper.py search "洪荒：我開局打造鴻蒙金榜"

# Search specific sources only
python universal_novel_scraper.py search "my novel" --sources ixdzs8 ttkan

# Output as JSON
python universal_novel_scraper.py search "novel title" --json
```

### Get Chapter List

```bash
# Get chapter list from novel URL
python universal_novel_scraper.py chapters "https://ixdzs8.com/book/123"

# Show all chapters (default shows first 50)
python universal_novel_scraper.py chapters "https://ixdzs8.com/book/123" --all

# Output as JSON
python universal_novel_scraper.py chapters "https://ixdzs8.com/book/123" --json
```

### Extract Chapter Content

```bash
# Extract a single chapter
python universal_novel_scraper.py extract "https://ixdzs8.com/book/123/chapter-1"

# Output as JSON
python universal_novel_scraper.py extract "https://ixdzs8.com/book/123/chapter-1" --json
```

### Export Entire Novel

```bash
# Export all chapters to files
python universal_novel_scraper.py export "https://ixdzs8.com/book/123"

# Specify output directory
python universal_novel_scraper.py export "https://ixdzs8.com/book/123" -o ./my_novels
```

### Interactive Mode

```bash
python universal_novel_scraper.py interactive
```

Interactive commands:
- `search <query>` - Search for novels
- `info <url>` - Get novel info and chapter list
- `chapter <url>` - Extract chapter content
- `export <url>` - Export all chapters to files
- `quit` - Exit program

## Architecture

### Data Classes

- **SearchResult**: Represents a novel search result (title, URL, source, author, etc.)
- **ChapterInfo**: Represents a chapter (title, URL, chapter number, volume)
- **NovelInfo**: Complete novel information with sorted chapter list

### Key Functions

#### Search Layer
- `search_novel(query, sources)` - Search across multiple sources
- `search_source(source_id, query)` - Search a specific source
- Source-specific parsers for each supported website

#### Chapter Extraction Layer
- `fetch_novel_info(url)` - Get complete novel info including chapters
- `extract_chapters_from_page(html, url, source_id)` - Parse chapter lists
- `handle_expand_button()` - Handle JavaScript expand functionality
- `sort_chapters()` - Sort chapters by number/volume

#### Content Extraction Layer
- `extract_chapter_content(url)` - Extract clean chapter text
- Integrates with `novel_extractor.extract_chapter()` when available
- Falls back to basic extraction if needed

### Chapter Sorting Algorithm

```python
1. Extract chapter numbers using regex patterns:
   - Chinese: 第 X 章
   - Roman: Chapter IV
   - Volume: 第 X 卷 第 Y 章
   
2. Convert numerals to Arabic numbers:
   - Chinese numerals (一，二，三...) → 1, 2, 3...
   - Roman numerals (I, V, X...) → 1, 5, 10...
   
3. Sort by (volume, chapter_number)
4. Append unnumbered chapters in original order
5. Remove duplicates by URL
```

## Configuration

Edit the `SOURCES` dictionary in the script to customize:

```python
SOURCES = {
    "ixdzs8": {
        "name": "ixdzs8",
        "base_url": "https://ixdzs8.com",
        "search_url": "https://ixdzs8.com/search?q={query}",
        "chapter_list_pattern": r"/book/\d+/dir",
        "has_expand": True,
        "expand_button_selector": ".chapter-expand-btn",
        "latest_chapters_first": False,
        "duplicate_latest_count": 12,
    },
    # ... other sources
}
```

## Rate Limiting

The scraper includes built-in rate limiting:
- 0.3 second delay between source searches
- 0.3 second delay between chapter downloads during export
- Respectful request headers with proper User-Agent

## Error Handling

- Graceful handling of HTTP errors (404, timeouts, etc.)
- Continues searching other sources if one fails
- Reports success/failure counts during export
- Confidence scores for extracted content quality

## Example Workflow

```bash
# Step 1: Search for the novel
$ python universal_novel_scraper.py search "洪荒：我開局打造鴻蒙金榜"

Found 3 results:

[1] 洪荒：我開局打造鴻蒙金榜
    Source: ixdzs8
    URL: https://ixdzs8.com/book/12345
    Author: 某作者
    Latest: 第 500 章 大结局

[2] 洪荒：我開局打造鴻蒙金榜
    Source: ttkan
    URL: https://www.ttkan.co/novels/honghuang-wo-kaiju
    Author: 某作者

# Step 2: Get chapter list
$ python universal_novel_scraper.py chapters "https://ixdzs8.com/book/12345"

Novel: 洪荒：我開局打造鴻蒙金榜
Author: 某作者
Source: ixdzs8
Total Chapters: 500

Chapter List:
--------------------------------------------------------------------------------
   1. 第 1 章 开局
      URL: https://ixdzs8.com/book/12345/chapter-1
   2. 第 2 章 发展
      URL: https://ixdzs8.com/book/12345/chapter-2
...

# Step 3: Export all chapters
$ python universal_novel_scraper.py export "https://ixdzs8.com/book/12345"

Exporting 500 chapters to ./洪荒：我開局打造鴻蒙金榜_ixdzs8
  [0001/0500] 第 1 章 开局
  [0002/0500] 第 2 章 发展
...

Export complete! 500/500 chapters saved to: ./洪荒：我開局打造鴻蒙金榜_ixdzs8
```

## Integration with Existing Tools

This scraper complements the existing `novel_extractor.py`:
- `novel_extractor.py`: Extracts clean text from chapter HTML (content layer)
- `universal_novel_scraper.py`: Searches, discovers, and manages novels (discovery layer)

Together they form a complete pipeline:
```
Search → Select Novel → Get Chapter List → Extract Chapter Content → TTS/Reading
```

## Future Enhancements

Potential improvements:
- Google Custom Search API integration for broader search
- Proxy support for geo-restricted content
- Caching layer to reduce repeated requests
- GUI interface for non-CLI users
- API endpoint for mobile app integration
- Automatic source quality scoring
- Parallel chapter downloading

## License

This tool is for educational purposes. Please respect website terms of service and robots.txt files.
