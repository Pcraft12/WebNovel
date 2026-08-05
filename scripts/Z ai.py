#!/usr/bin/env python3
"""
novel_extractor.py
==================

Generic chapter-text extractor for novel-reading websites.

Given raw HTML from any chapter page, isolates the title + body text and
strips out nav bars, ads, comments, "recommended novels", author notes,
website chrome, etc.

Heuristic-driven (no per-site rules). Works on English & Chinese.
Returns: {"title": str, "content": str, "confidence": float}

This is the prototyping form of the content-extraction layer for a
WebView-based Android novel reader with TTS. Once validated here,
the same algorithm will be ported to Kotlin/JS.

Usage
-----
    python novel_extractor.py <url-or-html-file> [<url-or-file> ...]
    python novel_extractor.py            # runs built-in TEST_URLS / TEST_FILES

Dependencies: beautifulsoup4, lxml (optional but recommended), requests.
"""

from __future__ import annotations

import re
import sys
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup, NavigableString, Tag

try:
    import requests
except ImportError:  # requests only needed for live-URL testing
    requests = None

# Prefer lxml (faster, more forgiving on messy HTML); fall back to stdlib.
try:
    import lxml  # noqa: F401
    _PARSER = "lxml"
except ImportError:
    _PARSER = "html.parser"


# ---------------------------------------------------------------------------
# Configuration: heuristic knobs. Tune against real sites over time.
# ---------------------------------------------------------------------------

# Fast-path: if an element's class/id contains one of these substrings,
# treat it as a *hint* (still validated via scoring).
COMMON_CONTENT_HINTS = [
    "chapter-content", "chapter_content", "chaptertext", "chapter-text",
    "article-content", "article_content",
    "readcontent", "read-content", "read_content", "readbody", "read-body",
    "entry-content", "entry_content",
    "post-content", "post_content",
    "novel-content", "novel_content", "novel-body", "novel_body",
    "booktxt", "book-txt", "bookcontent",
    "txt", "text",           # very common on Chinese novel sites (id="txt")
    "content", "contents",
    "main-content", "main_content",
    "story-content", "story_content",
    "reader-content", "reader_content", "reading-content", "reading_content",
    "chapter-body", "chapter_body",
    "page-content", "page_content",
    "view-content", "view_content",
]

# Block-level wrappers we score as candidate containers.
CANDIDATE_TAGS = {"div", "section", "article", "main", "td", "li", "dd"}

# Noise keywords — if a child element's class/id/text matches, prune it from
# the chosen container. Applied AFTER candidate selection.
NOISE_KEYWORDS = [
    "comment", "comments", "disqus", "respond",
    "recommend", "recommended", "recommendation",
    "related", "seealso", "see-also", "related-post",
    "nav", "navbar", "navigation", "menu",
    "footer", "sidebar", "aside",
    "share", "social", "facebook", "twitter", "weibo",
    "advertisement", "ad-", "ads", "adsbygoogle", "adblock", "gadblock", "gad", "sponsor",
    "breadcrumb", "breadcrumbs",
    "prev", "next", "previous", "chapter-nav", "chapternav",
    "pagination", "pager",
    "popup", "modal", "overlay",
    "signup", "login", "register", "subscribe", "newsletter",
    "copyright", "license",
    "author-note", "translator-note",
]

# Chinese noise keywords (mixed into the same filter).
NOISE_KEYWORDS_CJK = [
    # Simplified
    "\u63a8\u8350", "\u8bc4\u8bba", "\u76f8\u5173", "\u4e0a\u4e00\u7bc7", "\u4e0b\u4e00\u7bc7",
    "\u4e0a\u4e00\u7ae0", "\u4e0b\u4e00\u7ae0", "\u76ee\u5f55", "\u7ae0\u8282\u76ee\u5f55",
    "\u5bfc\u822a", "\u83dc\u5355", "\u5e95\u90e8", "\u4fa7\u8fb9", "\u5206\u4eab",
    "\u5e7f\u544a", "\u8d5e\u52a9", "\u9762\u5305\u5c51", "\u4e0a\u4e00\u9875", "\u4e0b\u4e00\u9875",
    "\u4f5c\u8005\u7684\u8bdd", "\u8bd1\u8005\u7684\u8bdd", "\u7248\u6743",
    "\u6e29\u99a8\u63d0\u793a", "\u63d0\u793a", "\u767b\u5f55", "\u6ce8\u518c", "\u8054\u7cfb\u6211\u4eec",
    # Traditional Chinese variants
    "\u63a8\u85a6", "\u8a55\u8ad6", "\u76f8\u95dc", "\u4e0a\u4e00\u7bc7", "\u4e0b\u4e00\u7bc7",
    "\u4e0a\u4e00\u7ae0", "\u4e0b\u4e00\u7ae0", "\u76ee\u9304", "\u7ae0\u7bc0\u76ee\u9304",
    "\u5c0e\u822a", "\u5e95\u90e8", "\u5074\u908a", "\u5206\u4eab",
    "\u5ee3\u544a", "\u8d0a\u52a9", "\u767b\u5165", "\u8a3b\u518a", "\u806f\u7d61\u6211\u5011",
]

# Text-content patterns: if an element's text STARTS with one of these,
# it is treated as noise (site notices, reminders, login prompts).
# Both simplified and traditional Chinese variants are included.
NOISE_TEXT_PREFIXES = [
    "\u6e29\u99a8\u63d0\u793a",   # \u6e29\u99a8\u63d0\u793a (simplified)
    "\u6eab\u99a8\u63d0\u793a",   # \u6eab\u99a8\u63d0\u793a (traditional)
    "\u63d0\u793a\uff1a",         # \u63d0\u793a: (full-width colon)
    "\u63d0\u793a:\u3000",        # \u63d0\u793a:\u3000 (ASCII colon + space)
    "\u514d\u8d39\u5c0f\u8bf4",    # \u514d\u8d39\u5c0f\u8bf4 (simplified)
    "\u514d\u8cbb\u5c0f\u8aaa",    # \u514d\u8cbb\u5c0f\u8aaa (traditional)
    "\u672c\u7ad9\u63d0\u793a",    # \u672c\u7ad9\u63d0\u793a (simplified)
    "\u672c\u7ad9\u63d0\u793a",    # same in traditional
    "\u672c\u7ae0\u672a\u5b8c\u7ed3", # \u672c\u7ae0\u672a\u5b8c\u7ed3 (simplified)
    "\u672c\u7ae0\u672a\u5b8c\u7d50", # \u672c\u7ae0\u672a\u5b8c\u7d50 (traditional)
    "\u6700\u65b0\u7f51\u5740",    # \u6700\u65b0\u7f51\u5740 (simplified)
    "\u6700\u65b0\u7db2\u5740",    # \u6700\u65b0\u7db2\u5740 (traditional)
]

# Common <title>-tag suffix patterns to strip when falling back to <title>.
TITLE_SUFFIX_PATTERNS = [
    r"\s*[-\u2013|\u00b7]+\s*.+\u5c0f\u8bf4\u7f51.*$",
    r"\s*[-\u2013|\u00b7]+\s*.+\u6587\u5b66.*$",
    r"\s*[-\u2013|\u00b7]+\s*.+\u7f51.*$",
    r"\s*[-\u2013|\u00b7]+\s*\S+\s*$",      # "Chapter 1 - SiteName"
    r"\s*[|_]+\s*\S+\s*$",
]

# --- Scoring knobs ---------------------------------------------------------

MIN_CONTENT_LENGTH = 200          # below this, candidate is non-viable
MAX_LINK_DENSITY   = 0.35         # >this much text in <a> -> likely nav/recs
PARA_BOOST_PER_P   = 5.0          # each <p> adds this much
PARA_BOOST_CAP     = 200.0
TEXT_SCORE_CAP     = 5000.0       # raw-length contribution cap
SHORT_CHILD_PENALTY = 2.0         # per fragmented short text-node
MERGE_TOPN         = 3            # fallback: how many candidates to merge
MERGE_SCORE_GAP    = 0.5          # merge only if runner-ups >= top*GAP
CONFIDENCE_CEIL    = 0.95         # never claim 100% certainty


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------

# CJK + ASCII punctuation + whitespace. Stripped for *scoring only* \u2014
# preserved in the final extracted text.
_PUNCT_RE = re.compile(
    r"[\u3000-\u303f"      # CJK symbols & punctuation
    r"\uff00-\uffef"       # full-width forms
    r"\u2000-\u206f"       # general punctuation
    r"!-/:-@\[-`{-~"       # ASCII punctuation
    r"\s]+",
    re.UNICODE,
)

def _strip_punct_for_scoring(s: str) -> str:
    """Remove CJK + ASCII punctuation & whitespace for density scoring."""
    return _PUNCT_RE.sub("", s or "")


def _text_len(s: str) -> int:
    """Character count (not word count) \u2014 language-agnostic.

    Chinese has no spaces, so word-tokenization would under-count CJK text.
    """
    return len(_strip_punct_for_scoring(s or ""))


# ---------------------------------------------------------------------------
# HTML loading (used only by the test harness / CLI)
# ---------------------------------------------------------------------------

def load_html(source: str) -> str:
    """Load HTML from URL or local file. Returns the raw HTML string."""
    if source.startswith(("http://", "https://")):
        if requests is None:
            raise RuntimeError("requests not installed; cannot fetch URL")
        resp = requests.get(source, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (compatible; NovelReaderBot/1.0)"
        })
        # Chinese sites frequently mislabel charset; trust apparent encoding.
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding
        return resp.text
    with open(source, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Pre-processing
# ---------------------------------------------------------------------------

def _remove_obvious_noise(soup: BeautifulSoup) -> None:
    """Decompose tags that contribute zero useful chapter text.

    Done in-place so subsequent scoring isn't polluted by <script>/<style>.
    """
    for tag_name in ("script", "style", "noscript", "iframe", "svg",
                     "form", "button", "input", "select", "textarea",
                     "header", "nav", "footer"):
        for el in soup.find_all(tag_name):
            el.decompose()


# ---------------------------------------------------------------------------
# Noise-element detection (applied as a secondary filter on chosen container)
# ---------------------------------------------------------------------------

def _looks_like_noise_element(el: Tag) -> bool:
    """Class/id substring match against the noise blocklist."""
    cls = " ".join(el.get("class") or [])
    id_ = el.get("id") or ""
    blob = f"{cls} {id_}".lower()
    for k in NOISE_KEYWORDS:
        if k in blob:
            return True
    for k in NOISE_KEYWORDS_CJK:
        if k in blob:
            return True
    # Text-prefix noise detection: elements whose visible text starts
    # with common site-notice patterns (e.g. \u6e29\u99a8\u63d0\u793a: ...).
    text_stripped = el.get_text(strip=True)
    if text_stripped:
        for prefix in NOISE_TEXT_PREFIXES:
            if text_stripped.startswith(prefix):
                return True
    # Also catch elements whose class/id contains common notice keywords.
    for kw in ("notice", "reminder", "tip", "toast"):
        if kw in blob:
            return True
    return False


# ---------------------------------------------------------------------------
# Candidate scoring \u2014 the core heuristic
# ---------------------------------------------------------------------------

def _link_density(el: Tag) -> float:
    """Fraction of (punct-stripped) text inside <a> tags.

    Nav menus & recommendation lists are link-heavy (>=0.5).
    Chapter prose is link-sparse (<=0.1).
    """
    total = _text_len(el.get_text(" ", strip=True))
    if total == 0:
        return 0.0
    link_text = sum(_text_len(a.get_text(" ", strip=True))
                    for a in el.find_all("a"))
    return link_text / total


def _count_paragraphs(el: Tag) -> int:
    """Count <p> tags plus a fractional contribution from <br>.

    Many Chinese novel sites use <br> inside a single <div> instead of <p>,
    so we treat <br> as half-weight.
    """
    p_count = len(el.find_all("p"))
    br_count = len(el.find_all("br"))
    return p_count + (br_count // 2)


def _count_tags(el: Tag) -> int:
    """Total descendant element count \u2014 denominator for text density."""
    return sum(1 for _ in el.find_all())


def _short_child_text_nodes(el: Tag) -> int:
    """Count direct NavigableString children shorter than ~30 chars.

    Comment threads & UI labels fragment text into many tiny runs.
    Prose has few, long text runs.
    """
    n = 0
    for child in el.children:
        if isinstance(child, NavigableString):
            s = str(child).strip()
            if s and _text_len(s) < 30:
                n += 1
    return n


def _score_candidate(el: Tag) -> float:
    """Core scoring function. Higher = more likely to be chapter text.

    Components:
      * text-to-tag density (prose packs text with few tags)
      * paragraph boost (chapter prose is paragraph-heavy)
      * raw length signal (capped \u2014 long shouldn't win on length alone)
      * link-density penalty (nav/recs are link-heavy)
      * short-child penalty (comments/labels fragment text)
    """
    text = el.get_text(" ", strip=True)
    text_len = _text_len(text)
    if text_len < 50:
        return 0.0

    tag_count = max(1, _count_tags(el))
    density = text_len / tag_count

    # Link-density penalty. Hard cut above MAX_LINK_DENSITY, soft scaling below.
    ld = _link_density(el)
    if ld > MAX_LINK_DENSITY:
        density *= max(0.05, 1.0 - ld)
    else:
        density *= (1.0 - 0.5 * ld)

    para_boost = min(PARA_BOOST_CAP, _count_paragraphs(el) * PARA_BOOST_PER_P)
    short_penalty = _short_child_text_nodes(el) * SHORT_CHILD_PENALTY
    length_score = min(TEXT_SCORE_CAP, text_len)

    score = density + para_boost + (length_score * 0.1) - short_penalty
    return max(0.0, score)


def _collect_candidates(soup: BeautifulSoup) -> List[Tuple[Tag, float]]:
    """Score every plausible container in the document."""
    out = []
    for el in soup.find_all(CANDIDATE_TAGS):
        if _text_len(el.get_text(" ", strip=True)) < 50:
            continue
        s = _score_candidate(el)
        if s > 0:
            out.append((el, s))
    return out


# ---------------------------------------------------------------------------
# Fast path: CMS class/id hints (treated as hints, not authoritative)
# ---------------------------------------------------------------------------

def _fast_path_candidate(soup: BeautifulSoup) -> Optional[Tag]:
    """Look for <article>, role="main", or common CMS class/id hints.

    Returns the best-matching element or None. Result is *still* scored
    against the general candidate pool \u2014 hints aren't trusted blindly.
    """
    art = soup.find("article")
    if art and _text_len(art.get_text(" ", strip=True)) > MIN_CONTENT_LENGTH // 2:
        return art

    main = soup.find(attrs={"role": "main"})
    if main and _text_len(main.get_text(" ", strip=True)) > MIN_CONTENT_LENGTH // 2:
        return main

    best, best_len = None, 0
    for el in soup.find_all(CANDIDATE_TAGS):
        cls = " ".join(el.get("class") or [])
        id_ = el.get("id") or ""
        blob = f"{cls} {id_}".lower()
        for hint in COMMON_CONTENT_HINTS:
            if hint in blob:
                t = _text_len(el.get_text(" ", strip=True))
                if t > best_len:
                    best, best_len = el, t
                break
    if best and best_len >= MIN_CONTENT_LENGTH // 2:
        return best
    return None


# ---------------------------------------------------------------------------
# Title detection
# ---------------------------------------------------------------------------

def _strip_title_suffix(raw: str) -> str:
    """Strip trailing site-name suffixes from a <title> string."""
    t = raw.strip()
    for pat in TITLE_SUFFIX_PATTERNS:
        new = re.sub(pat, "", t).strip()
        if new and len(new) < len(t):
            t = new
            break
    return t


def _detect_title(soup: BeautifulSoup, container: Optional[Tag]) -> str:
    """Find the chapter title.

    Order of preference:
      1. <h1>/<h2>/<h3> inside the chosen container.
      2. <h1>/<h2> in an ancestor (sometimes title is sibling of content div).
      3. First <h1> in <body>.
      4. <title> tag with site-name suffix stripped.
    """
    if container is not None:
        for tag_name in ("h1", "h2", "h3"):
            h = container.find(tag_name)
            if h and h.get_text(strip=True):
                # If title lives *inside* content div, remove it from body
                # so it isn't duplicated in extracted text.
                txt = h.get_text(strip=True)
                h.decompose()
                return txt
        # Walk up to 3 ancestors looking for a heading sibling.
        parent = container.parent
        for _ in range(3):
            if not isinstance(parent, Tag):
                break
            for tag_name in ("h1", "h2"):
                # Only check direct children (not deep subtree) to avoid
                # grabbing headings from unrelated sibling branches.
                for child in parent.children:
                    if isinstance(child, Tag) and child.name == tag_name:
                        if child.get_text(strip=True) and child is not container:
                            return child.get_text(strip=True)
            parent = parent.parent

    body = soup.find("body") or soup
    h1 = body.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)

    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        return _strip_title_suffix(title_tag.get_text(strip=True))
    return ""


# ---------------------------------------------------------------------------
# Content extraction & noise pruning
# ---------------------------------------------------------------------------

def _prune_noise_children(container: Tag) -> None:
    """Remove child elements that look like noise (comments, recs, nav, ads).

    Safety: never prune an element that holds >60% of the container's text
    \u2014 some sites use confusingly-named wrappers for the content itself.
    """
    total = _text_len(container.get_text(" ", strip=True))
    for el in list(container.find_all(True)):
        # Skip if already decomposed (parent detached it from the tree).
        if el.parent is None:
            continue
        if not isinstance(el, Tag):
            continue
        if not _looks_like_noise_element(el):
            continue
        el_text = _text_len(el.get_text(" ", strip=True))
        if total > 0 and el_text / total > 0.6:
            continue
        el.decompose()


# Block-level tags that should produce a paragraph break in output.
_BLOCK_TAGS = {"p", "div", "section", "br", "li", "dd", "dt",
               "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote"}

def _extract_text(container: Tag) -> str:
    """Convert pruned container to readable text.

    Inserts paragraph breaks at block boundaries, collapses extra whitespace.
    Punctuation (CJK + ASCII) is preserved in output \u2014 stripping was only
    used during scoring.
    """
    parts: List[str] = []

    def walk(node):
        for child in node.children:
            if isinstance(child, NavigableString):
                s = str(child)
                if s.strip():
                    parts.append(s)
            elif isinstance(child, Tag):
                if child.name == "br":
                    parts.append("\n")
                elif child.name in _BLOCK_TAGS:
                    parts.append("\n\n")
                    walk(child)
                    parts.append("\n\n")
                else:
                    walk(child)

    walk(container)
    raw = "".join(parts)
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r" *\n *", "\n", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


# ---------------------------------------------------------------------------
# Confidence calculation
# ---------------------------------------------------------------------------

def _confidence(score: float, runner_up: float, text_len: int,
                container: Optional[Tag]) -> float:
    """Map raw signals to a 0..1 confidence value.

    Downstream app uses this to decide: trust extraction, fall back to
    full-page read, or prompt manual selection.

    Factors:
      * score margin over runner-up (decisive winner \u2192 higher conf)
      * absolute text length (too short \u2192 suspicious)
      * paragraph count (prose has many)
      * link-density penalty on the final container
    """
    if container is None or text_len < MIN_CONTENT_LENGTH:
        return 0.0

    # Margin: how dominant is the winner?
    if runner_up <= 0:
        margin = 1.0
    else:
        margin = max(0.0, min(1.0, (score - runner_up) / max(score, 1.0)))

    length_factor = min(1.0, text_len / 3000.0)
    para_factor   = min(1.0, _count_paragraphs(container) / 10.0)

    ld = _link_density(container)
    ld_penalty = 1.0 - min(0.7, ld * 1.5)

    c = (0.4 * margin + 0.3 * length_factor + 0.3 * para_factor) * ld_penalty
    return round(min(CONFIDENCE_CEIL, max(0.0, c)), 3)


# ---------------------------------------------------------------------------
# Fallback: merge structurally-adjacent candidates
# ---------------------------------------------------------------------------

def _merge_candidates(candidates: List[Tuple[Tag, float]]) -> Optional[Tag]:
    """Fallback when no single block dominates.

    Some sites split chapter text across multiple sibling <div>s. We merge
    top-N candidates if they share a parent and have comparable scores.
    """
    top = candidates[:MERGE_TOPN]
    top_score = top[0][1]
    qualifying = [el for el, s in top if s >= top_score * MERGE_SCORE_GAP]
    if len(qualifying) < 2:
        return None
    parent = qualifying[0].parent
    if not isinstance(parent, Tag):
        return None
    if not all(el.parent is parent for el in qualifying):
        return None
    # Wrap copies into a synthetic container so we don't mutate the tree.
    wrapper = BeautifulSoup("<div></div>", _PARSER).div
    for el in qualifying:
        wrapper.append(el.__copy__())
    return wrapper


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def extract_chapter(html: str) -> Dict:
    """Extract chapter title + body text from raw HTML.

    Returns {"title": str, "content": str, "confidence": float}.
    """
    soup = BeautifulSoup(html, _PARSER)
    _remove_obvious_noise(soup)

    fast = _fast_path_candidate(soup)
    candidates = _collect_candidates(soup)
    candidates.sort(key=lambda x: x[1], reverse=True)

    chosen: Optional[Tag] = None
    chosen_score = 0.0
    runner_up = 0.0

    if candidates:
        top_el, top_score = candidates[0]
        runner_up = candidates[1][1] if len(candidates) > 1 else 0.0

        if fast is not None:
            fast_score = _score_candidate(fast)
            # Prefer the fast-path hint if it scores within 70% of the top
            # candidate \u2014 class hints are usually reliable when they match.
            if fast_score >= top_score * 0.7:
                chosen, chosen_score = fast, fast_score
                # Runner-up: best score among candidates that are neither
                # the chosen element nor an ancestor/descendant of it.
                # Parent wrappers naturally score similarly because they
                # contain the same text \u2014 using them as runner-up
                # destroys the confidence margin.
                def _is_ancestor_or_descendant(a: Tag, b: Tag) -> bool:
                    if a is b:
                        return True
                    # Walk parent chains using identity comparison.
                    # .find() is unreliable across parser backends (lxml
                    # may not locate the exact Tag object reference).
                    p = b.parent
                    while p is not None:
                        if p is a:
                            return True
                        p = p.parent
                    p = a.parent
                    while p is not None:
                        if p is b:
                            return True
                        p = p.parent
                    return False
                other_scores = [
                    s for el, s in candidates
                    if not _is_ancestor_or_descendant(el, fast)
                ]
                runner_up = other_scores[0] if other_scores else 0.0
            else:
                chosen, chosen_score = top_el, top_score
        else:
            chosen, chosen_score = top_el, top_score
    elif fast is not None:
        chosen = fast
        chosen_score = _score_candidate(fast)

    # Fallback: merge adjacent high-scoring candidates if no clear winner.
    if (chosen is None or chosen_score < 50) and len(candidates) >= 2:
        merged = _merge_candidates(candidates)
        if merged is not None:
            chosen = merged
            chosen_score = candidates[0][1]

    if chosen is None:
        return {"title": _detect_title(soup, None), "content": "",
                "confidence": 0.0}

    # Title detection may decompose an <h1> inside the container \u2014 call it
    # BEFORE pruning & extracting so the title isn't duplicated in content.
    title = _detect_title(soup, chosen)
    _prune_noise_children(chosen)
    content = _extract_text(chosen)

    conf = _confidence(chosen_score, runner_up, _text_len(content), chosen)
    return {"title": title, "content": content, "confidence": conf}


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

# Replace these with real chapter URLs/files for tuning.
TEST_URLS: List[str] = [
    # "https://www.royalroad.com/fiction/<id>/<slug>/chapter/<id>/<title>",
    # "https://www.bqg2.com/book/<id>/<chapter>.html",
]

TEST_FILES: List[str] = [
    # "samples/site1_chapter.html",
    # "samples/site2_chapter.html",
]


def _run_one(source: str) -> None:
    print("=" * 72)
    print(f"SOURCE: {source}")
    try:
        html = load_html(source)
    except Exception as e:
        print(f"  [load error] {e}")
        return
    result = extract_chapter(html)
    print(f"  TITLE      : {result['title']!r}")
    print(f"  CONFIDENCE : {result['confidence']}")
    body = result["content"]
    if body:
        preview = body[:800] + ("..." if len(body) > 800 else "")
        print(f"  CONTENT ({len(body)} chars):")
        for line in preview.splitlines():
            print(f"    {line}")
    else:
        print("  CONTENT: (empty \u2014 extraction failed)")
    print()


def _run_tests() -> None:
    sources = TEST_URLS + TEST_FILES
    if not sources:
        print("No test sources configured.")
        print("Edit TEST_URLS / TEST_FILES in this script, or pass URLs/files")
        print("as CLI args, e.g.:")
        print("  python novel_extractor.py https://example.com/chapter1.html")
        return
    for src in sources:
        _run_one(src)


if __name__ == "__main__":
    # CLI args override / extend the built-in test list.
    for arg in sys.argv[1:]:
        if arg.startswith(("http://", "https://")):
            TEST_URLS.append(arg)
        else:
            TEST_FILES.append(arg)
    _run_tests()
