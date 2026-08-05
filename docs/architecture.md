# Architecture

## Overview
The Universal Novel Scraper is built on a modular architecture that separates concerns between HTTP request handling, HTML parsing, data extraction, and CLI interaction.

## Core Components

### 1. Bypasser (`bypasser.py`)
The `Bypasser` class handles all HTTP requests with built-in anti-bot bypass capabilities.

**Key Features:**
- **Multi-tier Request System**: Attempts different request strategies (Tier 1, Tier 2, Tier 3) based on challenge detection
- **JavaScript Challenge Detection**: Identifies Cloudflare-style JS challenges by looking for token patterns
- **Automatic Token Extraction**: Extracts challenge tokens from JavaScript and re-requests with proper parameters
- **Session Management**: Maintains cookies and headers across requests
- **User-Agent Rotation**: Uses realistic browser user agents to avoid detection

**Request Flow:**
```
User Request → _tier1_request() → Check for JS Challenge
                                      ↓ (if challenge detected)
                              Extract token from JS
                                      ↓
                              Re-request with ?challenge=<token>
                                      ↓
                              Return clean HTML
```

### 2. Extractor System (`extractors/`)
Each website has its own extractor class that inherits from `BaseExtractor`.

**BaseExtractor Interface:**
```python
class BaseExtractor(ABC):
    @abstractmethod
    def extract_chapter(self, html: str, url: str) -> ChapterResult
    @abstractmethod
    def search(self, query: str) -> List[SearchResult]
    @abstractmethod
    def get_home_feed(self, page: int = 1) -> List[SearchResult]
    @abstractmethod
    def get_novel_info(self, novel_url: str) -> NovelInfo
```

**Extractor Responsibilities:**
- Parse HTML using BeautifulSoup/CSS selectors
- Extract chapter title and content
- Clean text (remove ads, navigation, etc.)
- Calculate confidence scores based on content quality
- Extract metadata (cover images, author, status, etc.)

### 3. Data Models (`models.py`)
Structured data classes for consistent output:

- **ChapterResult**: Title, content, confidence score, URL, source
- **SearchResult**: Title, URL, cover image, latest chapter, source
- **NovelInfo**: Complete novel metadata including description, author, status, chapters list

### 4. CLI Interface (`universal_novel_scraper.py`)
Command-line interface using argparse:

**Commands:**
- `extract <url>` - Extract chapter content
- `search <query>` - Search across sources
- `feed [source]` - Get home feed/recommendations
- `info <url>` - Get novel details

**Flags:**
- `--json` - Output as JSON
- `--all` - Query all sources (search/feed)
- `--sep` - Separate results by source
- `--page` - Pagination support

## Data Flow

```
┌─────────────┐
│   CLI       │
│  Command    │
└──────┬──────┘
       │
       ▼
┌─────────────┐     ┌──────────────┐
│  Dispatcher │────▶│   Bypasser   │
│  (select    │     │  (HTTP +     │
│  extractor) │     │  Bypass)     │
└──────┬──────┘     └──────┬───────┘
       │                   │
       │                   ▼
       │            ┌──────────────┐
       │            │  Raw HTML    │
       │            └──────┬───────┘
       │                   │
       ▼                   │
┌─────────────┐            │
│  Extractor  │◀───────────┘
│  (parse &   │
│  extract)   │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Structured │
│  Result     │
│  (JSON/Text)│
└─────────────┘
```

## Supported Sources

| Source | Base URL | Feed | Search | Chapters | Covers |
|--------|----------|------|--------|----------|--------|
| ixdzs8 | https://ixdzs8.com | ✅ `/hot/day/` | ✅ | ✅ | ✅ |
| shuhaige | https://shuhaige.net | ✅ `/shuku/` | ✅ | ✅ | ✅ |
| biquge.company | https://www.biquge.company | ✅ `/sort/0/` | ✅ | ✅ | ✅ |
| ttkan | https://www.ttkan.co | ✅ `/novel/rank` | ✅ | ✅ | ✅ |
| xbiquge | https://www.xbiquge.info | ✅ `/top/` | ✅ | ✅ | ✅ |

## Extension Points

### Adding a New Source
1. Create new file in `extractors/` (e.g., `newsite.py`)
2. Implement `BaseExtractor` interface
3. Register in main dispatcher
4. Add to documentation

### Custom Headers/User-Agents
Modify `Bypasser._get_headers()` to add custom headers for specific sites.

### Confidence Scoring
Adjust extraction logic to improve confidence scores based on:
- Content length
- Paragraph count
- Chinese character ratio
- Absence of noise keywords
