Here is a complete `README.md` you can drop into the project alongside `novel_extractor.py`.

```md
# Novel Extractor

Generic chapter-text extraction for arbitrary novel-reading websites.

This project is a Python prototype for the content-extraction layer of a WebView-based Android novel reader app with TTS. Given raw HTML from an unknown novel site, it tries to isolate only the actual chapter:

- chapter title
- chapter body text

and remove everything else:

- navigation bars
- ads
- comments
- recommended novels
- author notes
- prev/next chapter links
- website chrome
- other boilerplate

The extractor is heuristic-based and language-agnostic. It is intended to work on unknown English and Chinese novel sites without per-domain scrapers.

---

## Goal

Without this extraction step, TTS reads the entire raw page:

> menu, login, recommendations, comments, prev/next links, footer, ads, chapter body, more ads...

With this step, the app should get clean prose suitable for reading and TTS:

```json
{
  "title": "Chapter 1: The Beginning",
  "content": "The morning sun rose over the city...\n\nHe opened the old book...",
  "confidence": 0.87
}
```

The `confidence` field allows the downstream app to decide whether to:

- trust the extracted result,
- fall back to reading the full page,
- or prompt the user to manually select content.

---

## Project Files

```text
novel_extractor.py   # Main extractor module and CLI test harness
README.md            # This file
```

---

## Requirements

- Python 3.9+ recommended
- Dependencies:
  - `beautifulsoup4`
  - `lxml` recommended, optional
  - `requests` optional, only needed for fetching URLs in the CLI harness

No headless browser is required.

This tool expects already-fetched HTML. For live testing, it can optionally fetch URLs using `requests`.

---

## Installation

```bash
pip install beautifulsoup4 lxml requests
```

If you do not want URL fetching support, you can install only:

```bash
pip install beautifulsoup4 lxml
```

---

## CLI Usage

The script includes a small test harness.

### Extract from local HTML files

```bash
python novel_extractor.py samples/english_chapter.html samples/chinese_chapter.html
```

### Extract from live URLs

```bash
python novel_extractor.py https://example-novel-site.com/chapter-1.html
```

### Mix files and URLs

```bash
python novel_extractor.py chapter.html https://example-novel-site.com/chapter-2.html
```

### Print JSON output

```bash
python novel_extractor.py chapter.html --json
```

### Increase preview length

```bash
python novel_extractor.py chapter.html --preview 1200
```

### Set HTTP timeout

```bash
python novel_extractor.py https://example.com/chapter.html --timeout 30
```

---

## CLI Options

```text
sources          One or more HTML files or http/https URLs
--json           Print full JSON result for each source
--preview N      Number of content characters to preview in normal mode
--timeout N      HTTP timeout in seconds
```

Example:

```bash
python novel_extractor.py samples/*.html --json --preview 800
```

---

## Example Output

Normal mode:

```text
====================================================================================================
SOURCE    : samples/chapter_english.html
TITLE     : Chapter 1: The Beginning
CONFIDENCE: 0.873
CONTENT   :
The morning sun rose over the city, pale and thin between the towers...

He opened the old book and felt the familiar weight of it in his hands...
```

JSON mode:

```json
{
  "title": "Chapter 1: The Beginning",
  "content": "The morning sun rose over the city, pale and thin between the towers...\n\nHe opened the old book and felt the familiar weight of it in his hands...",
  "confidence": 0.873
}
```

---

## Programmatic API

You can also use the extractor as a Python module.

```python
from pathlib import Path
from novel_extractor import extract_chapter

html = Path("samples/chapter.html").read_bytes()

result = extract_chapter(html, url=None)

print(result["title"])
print(result["confidence"])
print(result["content"][:500])
```

If you have a URL, pass it as `url`. The URL is only used to help clean the page `<title>`, for example removing site-name suffixes.

```python
import requests
from novel_extractor import extract_chapter

url = "https://example-novel-site.com/chapter-1.html"
html = requests.get(url, timeout=20).content

result = extract_chapter(html, url=url)

print(result)
```

Return shape:

```python
{
    "title": str,
    "content": str,
    "confidence": float,
}
```

---

## Output Fields

| Field        | Type    | Description |
|---           |---      |---|
| `title`      | string  | Detected chapter title. May be empty if no reasonable title is found. |
| `content`    | string  | Extracted chapter body. Paragraphs are separated by blank lines. |
| `confidence` | float   | Extraction confidence from `0.0` to `1.0`. |

---

## Suggested Confidence Handling

The confidence score is intentionally conservative. Suggested downstream behavior:

| Confidence | Suggested App Behavior |
|---:|---|
| `0.75` and above | Trust extraction and send directly to TTS. |
| `0.45` to `0.75` | Use extraction, but allow user to switch to full-page mode. |
| Below `0.45` | Consider falling back to full-page reading or manual selection. |
| `0.0` | Extraction failed or produced no usable text. |

These thresholds should be tuned against your real corpus.

---

## How It Works

The extractor combines multiple weak signals instead of relying on one rule.

High-level pipeline:

```text
Raw HTML
  ↓
Parse with BeautifulSoup/lxml
  ↓
Remove scripts, styles, hidden elements, embedded media, forms, etc.
  ↓
Fast-path semantic checks:
  - <article>
  - <main>
  - role="main"
  ↓
Collect candidate containers:
  - div
  - section
  - article
  - main
  - td
  - center
  - body
  ↓
Score each candidate using:
  - text density
  - paragraph ratio
  - link density
  - short-text-node ratio
  - long text runs
  - class/id hints
  - tag semantics
  ↓
Choose one dominant candidate or merge adjacent strong candidates
  ↓
Detect title from:
  - nearby h1/h2/h3
  - og:title / twitter:title
  - page h1/h2
  - cleaned <title>
  ↓
Clean selected content:
  - remove nav/footer/header/aside
  - remove comment/recommend/author-note blocks
  - remove link-heavy clusters
  - remove prev/next chapter UI
  - remove small UI labels
  ↓
Serialize clean text blocks
  ↓
Return title, content, confidence
```

---

## Main Heuristics

### 1. Text Density

For each candidate block, the extractor estimates:

```text
density = meaningful character count / descendant tag count
```

Main chapter text usually has a high ratio of prose to markup.

Navigation menus, recommendation lists, and comment sections usually have many tags and little continuous prose.

---

### 2. Paragraph Ratio

Blocks with many `<p>` elements are rewarded.

Novel chapters are usually paragraph-based, while menus and recommendation widgets are usually list/link-based.

However, `<p>` is not required. Many Chinese novel sites use `<br>`-separated text inside a plain `<div>`. The extractor also rewards long continuous text runs.

---

### 3. Link Density Penalty

Blocks with lots of anchor text are penalized.

This helps remove:

- navigation bars
- recommended novels
- related chapters
- prev/next chapter clusters
- tag clouds
- sidebar widgets

---

### 4. Short-Node Penalty

Blocks with many short text nodes are penalized.

This helps reduce:

- comment threads
- UI labels
- button text
- metadata
- small widget text
- chapter navigation clusters

---

### 5. Class/ID Hints

Common class/id patterns are treated as soft hints, not requirements.

Positive hints include patterns like:

```text
content
chapter
article
read
reader
story
fiction
novel
book
txt
main
内容
章节
正文
小说
阅读
```

Negative hints include patterns like:

```text
comment
recommend
related
nav
menu
footer
sidebar
share
advertisement
disqus
breadcrumb
prev
next
author
note
copyright
评论
推荐
相关
广告
目录
书架
上一章
下一章
作者有话说
```

These are hints only. A block can still be selected without matching any known class or id.

---

### 6. Semantic Fast Path

The extractor first checks semantic containers:

```html
<article>
<main>
<div role="main">
```

These are strong signals, but they are still scored and compared against general density candidates.

---

### 7. Merge Fallback

If no single dominant block is found, the extractor may merge multiple strong adjacent candidates.

This helps pages where the chapter is split across several sibling containers, for example:

```html
<div class="chapter-part-1">...</div>
<div class="chapter-part-2">...</div>
<div class="chapter-part-3">...</div>
```

The merge fallback only applies when the candidates are structurally adjacent and collectively stronger than the best single block.

---

## Title Detection

Title detection tries multiple sources in this order:

1. `h1`, `h2`, or `h3` near the selected content block
2. `og:title`
3. `twitter:title`
4. best page-level `h1` or `h2`
5. cleaned `<title>` tag

The `<title>` cleanup tries to remove site-name suffixes and prefixes.

Example:

```text
Chapter 1: The Beginning - NovelSite
```

becomes:

```text
Chapter 1: The Beginning
```

Example:

```text
第一章 觉醒 - 小说阅读网
```

becomes:

```text
第一章 觉醒
```

Title cleanup is generic and uses:

- URL host tokens
- common English site-like suffixes
- common Chinese site-like suffixes
- common separators such as `|`, `-`, `—`, `_`, `:`

---

## Language Handling

The extractor is designed to be usable for both English and Chinese sites.

For scoring, it uses character count after removing punctuation and whitespace.

This avoids word-count bias against Chinese, which does not use spaces between words.

Important:

- Scoring ignores punctuation.
- Final extracted output preserves punctuation.
- Paragraph breaks are preserved as `\n\n`.

---

## Testing Workflow

For tuning, it is recommended to keep a corpus of saved chapter pages.

Example directory:

```text
samples/
  english_site_a.html
  english_site_b.html
  chinese_site_a.html
  chinese_site_b.html
  br_only_layout.html
  table_layout.html
  comments_heavy.html
```

Run:

```bash
python novel_extractor.py samples/*.html
```

For machine-readable output:

```bash
python novel_extractor.py samples/*.html --json > results.json
```

Then inspect:

- Is the title correct?
- Is the chapter body complete?
- Are comments removed?
- Are prev/next links removed?
- Are recommended novels removed?
- Is author note removed?
- Is confidence reasonable?

---

## Tuning Guide

Most tuning will happen in `novel_extractor.py`.

### Positive/Negative Attribute Hints

Adjust these regexes if the extractor repeatedly misses or keeps certain blocks.

```python
HINT_ATTR_RE
NEGATIVE_ATTR_RE
```

Examples:

- If author notes are not removed, add patterns to `NEGATIVE_ATTR_RE`.
- If chapter containers are missed, add generic patterns to `HINT_ATTR_RE`.

Avoid adding site-specific rules unless absolutely necessary. Prefer generic patterns.

---

### Small UI Label Removal

Adjust:

```python
NEGATIVE_LABEL_RE
```

This controls removal of small text blocks such as:

```text
Next Chapter
Previous Chapter
上一章
下一章
推荐本书
加入书架
Comments
Share
Advertisement
```

Be careful not to make this too broad. It can accidentally remove short legitimate dialogue lines.

---

### Candidate Tags

Adjust:

```python
CANDIDATE_TAGS
```

Default:

```python
CANDIDATE_TAGS = [
    "div", "section", "article", "main", "td", "center", "body",
]
```

If a site uses unusual containers, you may need to add tags here.

---

### Text Block Serialization

Adjust:

```python
TEXT_BLOCK_TAGS
```

This controls which tags are treated as paragraph-like blocks during final text extraction.

Default includes:

```text
p
div
section
article
blockquote
pre
li
h1-h6
td
th
figure
figcaption
dd
dt
```

---

### Cleaning Rules

Adjust:

```python
CLEAN_REMOVE_TAGS
```

This controls which descendant tags are removed from the selected content block.

Default removes:

```text
script
style
iframe
svg
form
button
input
nav
footer
header
aside
img
audio
video
...
```

---

### Scoring Thresholds

Important functions:

```python
_score_tag()
_choose_selection()
_estimate_confidence()
```

Useful thresholds to tune:

| Location | Purpose |
|---|---|
| `feat["chars"] < 60` | Minimum candidate size |
| `link_density` penalty | How strongly link-heavy blocks are punished |
| `short_string_ratio` penalty | How strongly UI-like short text is punished |
| `p_ratio` reward | How strongly paragraph-heavy blocks are rewarded |
| `long_run_ratio` reward | How strongly long text runs are rewarded |
| `best.feat["chars"] < 300` | Merge fallback trigger |
| `margin < 0.25` | Merge fallback trigger |
| `final_chars < 150` | Final confidence penalty |

---

## Porting to Kotlin/JS

This prototype is designed to be portable to the Android app's WebView/JS layer.

The important concepts to port are:

1. Remove non-content nodes first.
2. Score candidate containers.
3. Use density, paragraph ratio, link density, and short-node ratio.
4. Treat class/id hints as soft signals.
5. Prefer semantic containers when they are clean.
6. Merge adjacent strong candidates if no dominant block exists.
7. Clean the selected node before serialization.
8. Return confidence with the result.

In JavaScript/Kotlin WebView injection, the same algorithm can use:

```js
document.querySelectorAll("div, section, article, main, td, center, body")
```

Then compute:

```js
element.innerText.length
element.querySelectorAll("*").length
element.querySelectorAll("a").length
element.querySelectorAll("p").length
```

For Chinese text, use code-point-aware length, not naive word splitting.

---

## Limitations

This is a generic heuristic extractor, not a guaranteed scraper.

Known limitations:

### 1. JavaScript-rendered pages

If the chapter text is inserted by JavaScript after page load and is not present in the raw HTML, this extractor cannot see it.

For the WebView app, this may be less of a problem because the WebView can access the rendered DOM.

---

### 2. Anti-bot or login walls

The extractor assumes it receives real chapter HTML.

It does not bypass:

- CAPTCHAs
- paywalls
- logins
- Cloudflare-style challenges
- anti-scraping systems

---

### 3. Extremely malformed HTML

BeautifulSoup and lxml are tolerant, but severely broken markup can still cause poor extraction.

---

### 4. Hidden content

Elements hidden with CSS are removed by default.

Most hidden elements are ads or UI chrome, but some sites may hide chapter text for anti-copy purposes. If this becomes common, the hidden-element handling may need to be softened.

---

### 5. Ads embedded inside paragraphs

If an advertisement is injected directly into the middle of chapter prose with no distinguishing markup, it may be difficult to remove without damaging the chapter.

---

### 6. Ambiguous titles

Some pages have multiple headings:

- site name
- novel name
- volume name
- chapter title
- section title

The extractor tries to choose the best heading, but ambiguous pages may require tuning.

---

## Troubleshooting

### The title is wrong

Check:

- Is the correct heading inside or near the content block?
- Is the page using `og:title`?
- Is the `<title>` suffix cleanup removing too much?

Relevant code:

```python
_detect_title()
_title_from_candidate()
_clean_title()
```

---

### The content is empty

Possible causes:

- The chapter is JavaScript-rendered.
- The selected candidate was too link-heavy or negative and got removed.
- The content was inside a hidden element.
- The page structure is unusual.

Try:

```bash
python novel_extractor.py page.html --json
```

Then inspect the confidence and title.

Relevant code:

```python
_choose_selection()
_clean_content_root()
_extract_text_from_root()
```

---

### Too much noise remains

Possible causes:

- Noise block does not match negative patterns.
- Noise is inside the selected content container.
- Noise is not link-heavy enough to trigger automatic removal.

Tune:

```python
NEGATIVE_ATTR_RE
NEGATIVE_LABEL_RE
_clean_content_root()
```

---

### Good content is removed

Possible causes:

- Overly broad negative regex.
- Link-density penalty too aggressive.
- Short-line penalty too aggressive.
- Hidden-element detection too aggressive.

Tune:

```python
NEGATIVE_ATTR_RE
NEGATIVE_LABEL_RE
HIDDEN_RE
_score_tag()
_clean_content_root()
```

---

## Design Constraints

This module intentionally follows these constraints:

- No hardcoded per-domain rules.
- No heavy NLP dependencies.
- No headless browser requirement.
- Single self-contained Python module.
- Minimal dependencies.
- Must generalize across unknown novel sites.
- Must support English and Chinese text.
- Must return confidence for downstream app decisions.

---

## Legal and Ethical Use

This tool is intended for:

- personal reading assistance,
- accessibility,
- TTS usability,
- content extraction from pages the user is already viewing.

Respect website terms of service, copyright, robots policies, and rate limits.

Do not use this for large-scale scraping or redistribution of copyrighted content.

---

## License

Add your chosen license here.

For example:

```text
MIT License
```

or:

```text
Apache-2.0
```
```
