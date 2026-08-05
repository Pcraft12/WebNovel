# Development Guide

## Project Structure

```
universal_novel_scraper/
├── universal_novel_scraper.py    # Main CLI entry point
├── bypasser.py                   # HTTP request handler with anti-bot bypass
├── models.py                     # Data models (ChapterResult, SearchResult, NovelInfo)
├── extractors/
│   ├── __init__.py
│   ├── base.py                   # BaseExtractor abstract class
│   ├── ixdzs8.py                 # ixdzs8.com extractor
│   ├── shuhaige.py               # shuhaige.net extractor
│   ├── biquge_company.py         # biquge.company extractor
│   ├── ttkan.py                  # ttkan.co extractor
│   └── xbiquge.py                # xbiquge.info extractor
├── docs/
│   ├── architecture.md           # System architecture documentation
│   ├── usage.md                  # User guide
│   └── development.md            # This file
└── README.md                     # Main documentation
```

## Adding a New Source

### Step 1: Create Extractor Class

Create a new file in `extractors/` directory:

```python
# extractors/newsite.py
from typing import List, Optional
from bs4 import BeautifulSoup
from .base import BaseExtractor
from models import ChapterResult, SearchResult, NovelInfo

class NewSiteExtractor(BaseExtractor):
    BASE_URL = "https://newsite.com"
    
    def __init__(self, bypasser):
        self.bypasser = bypasser
    
    def extract_chapter(self, html: str, url: str) -> ChapterResult:
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract title
        title_tag = soup.select_one('h1.chapter-title')
        title = title_tag.get_text(strip=True) if title_tag else "Unknown Title"
        
        # Extract content
        content_div = soup.select_one('div.chapter-content')
        paragraphs = content_div.find_all('p') if content_div else []
        
        content_lines = []
        for p in paragraphs:
            text = p.get_text(strip=True)
            if text and len(text) > 5:  # Filter out empty/short lines
                content_lines.append(text)
        
        content = '\n\n'.join(content_lines)
        
        # Calculate confidence
        confidence = self._calculate_confidence(content, len(paragraphs))
        
        return ChapterResult(
            title=title,
            content=content,
            confidence=confidence,
            url=url,
            source=self.source
        )
    
    def search(self, query: str) -> List[SearchResult]:
        search_url = f"{self.BASE_URL}/search?q={query}"
        html = self.bypasser.get(search_url)
        soup = BeautifulSoup(html, 'html.parser')
        
        results = []
        for item in soup.select('div.novel-item'):
            title_tag = item.select_one('a.novel-title')
            cover_img = item.select_one('img.cover')
            latest_tag = item.select_one('span.latest-chapter')
            
            if title_tag:
                results.append(SearchResult(
                    title=title_tag.get_text(strip=True),
                    url=title_tag.get('href'),
                    cover_url=cover_img.get('src') if cover_img else None,
                    latest_chapter=latest_tag.get_text(strip=True) if latest_tag else None,
                    source=self.source
                ))
        
        return results
    
    def get_home_feed(self, page: int = 1) -> List[SearchResult]:
        feed_url = f"{self.BASE_URL}/hot/{page}"
        html = self.bypasser.get(feed_url)
        soup = BeautifulSoup(html, 'html.parser')
        
        results = []
        for item in soup.select('div.recommendation-item'):
            # Similar extraction logic as search
            # ...
            pass
        
        return results
    
    def get_novel_info(self, novel_url: str) -> NovelInfo:
        html = self.bypasser.get(novel_url)
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract all novel metadata
        # ...
        
        return NovelInfo(
            title=title,
            author=author,
            status=status,
            description=description,
            cover_url=cover_url,
            latest_chapter=latest_chapter,
            chapters=chapters_list,
            source=self.source
        )
    
    @property
    def source(self) -> str:
        return "newsite"
```

### Step 2: Register Extractor

In `universal_novel_scraper.py`, add the new extractor to the dispatcher:

```python
from extractors.newsite import NewSiteExtractor

# In the dispatch logic
def get_extractor(source: str, bypasser: Bypasser):
    extractors = {
        'ixdzs8': Ixdzs8Extractor,
        'shuhaige': ShuhaigeExtractor,
        # ...
        'newsite': NewSiteExtractor,  # Add new extractor
    }
    
    extractor_class = extractors.get(source)
    if extractor_class:
        return extractor_class(bypasser)
    return None
```

### Step 3: Update Documentation

Add the new source to:
- `README.md` - Supported sources table
- `docs/usage.md` - Usage examples
- `docs/architecture.md` - Architecture diagram

## Understanding the Bypasser

### How It Works

The `Bypasser` class uses a tiered approach to handle anti-bot measures:

```python
class Bypasser:
    def get(self, url: str) -> str:
        # Try Tier 1 (standard request with good headers)
        html = self._tier1_request(url)
        
        # Check if we hit a JS challenge
        if self._is_js_challenge(html):
            # Extract token from JavaScript
            token = self._extract_token(html)
            
            # Re-request with token
            html = self._tier1_request(f"{url}?challenge={token}")
        
        return html
    
    def _is_js_challenge(self, html: str) -> bool:
        # Look for patterns like: let token = "abc123"
        patterns = [
            r'let\s+token\s*=\s*["\']([^"\']+)["\']',
            r'var\s+challenge\s*=\s*["\']([^"\']+)["\']',
        ]
        for pattern in patterns:
            if re.search(pattern, html):
                return True
        return False
```

### Customizing for Specific Sites

Different sites may need different approaches:

```python
def _get_headers(self, url: str) -> dict:
    base_headers = {
        'User-Agent': self.user_agent,
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8',
    }
    
    # Site-specific headers
    if 'ixdzs8.com' in url:
        base_headers['Referer'] = 'https://ixdzs8.com/'
    
    return base_headers
```

## Testing Extractors

### Manual Testing

```bash
# Test chapter extraction
python3 universal_novel_scraper.py extract <URL> --json | jq '.confidence'

# Test search
python3 universal_novel_scraper.py search "test" --json | jq 'length'

# Test feed
python3 universal_novel_scraper.py feed <source> --json | jq '.[0].cover_url'
```

### Automated Testing

Create test cases in `tests/`:

```python
# tests/test_ixdzs8.py
import unittest
from bypasser import Bypasser
from extractors.ixdzs8 import Ixdzs8Extractor

class TestIxdzs8Extractor(unittest.TestCase):
    def setUp(self):
        self.bypasser = Bypasser()
        self.extractor = Ixdzs8Extractor(self.bypasser)
    
    def test_extract_chapter(self):
        result = self.extractor.extract_chapter(
            url="https://ixdzs8.com/read/328181/p2.html"
        )
        self.assertGreater(result.confidence, 0.5)
        self.assertIn("Chapter", result.title)
    
    def test_search(self):
        results = self.extractor.search("cultivation")
        self.assertGreater(len(results), 0)
    
    def test_get_home_feed(self):
        feed = self.extractor.get_home_feed(page=1)
        self.assertGreater(len(feed), 0)
        # Check cover URLs exist
        for item in feed:
            self.assertIsNotNone(item.cover_url)
```

## Debugging Tips

### Enable Verbose Output

Add debug prints to understand what's happening:

```python
def extract_chapter(self, html: str, url: str) -> ChapterResult:
    print(f"[DEBUG] URL: {url}")
    print(f"[DEBUG] HTML length: {len(html)}")
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Check what selectors match
    title_tag = soup.select_one('h1.chapter-title')
    print(f"[DEBUG] Title tag found: {title_tag is not None}")
    
    # ...
```

### Inspect Raw HTML

Save raw HTML for inspection:

```python
html = self.bypasser.get(url)
with open('/tmp/debug.html', 'w', encoding='utf-8') as f:
    f.write(html)
print(f"Saved HTML to /tmp/debug.html")
```

Then open in browser or use `grep`/`sed` to find patterns.

### Check Confidence Scores

Low confidence often indicates extraction issues:

```python
def _calculate_confidence(self, content: str, paragraph_count: int) -> float:
    score = 0.0
    
    # Length check
    if len(content) > 500:
        score += 0.3
    elif len(content) > 200:
        score += 0.2
    
    # Paragraph count
    if paragraph_count > 5:
        score += 0.3
    
    # Chinese character ratio (for Chinese novels)
    chinese_chars = sum(1 for c in content if '\u4e00' <= c <= '\u9fff')
    if len(content) > 0:
        ratio = chinese_chars / len(content)
        score += ratio * 0.4
    
    print(f"[CONFIDENCE] Length: {len(content)}, Paragraphs: {paragraph_count}, Score: {score}")
    return min(score, 1.0)
```

## Performance Optimization

### Caching

Implement caching for repeated requests:

```python
from functools import lru_cache

class Bypasser:
    @lru_cache(maxsize=100)
    def get(self, url: str) -> str:
        # ... existing implementation
        pass
```

### Concurrent Requests

For batch operations:

```python
from concurrent.futures import ThreadPoolExecutor

def extract_multiple(urls: List[str]) -> List[ChapterResult]:
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(extract_single, urls))
    return results
```

## Best Practices

1. **Respect robots.txt**: Check and honor website crawling policies
2. **Rate limiting**: Add delays between requests to avoid overwhelming servers
3. **Error handling**: Always handle network errors gracefully
4. **User-Agent rotation**: Use realistic and varied user agents
5. **Content validation**: Verify extracted content makes sense before returning
6. **Logging**: Use proper logging instead of print statements in production

## Contributing Guidelines

1. Follow existing code style (PEP 8)
2. Add docstrings to all public methods
3. Include type hints
4. Write tests for new features
5. Update documentation
6. Test with multiple URLs before submitting
