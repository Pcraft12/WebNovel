# Novel Chapter Extractor

A generic, language-agnostic "reader mode" extractor for web-novel chapter
pages. Given raw HTML from **any** novel-reading site (English or Chinese,
unknown markup), it isolates the chapter title + body text and strips
navigation, ads, comments, "recommended novels," author-note widgets, and
other site chrome — so a TTS engine reads only the actual story.

This is a **prototype/validation script**. Once the heuristic is tuned
against enough real sites, the logic gets ported to Kotlin/JS for the
Android WebView novel reader app.

## Why

Feeding raw HTML into a WebView's TTS reader means it reads the whole
page — menus, "you may also like" tiles, comment threads, boilerplate.
This script is the extraction layer that fixes that, without hardcoding
rules for any specific site.

## Requirements

```bash
pip install beautifulsoup4 lxml requests
```

(`requests` is only needed if you extract directly from a URL instead of
a saved HTML file.)

## Usage

**Test harness** (prints title / confidence / char count / preview for
each source, so you can eyeball results):

```bash
python novel_extractor.py chapter1.html chapter2.html https://example.com/chapter/42
```

**Single-file JSON output** (what the app would actually consume):

```bash
python novel_extractor.py --json chapter1.html
```

```json
{
  "title": "Chapter 142: The Duel at Dawn",
  "content": "The morning mist clung to the training grounds...",
  "confidence": 0.857,
  "prev_chapter_href": "/chapter/141",
  "next_chapter_href": "/chapter/143"
}
```

**As a library:**

```python
from novel_extractor import extract

with open("chapter.html", encoding="utf-8") as f:
    html = f.read()

result = extract(html)
print(result.title)
print(result.content)      # this is what TTS should read
print(result.confidence)   # 0.0 - 1.0
```

## Output shape

| Field                | Type          | Notes                                                              |
|-----------------------|---------------|---------------------------------------------------------------------|
| `title`               | `str`         | Chapter title (heading in-page, or cleaned `<title>` fallback)      |
| `content`              | `str`         | Cleaned chapter body, paragraphs separated by blank lines            |
| `confidence`           | `float`       | `0.0`–`1.0`. Low confidence → app should offer full-page fallback or manual selection |
| `prev_chapter_href`     | `str \| null` | Best-guess "previous chapter" link, pulled before nav gets stripped  |
| `next_chapter_href`     | `str \| null` | Best-guess "next chapter" link                                       |

`confidence` is intentionally conservative — it drops close to `0` on
chrome-only pages (e.g. a 404) so the app knows extraction failed rather
than silently reading garbage.

## How it works

The algorithm is a simplified, heavily-commented port of the technique
behind Mozilla's Readability.js:

1. **Preprocess** — strip `<script>`, `<style>`, `<form>`, etc. `<head>`
   is deliberately kept alive (just not scored) so the `<title>` tag
   survives as a fallback title source.
2. **Fast path** — an `<article>` or `[role="main"]` with substantial,
   low-link-density text short-circuits straight to cleanup. Catches most
   modern/WordPress-style reader layouts immediately.
3. **Score & propagate** — every text-bearing leaf (`<p>`, `<pre>`,
   `<blockquote>`, or a `<div>`/`<span>` with direct text) is scored on:
   - content-character length (CJK + Latin, punctuation-agnostic)
   - punctuation density (weak signal of real prose vs. a UI label)
   - link density, squared and inverted (kills nav menus / link-farm
     "recommended" lists)
   - a penalty if its class/id matches the noise blocklist
   Each leaf's score is added to its parent (full weight) and grandparent
   (half weight) — the classic Readability trick for finding the
   *container* that wraps the bulk of the content, even when the actual
   text sits in a deeply nested wrapper `<div>` with no useful class name.
4. **Pick the winner** — highest-scoring container wins. If the top two
   candidates are close in score *and* are DOM siblings, they're merged
   (handles chapters split around a mid-content ad block).
5. **Clean the winner** — child elements matching the noise-keyword
   blocklist (comments, recommended/related lists, share widgets,
   breadcrumbs, prev/next-chapter nav clusters, ads — English and Chinese
   keywords both covered) are stripped. Prev/next chapter links are
   harvested *before* their containing nav cluster is deleted.
6. **Title detection** — `<h1>`/`<h2>` inside or immediately preceding the
   container, else the page `<title>`, split on common separators
   (`-`, `_`, `|`, `–`, `—`, `丨`) with the longest segment kept (site name
   suffixes are usually the shorter chunk).
7. **Confidence** — blend of: how decisively the winner beat the
   runner-up, how much of the total page text it represents (too little
   *or* too much is suspicious), how link-light the final text is, and
   whether a recognized CMS/reader class hint was involved.

All scoring uses **character counts, not word counts**, since Chinese has
no whitespace-delimited tokens — word-based heuristics silently break on
CJK text.

## Test fixtures

`test_html/` contains four synthetic pages built to stress different
failure modes:

- `english_site.html` — WordPress-style layout, `<article>` fast path,
  ads/comments/recommended-novels/breadcrumb noise
- `chinese_site.html` — raw `<div>` + `<br>` chapter text (very common on
  Chinese novel sites), Chinese noise keywords (推荐/评论/上一章/下一章)
- `hard_case_site.html` — no `<article>` tag at all, generic div soup,
  ads injected **mid-content** between paragraphs
- `noise_only.html` — a chrome-only 404-style page, used to confirm
  confidence correctly collapses toward `0` when there's no real content

Run `python novel_extractor.py test_html/*.html` to see how each scores.

Network in this dev environment is restricted to package registries, so
these are synthetic stand-ins — **before porting, run the script against
a handful of real chapter pages** (WTR Lab and the Chinese sites you're
targeting) and eyeball the output for tuning.

## Known limitations / porting notes

- No hardcoded per-site rules by design — accuracy depends entirely on
  the general heuristics, so expect to tune `GOOD_HINTS` / `NOISE_KEYWORDS`
  / score weights against real sites over time.
- The parent/grandparent score-propagation walk and the "does this div
  have block children" check lean on BeautifulSoup's tree API
  (`find_all`, `.parent`). When porting to JS for the WebView, these map
  onto `element.parentElement` / `querySelectorAll`, but the block-children
  check should be reworked to avoid O(n²) behavior on deeply nested pages.
- Sites that render chapter text via client-side JS (not present in the
  raw HTML) aren't handled here — this script assumes already-fetched,
  fully server-rendered HTML, matching how the WebView will hand off page
  source.
- The sibling-merge fallback only merges exactly two candidates one level
  apart; sites that scatter a chapter across three or more disjoint blocks
  will need a smarter merge pass if that pattern shows up in testing.
