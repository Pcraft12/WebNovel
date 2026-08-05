# Novel Chapter Content Extractor

A generic, heuristic-based HTML content extractor tuned for **novel-reading websites**. It isolates chapter title + body text from arbitrary HTML, stripping nav bars, ads, comments, recommendations, author notes, and site chrome — producing clean output ready for text-to-speech (TTS) engines.

> **Context:** This is the prototyping script for the content-extraction layer of a WebView-based Android novel reader app. Once validated, the logic will be ported to Kotlin/JS.

---

## Features

- **Zero per-domain rules** — works on any English or Chinese novel site out of the box
- **Language-agnostic scoring** — uses character count (not word count), so Chinese text without spaces scores correctly
- **Multi-signal heuristics** — combines structural hints, text-density scoring, link-density penalties, and paragraph-length bonuses
- **Fast-path detection** — instantly recognizes common CMS patterns (`chapter-content`, `readcontent`, `小说正文`, `<article>`, `role="main"`, etc.)
- **Noise blacklist** — filters comments, ads, prev/next links, author notes, sidebars, and their Chinese equivalents
- **Confidence scoring** — returns a `0.0–1.0` confidence value so downstream apps can decide whether to trust the result, fall back, or prompt manual selection
- **Readability fallback** — automatically falls back to Mozilla's Readability.js algorithm (via `readability-lxml`) when heuristics are uncertain
- **Self-contained test harness** — built-in CLI for batch-testing against live URLs or saved HTML files

---

## Installation

```bash
pip install beautifulsoup4 lxml readability-lxml requests
```

Or with a `requirements.txt`:

```
beautifulsoup4>=4.12.0
lxml>=4.9.0
readability-lxml>=0.8.1
requests>=2.28.0
```

---

## Quick Start

### Command Line

```bash
# Extract from a live URL (human-readable output)
python novel_extractor.py --url "https://example.com/chapter/123"

# Extract from a local HTML file
python novel_extractor.py --file chapter.html

# Output as JSON for downstream processing
python novel_extractor.py --url "https://example.com/chapter/123" --json

# Run the built-in test harness against a mix of English & Chinese sites
python novel_extractor.py --test

# Test against your own URL list (one per line)
python novel_extractor.py --test my_urls.txt
```

### Programmatic API

```python
from novel_extractor import NovelExtractor

extractor = NovelExtractor(min_text_length=200)

with open("chapter.html", "r", encoding="utf-8") as f:
    html = f.read()

result = extractor.extract(html, url="https://example.com/chapter/123")

print(result.title)       # "Chapter 1: The Beginning"
print(result.content)     # Plain-text paragraphs, separated by \n\n
print(result.confidence)  # 0.92
print(result.method)      # "fast-path" or "density-heuristic"
```

---

## Output Format

```json
{
  "title": "Chapter 1: The Beginning",
  "content": "The sun rose over the eastern mountains...",
  "content_html": "<div>...cleaned HTML fragment...</div>",
  "confidence": 0.92,
  "method": "density-heuristic",
  "warnings": []
}
```

| Field | Description |
|-------|-------------|
| `title` | Detected chapter title (empty string if none found) |
| `content` | Clean plain text with paragraph breaks preserved |
| `content_html` | Optional cleaned HTML fragment (useful for rich-text preview) |
| `confidence` | `0.0–1.0` aggregated confidence score |
| `method` | Which strategy succeeded (`fast-path`, `density-heuristic`, `readability-lxml-fallback`, `failed`) |
| `warnings` | List of human-readable warnings (e.g., "Extracted text very short") |

---

## How It Works

The extractor runs in **8 stages**, combining multiple independent signals so no single heuristic can fail catastrophically.

### 1. Pre-clean
Removes invisible/irrelevant tags (`<script>`, `<style>`, `<nav>`, `<aside>`, HTML comments) and elements whose `class`/`id` contain strongly negative keywords (`comment`, `advertisement`, `推荐`, `广告`, etc.).

### 2. Fast-path structural hints
Checks for well-known containers first:
- Semantic HTML: `<article>`, `<main>`, `[role="main"]`
- Common CMS classes: `.chapter-content`, `#readcontent`, `.小说正文`, `.booktext`, etc.

If found and containing substantial text (≥200 chars), returns immediately with high confidence.

### 3. Density-based candidate scoring
For every block-level container in the `<body>`, computes a **composite score** from:

| Signal | Weight | Rationale |
|--------|--------|-----------|
| **Text density** | `score_len / tag_count` | More text per tag = less boilerplate markup |
| **Paragraph bonus** | `+2.0` per `<p>` | Novels are paragraph-heavy |
| **Long-run bonus** | `+1.5` per text node ≥80 chars | Catches flowing prose |
| **Link-density penalty** | `-10.0` if >30% of text is inside `<a>` | Nav menus and "recommended novels" are link-heavy |
| **Short-node penalty** | `-5.0` for many tiny text nodes | UI labels, timestamps, comment usernames |
| **Depth penalty** | `-0.3` per level beyond depth 8 | Deep nesting often indicates widgets |
| **Class/id hints** | `+3.0` per positive match, `-2.5` per negative | Leverages site conventions without hardcoding domains |
| **Article/main bonus** | `+15.0` / `+20.0` | Semantic HTML is highly reliable |

> **Important:** All scoring uses **character count**, not word count. This makes the heuristic equally accurate for English and Chinese (and any other language).

### 4. Candidate selection & merging
Selects the highest-scoring block. If the runner-up is structurally adjacent (sibling or cousin) and within 30% of the top score, the two blocks are merged. This catches sites that split chapter text across multiple `<div>` siblings.

### 5. Post-clean
Inside the winning block, strips surviving noise:
- Prev/next chapter navigation links
- Author notes (detected by keywords like "Author's Note", "作者的话", "PS.")
- Empty paragraphs and single-image containers
- Any elements still matching negative patterns

### 6. Title detection
Tries three strategies in order:
1. `<h1>` inside the content block
2. A nearby `<h1>`/`<h2>` containing chapter keywords (`chapter`, `第`, `章`, `节`, etc.)
3. The page `<title>` tag, cleaned of site-name suffixes (` - NovelSite`, `_XX小说网`, etc.)

### 7. Confidence scoring
Aggregates six normalized signals into a single `0.0–1.0` score:
- Text length adequacy
- Paragraph density
- Link density (inverse)
- Dominance over the runner-up candidate
- Positive class/id hints
- Long text-run count

The final confidence is weighted 70% toward the average signal and 30% toward the weakest signal, so a single red flag pulls the score down.

### 8. Readability fallback
If no candidate meets the minimum text-length floor, the extractor falls back to Mozilla's Readability.js algorithm (via the Python port `readability-lxml`). This provides a safety net for exotic page structures, but with lower confidence.

---

## Configuration & Tuning

The script is designed to be tuned over time as you encounter new site layouts. Key tuning knobs are at the top of the file:

### `POSITIVE_PATTERNS`
Add class/id substrings that strongly indicate chapter content on sites you encounter. Higher weights = stronger signal.

```python
POSITIVE_PATTERNS = {
    "chapter-content": 4.0,
    "小说正文": 4.5,
    # ... add your own
}
```

### `NEGATIVE_PATTERNS`
Add substrings that indicate boilerplate. These are penalized uniformly.

```python
NEGATIVE_PATTERNS = {
    "comment", "advertisement", "推荐", "广告",
    # ... add your own
}
```

### Scoring weights
Inside `_score_element()`, adjust the multipliers for density, paragraphs, links, depth, etc.:

```python
final = (
    density * 2.0          # increase if text density is highly reliable
    + score_len * 0.01
    + p_count * 2.0        # paragraph bonus
    + long_text_runs * 1.5 # long-run bonus
    + pos_hint * 3.0
    - neg_hint * 2.5
    - link_penalty * 10.0  # increase if link-heavy false positives are common
    - short_penalty * 5.0
    - depth_penalty
)
```

### `MIN_CHAPTER_LENGTH`
Set the floor for what counts as a valid chapter. Increase if you're seeing teaser/preview pages pass through; decrease if legitimate short chapters are being rejected.

---

## Testing

### Built-in test harness
The script includes a default list of English and Chinese novel URLs for quick validation:

```bash
python novel_extractor.py --test
```

### Custom URL list
Create a text file with one URL or local file path per line:

```text
# my_urls.txt
https://www.royalroad.com/fiction/.../chapter/...
https://www.qidian.com/chapter/.../.../
./saved_chapters/chapter_1.html
./saved_chapters/chapter_2.html
```

Then run:

```bash
python novel_extractor.py --test my_urls.txt
```

### Interpreting results
For each source, the harness prints:
- **Method** — which strategy succeeded
- **Confidence** — aggregated trust score
- **Title** — detected chapter title
- **Content preview** — first 800 characters of extracted text

Use these prints to eyeball whether the extractor is capturing the right block and stripping the right noise. If a site consistently fails, add its content-container class to `POSITIVE_PATTERNS` or adjust the scoring weights.

---

## Porting to Kotlin/JS (Android WebView)

This Python script is a prototype. The final implementation runs inside a WebView or headless JS environment. Here is how each concept maps:

| Python Concept | Kotlin/JS Equivalent |
|----------------|----------------------|
| `BeautifulSoup` | WebView `document` object or `jsdom` |
| `elem.find_all(True)` | `document.querySelectorAll('*')` |
| `elem.get_text()` | `elem.textContent` |
| `score_char_count()` | Regex replace on `textContent`, then `.length` |
| `has_negative_indicator()` | Check `element.className` and `element.id` against a `Set<String>` |
| `_score_element()` | Pure scalar math — trivial to port |
| `_post_clean()` | `element.remove()` on matched nodes |
| `Readability fallback` | Include `readability.js` (Mozilla's official JS port) as a `<script>` tag |

### Recommended Android architecture

```
WebView loads chapter URL
    ↓
JavaScript injection: run extraction algorithm
    ↓
JS returns JSON: { title, content, confidence, method }
    ↓
Kotlin layer decides:
    confidence >= 0.8  → pass content to TTS engine
    0.5–0.8            → show "Tap to edit" overlay
    < 0.5              → fallback to raw page or manual selection
```

### Prev/next chapter URLs
The post-clean step **removes** prev/next links from the TTS text, but you should **capture their `href` values before removal** and pass them to the Kotlin layer as navigation metadata:

```kotlin
data class ChapterExtraction(
    val title: String,
    val content: String,
    val confidence: Float,
    val prevUrl: String?,   // extracted before stripping nav
    val nextUrl: String?    // extracted before stripping nav
)
```

---

## Limitations & Known Edge Cases

| Issue | Mitigation |
|-------|------------|
| **Paywalled / login-gated chapters** | Extracted text will be very short; confidence drops and a warning is emitted. The app should detect this and prompt the user. |
| **Image-heavy illustrated novels** | The extractor focuses on text. Images inside the winning block are preserved in `content_html` but omitted from `content`. If images are narratively essential, consider a secondary image-captioning pass. |
| **Infinite-scroll / lazy-loaded content** | The extractor works on the HTML snapshot it receives. If the site loads chapter text via XHR after page load, fetch the HTML **after** the WebView has finished executing JavaScript. |
| **Extremely non-standard markup** | The Readability fallback catches most exotic layouts, but confidence will be lower. For persistent failures, add site-specific positive patterns rather than per-domain scrapers. |

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `beautifulsoup4` | HTML parsing and DOM traversal |
| `lxml` | Fast XML/HTML parser backend for BeautifulSoup |
| `readability-lxml` | Mozilla Readability.js Python port (fallback) |
| `requests` | Fetching live URLs for the test harness |

---

## License

MIT — use freely in commercial and personal projects. Attribution appreciated but not required.

---

## Contributing

This is a tuning-heavy heuristic system. The most valuable contributions are:

1. **Real-world HTML samples** that fail extraction (anonymized, please)
2. **New positive/negative patterns** for popular novel CMS platforms
3. **Weight adjustments** backed by before/after confidence scores on a test corpus

When tuning, always test against both English and Chinese sites to avoid regressions in either language.
