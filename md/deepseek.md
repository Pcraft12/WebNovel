```markdown
# Novel Chapter Content Extractor

A Python script that extracts the main chapter text (title + body) from arbitrary novel-reading websites, stripping away navigation bars, ads, comments, recommended lists, and other boilerplate. It is designed to work for both English and Chinese content without any per‑site hardcoding.

This is a **prototyping/testing tool** for the content‑extraction layer of an Android novel reader app that uses Text‑to‑Speech (TTS). Once the heuristic algorithm is validated here, the logic will be ported to Kotlin/JS for use inside a WebView‑based mobile app.

---

## Problem Statement

When a WebView loads a novel chapter page, the raw HTML contains far more than just the story—menus, advertisements, comment threads, “next chapter” links, and “recommended novels” all clutter the page. Reading this entire page with TTS produces an unusable stream of noise. The extraction layer must isolate just the chapter title and body text, regardless of the website's layout or CMS.

---

## Features

- **Generic heuristic algorithm** – No per‑domain rules; works on unknown sites.
- **Language‑agnostic** – Uses character counts instead of word counts, so it handles both English and Chinese (and other CJK scripts) without tokenisation.
- **Multi‑signal scoring** – Combines:
  - Text density (characters per HTML tag)
  - Link density (penalises navigation and recommendation lists)
  - Number of long `<p>` paragraphs
  - Common content class/id patterns (as hints)
  - Short‑text node ratio (penalises comment threads and UI labels)
- **Noise blocklist** – Removes elements with typical class/id names (comments, ads, related, share, etc.) in both English and Chinese.
- **Confidence score** – Returns a value between 0 and 1, allowing the downstream app to decide whether to trust the extraction or fall back to full‑page reading or manual selection.
- **Built‑in title detection** – Extracts title from `<h1>`/`<h2>` inside the content block, or falls back to the page `<title>` (stripping common site suffixes).
- **Self‑contained** – Only requires `BeautifulSoup`, `lxml`, and `requests` – no heavy NLP frameworks.

---

## Installation

### Prerequisites
- Python 3.6 or higher
- `pip` (Python package manager)

### Install dependencies
```bash
pip install beautifulsoup4 lxml requests
```

---

## Usage

### Command‑line interface
You can run the script with one or more URLs or local HTML files:

```bash
python extractor.py https://example.com/novel/chapter-1
python extractor.py ./saved_page.html
python extractor.py url1.html url2.html https://site.com/chapter
```

The script will print the extracted title, confidence score, and the first 500 characters of the content for each input.

### As a Python module
```python
from extractor import NovelContentExtractor

extractor = NovelContentExtractor(url="https://some-novel-site.com/chapter")
# or with pre‑fetched HTML:
# extractor = NovelContentExtractor(html=raw_html_string)

result = extractor.extract()
print(result["title"])
print(result["content"])
print(result["confidence"])
```

The result dictionary contains:
- `title` (str) – the extracted chapter title.
- `content` (str) – the cleaned chapter text (with paragraphs separated by newlines).
- `confidence` (float) – a score between 0 and 1 indicating how reliable the extraction is.

---

## Testing and Tuning

The script includes a small test harness that prints results for visual inspection. To tune the heuristics for a new set of sites:

1. Collect a few example HTML pages from different novel websites (both English and Chinese).
2. Run the script on them and examine the output.
3. Adjust the scoring weights, noise patterns, or content patterns in the source code based on what you see.
4. The comments in the code explain each heuristic clearly.

For more rigorous evaluation, you can build a small test suite comparing extraction results against manually annotated ground truth.

---

## Algorithm Overview

1. **Pre‑cleaning** – Remove elements with class/id matching noise patterns (scripts, styles, iframes, ads, comments, navigation).
2. **Candidate selection** – Gather all `<div>`, `<section>`, `<article>`, and `<main>` elements. If an `<article>` or `<main>` or `role="main"` is found, it is given priority.
3. **Scoring** – Each candidate is scored using:
   - Text density (character count ÷ number of tags)
   - Number of long `<p>` paragraphs
   - Link density (penalty)
   - Proportion of short text nodes (penalty)
   - Content class/id hints (bonus)
4. **Choose the best** – The element with the highest score is selected.
5. **Clean the selected block** – Remove any remaining noise inside, convert `<br>` and `<p>` tags to newlines, and collapse extra whitespace.
6. **Title detection** – Search for `<h1>`/`<h2>` within the block, otherwise fall back to `<title>` with site‑name stripping.
7. **Confidence** – Computed from the score and adjusted by content hints and text length.

The algorithm is inspired by Mozilla's Readability.js, adapted for character‑based languages and simplified for chapter‑specific content.

---

## Porting to Kotlin/JS (Android App)

Once the algorithm is tuned, the core logic will be ported to Kotlin/JS for execution inside the Android app's WebView. The port should preserve:

- The same heuristic scoring (using DOM traversal APIs available in Kotlin/JS, e.g., `document.querySelectorAll`).
- Noise patterns and text cleaning (using regular expressions available in Kotlin).
- Confidence calculation.

The Python version serves as the reference implementation. Keep the code clean and well‑commented to facilitate an accurate port.

---

## Dependencies

- **BeautifulSoup4** – HTML parsing and DOM manipulation.
- **lxml** – Fast HTML parser (used by BeautifulSoup).
- **requests** – For fetching live URLs (optional; you can also provide HTML strings directly).

---

## Limitations and Future Improvements

- **Merely heuristic** – No algorithm is 100% perfect; some sites may require additional tweaks.
- **Merging adjacent candidates** – Currently only the single best block is returned; merging nearby good blocks could improve coverage.
- **JavaScript‑rendered content** – The script expects already‑rendered HTML. For dynamic sites, you would need to pre‑render with a headless browser.
- **Performance** – For extremely large HTML pages, the scoring loop may be slow; in Kotlin/JS you can optimise with early‑exit strategies.

---

## License

This project is provided as‑is for testing and prototyping. You are free to use, modify, and distribute it as needed for your own applications.

---

## Contributing

If you have improvements or find common patterns that break the extractor, please share your findings. The algorithm is expected to evolve over time as it encounters more real‑world sites.

---

*Happy extracting!*
```
