# novel_extractor.py

Generic, heuristic-driven chapter-text extractor for novel-reading websites.

Given raw HTML from any chapter page, it isolates the **title** + **body text** and strips out nav bars, ads, comments, "recommended novels", author notes, website chrome, and other non-content noise.

No per-site rules — the algorithm is fully generic and works on both English and Chinese (Simplified & Traditional) novel sites.

Returns:

```python
{"title": str, "content": str, "confidence": float}
```

This is the prototyping form of the content-extraction layer for a WebView-based Android novel reader with TTS. Once validated here, the same algorithm will be ported to Kotlin/JS.

## Testing & Validation

This script has been **edited, debugged, and tested against [novel543.com](https://www.novel543.com)** — a Traditional Chinese novel site. The test URL used was:

```
https://www.novel543.com/0223699133/8096_1.html
```

### Bugs Found and Fixed During novel543 Testing

| # | Bug | Impact | Fix |
|---|-----|--------|-----|
| 1 | `NOISE_KEYWORDS` had `"ad-"` but not `"adblock"`/`"gadblock"` | Ad containers (`div.adBlock`, `div.gadBlock`) leaked into extracted content | Added `"adblock"`, `"gadblock"`, `"gad"` to `NOISE_KEYWORDS` |
| 2 | No text-content-based noise detection | Site notices like `溫馨提示: ...` (elements with no class/id) survived pruning | Added `NOISE_TEXT_PREFIXES` list and text-prefix check in `_looks_like_noise_element()` |
| 3 | `NOISE_TEXT_PREFIXES` only contained Simplified Chinese characters (e.g. 温 U+6E29) | Traditional Chinese notices (e.g. 溫 U+6EAB) on novel543 did not match | Added Traditional Chinese variants for all CJK noise patterns |
| 4 | Fast-path candidate could score lower than the general top scorer, making the runner-up higher than the chosen element and crushing confidence margin to 0 | Confidence stuck at ~0.40 despite correct extraction | Excluded ancestor/descendant candidates from runner-up calculation via identity-based parent-chain walking |
| 5 | `_detect_title` ancestor search used BS4 `.find()` which searches the entire subtree | Could grab unrelated headings from other branches | Changed to iterate only direct children of each ancestor |

**Additional fixes discovered during testing:**

- **Orphaned element crash**: `_prune_noise_children` iterated over a pre-computed list of descendants, but decomposing a parent made its children orphaned (`el.parent is None`), causing `AttributeError` on subsequent access. Fixed by adding an `el.parent is None` guard.
- **BS4 `.find(Tag)` unreliability with lxml**: BS4's `.find()` method does not use object identity — it matches by tag name and attributes, which fails across certain parser backends (lxml). Replaced with explicit `is`-based parent-chain walking in the ancestor/descendant check.

### novel543 Test Results

```
Run 1: confidence=0.771  content_length=1220  noise=none
Run 2: confidence=0.749  content_length=1245  noise=none
Run 3: confidence=0.771  content_length=1220  noise=none
```

- **Title** correctly extracted: `第1章 前言 (1/2)`
- All ad blocks, site notices (`溫馨提示`), and navigation elements properly pruned
- Confidence improved from **0.401** (before fixes) to **0.75–0.77** (after fixes)
- Verified across 3 separate HTTP requests (novel543 rotates notice messages randomly)

## How It Works

1. **Pre-clean** — decompose `<script>`, `<style>`, `<nav>`, `<header>`, `<footer>`, `<form>`, etc.
2. **Fast-path hint** — look for `<article>`, `role="main"`, or class/id substrings like `chapter-content`, `readcontent`, `txt`, `booktxt`.
3. **Candidate scoring** — for every plausible container (`<div>/<section>/<article>/<main>/<td>/<li>/<dd>`), compute a composite score based on text density, paragraph count, link density, and child fragmentation.
4. **Selection** — prefer the fast-path candidate if it scores within 70% of the top general candidate.
5. **Fallback** — if no clear winner, merge top-N structurally-adjacent candidates.
6. **Title detection** — `<h1>/<h2>/<h3>` inside the container (decomposed to avoid duplication), then ancestor siblings, then first `<h1>` in `<body>`, then `<title>` tag with site-name suffix stripped.
7. **Noise pruning** — secondary filter removing elements matching noise keywords (class/id/text) or text-content prefixes, with a 60% safety threshold.
8. **Text extraction** — walk the pruned tree, emit paragraph breaks at block boundaries, collapse whitespace.
9. **Confidence** — weighted blend of score margin, text length, and paragraph count, penalized by link density.

## Usage

```bash
# Install dependencies
pip install beautifulsoup4 lxml requests

# Test against a URL
python novel_extractor.py https://www.novel543.com/0223699133/8096_1.html

# Test against a local HTML file
python novel_extractor.py path/to/chapter.html

# Test multiple sources
python novel_extractor.py https://site1.com/chapter1.html https://site2.com/chapter2.html

# Run with built-in test URLs/files (edit TEST_URLS / TEST_FILES in the script)
python novel_extractor.py
```

## Configuration Knobs

Tune these constants at the top of the file against real sites:

| Constant | Default | Purpose |
|----------|---------|---------|
| `MIN_CONTENT_LENGTH` | 200 | Minimum text length for a viable candidate |
| `MAX_LINK_DENSITY` | 0.35 | Link-text fraction above which a candidate is penalized as nav/recs |
| `PARA_BOOST_PER_P` | 5.0 | Score boost per `<p>` or half-weighted `<br>` |
| `PARA_BOOST_CAP` | 200.0 | Cap on paragraph boost |
| `TEXT_SCORE_CAP` | 5000.0 | Cap on raw length contribution |
| `SHORT_CHILD_PENALTY` | 2.0 | Penalty per short text-node child (fragmented UI labels) |
| `CONFIDENCE_CEIL` | 0.95 | Maximum confidence value (never claim 100%) |

## Dependencies

- `beautifulsoup4` — HTML parsing
- `lxml` — faster, more forgiving parser backend (optional, falls back to `html.parser`)
- `requests` — URL fetching (only needed for live-URL testing; not needed when passing HTML strings directly)

## Porting Notes (for Kotlin/JS)

When porting to Kotlin/JS for the Android WebView reader:

- The scoring heuristic is pure string/integer math — no external NLP needed.
- BS4's `find_all` / `get_text` map directly to `querySelectorAll` / `textContent` in JS.
- The parent-chain ancestor check must use **reference identity**, not DOM `contains()` (same BS4 `.find()` vs `is` issue can occur).
- Include both Simplified and Traditional Chinese character variants in all keyword lists.
