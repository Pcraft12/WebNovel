"""
novel_extractor.py
==================

Generic, language-agnostic "reader mode" extractor for web-novel chapter pages.

Given raw HTML from ANY novel-reading site (English or Chinese, unknown
markup), this module isolates the actual chapter title + body text and
strips navigation, ads, comments, "recommended novels", author-note
widgets, and other site chrome.

This is a *prototype* for validating the extraction heuristic before the
logic gets ported to Kotlin/JS inside an Android WebView reader app.

Algorithm (inspired by Mozilla's Readability.js / python-readability, but
kept dependency-light and heavily commented so it's easy to tune later):

  1. Strip obviously non-content tags (script, style, nav, footer, etc.)
  2. Score every "leaf-ish" text-bearing node (p, pre, td, or a div/span
     with direct text) based on text length, punctuation density and
     link density.
  3. Propagate each leaf's score up to its parent and grandparent
     (grandparent gets a discounted share) -- this is the classic
     Readability trick for finding the *container* that wraps the bulk
     of the real content, even if the actual text sits in a deeply
     nested <p> soup.
  4. Pick the highest-scoring container. If the top two candidates are
     close and structurally adjacent (siblings), merge them.
  5. Clean the winning container: drop child elements that match a
     noise-keyword blocklist (comments, related/recommended lists,
     share widgets, breadcrumbs, prev/next-chapter nav clusters, ads).
  6. Detect the title via <h1>/<h2> near the top of the container, else
     fall back to <title>, stripped of common " - SiteName" suffixes.
  7. Compute a confidence score from density, dominance over runner-up
     candidates, and link density of the final text.

Only dependency: BeautifulSoup4 (+ lxml parser) and `requests` (only used
by the optional URL-fetching test harness).
"""

from __future__ import annotations

import re
import sys
import json
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup
from bs4.element import Tag, NavigableString


# --------------------------------------------------------------------------
# Tunable constants
# --------------------------------------------------------------------------

# Tags we never want to consider as content at all -- ripped out immediately.
JUNK_TAGS = {
    "script", "style", "noscript", "iframe", "svg", "form", "button",
    "input", "select", "textarea", "canvas", "video", "audio", "object",
    "embed", "template",
}
# NOTE: <head> is deliberately NOT in JUNK_TAGS -- we need soup.title to
# survive preprocessing so detect_title() can fall back to it. We operate
# on soup.body for scoring/extraction anyway, so a lingering <head> never
# pollutes the content search.

# Structural tags that are *never* content chrome by nature but are also
# never themselves "the" content container (we still score their children).
STRUCTURAL_SKIP = {"nav", "footer", "header", "aside"}

# Tags eligible to be scored as "content containers".
CONTAINER_TAGS = {"div", "section", "article", "main", "td", "body"}

# Tags eligible to be scored as "content leaves" (where actual prose lives).
LEAF_TAGS = {"p", "pre", "blockquote"}

# Class/id keyword hints that a container IS the reader content.
# Matched as substrings (case-insensitive) against class+id combined.
GOOD_HINTS = [
    "chapter-content", "chapter_content", "chaptercontent",
    "article-content", "article_content", "articlecontent",
    "read-content", "readcontent", "read_content",
    "booktxt", "book-txt", "book_txt",
    "entry-content", "entrycontent",
    "post-content", "postcontent",
    "novel-content", "novelcontent",
    "txt", "txtcontent", "content-text", "contenttext",
    "story", "storytext",
    "content",  # weakest/most generic hint, listed last on purpose
]

# Class/id/tag keyword blocklist -- things to strip out of (or never pick
# as) the content container. English + common Chinese equivalents.
NOISE_KEYWORDS = [
    # English
    "comment", "disqus", "recommend", "related", "sidebar", "nav",
    "navbar", "breadcrumb", "share", "sharing", "social", "advertisement",
    "advert", "ads", "banner", "footer", "header", "menu", "widget",
    "popup", "modal", "cookie", "subscribe", "newsletter", "promo",
    "pagination", "pager", "toolbar", "tag-list", "taglist", "author-note",
    "authornote", "tips", "warning-box", "copyright", "declaration",
    # Chinese
    "推荐", "评论", "相关", "上一章", "下一章", "目录", "书签", "广告",
    "版权", "声明", "作者", "书评", "排行", "热门",
]

# Prev/next chapter navigation link clusters -- we still want to *find*
# these (useful for the app's own navigation), just not include them in
# the TTS text. Kept as a separate signal from the general noise list.
CHAPTER_NAV_HINTS = [
    "prev", "next", "上一章", "下一章", "上一页", "下一页", "目录",
    "chapter-nav", "chapternav", "chapter_nav",
]

# Minimum length (in "content chars", see char_count()) for a text run to
# count as a real paragraph rather than a UI label / stray fragment.
MIN_PARAGRAPH_CHARS = 20

# Regex for counting "content characters" for scoring: Latin letters,
# digits, and CJK ideographs/kana/hangul. Punctuation and whitespace are
# excluded from the *score* but always preserved in the *output* text.
# NOTE: Python's re \w with default (unicode) flags already matches CJK,
# but we spell the ranges out explicitly so the intent is unambiguous and
# so we don't accidentally count underscores etc.
CONTENT_CHAR_RE = re.compile(
    r"["
    r"a-zA-Z0-9"
    r"\u4e00-\u9fff"    # CJK Unified Ideographs
    r"\u3400-\u4dbf"    # CJK Extension A
    r"\uf900-\ufaff"    # CJK Compatibility Ideographs
    r"\u3040-\u30ff"    # Hiragana + Katakana
    r"\uac00-\ud7af"    # Hangul syllables
    r"]"
)

# Common "site name" separators used in <title> tags, e.g.
# "Chapter 12: The Duel - MyNovelSite" or "第12章_XX小说网"
TITLE_SEPARATORS = re.compile(r"\s*[-_|–—丨]\s*|\s*[（(].*?[)）]\s*$")


def char_count(text: str) -> int:
    """Language-agnostic content-character count (see CONTENT_CHAR_RE)."""
    return len(CONTENT_CHAR_RE.findall(text or ""))


def class_id_string(tag: Tag) -> str:
    classes = tag.get("class") or []
    cid = tag.get("id") or ""
    return (" ".join(classes) + " " + cid).lower()


def matches_any(haystack: str, keywords: list[str]) -> bool:
    return any(kw in haystack for kw in keywords)


# --------------------------------------------------------------------------
# Result container
# --------------------------------------------------------------------------

@dataclass
class ExtractionResult:
    title: str
    content: str
    confidence: float
    # Extra, optional context useful for the Android app but not required
    # by the spec's minimal {title, content, confidence} shape.
    prev_chapter_href: Optional[str] = None
    next_chapter_href: Optional[str] = None
    debug: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "content": self.content,
            "confidence": self.confidence,
            "prev_chapter_href": self.prev_chapter_href,
            "next_chapter_href": self.next_chapter_href,
        }


# --------------------------------------------------------------------------
# Step 1: preprocessing
# --------------------------------------------------------------------------

def preprocess(soup: BeautifulSoup) -> None:
    """Strip tags that can never be content, in place."""
    for tag in soup.find_all(JUNK_TAGS):
        tag.decompose()
    # HTML comments (often used to wrap ad slots / tracking snippets)
    for comment in soup.find_all(string=lambda s: s.__class__.__name__ == "Comment"):
        comment.extract()


# --------------------------------------------------------------------------
# Step 2-3: leaf scoring + propagation (Readability-style)
# --------------------------------------------------------------------------

def link_density(tag: Tag) -> float:
    """Fraction of this tag's content characters that live inside <a> tags.
    High link density => nav menu / recommended-list / share widget, not prose.
    """
    total = char_count(tag.get_text())
    if total == 0:
        return 0.0
    link_chars = sum(char_count(a.get_text()) for a in tag.find_all("a"))
    return min(1.0, link_chars / total)


def score_leaf(tag: Tag) -> float:
    """Score a single text-bearing leaf (p/pre/blockquote/div-with-text)."""
    text = tag.get_text()
    n_chars = char_count(text)
    if n_chars < 5:
        return 0.0

    score = 1.0  # base score just for existing as a text node
    # Reward length, but with diminishing returns (cap contribution)
    score += min(n_chars / 100.0, 6.0)
    # Reward sentence-ish punctuation (commas/periods/CJK equivalents)
    # as a weak signal of real prose vs. a UI label.
    punct = len(re.findall(r"[,\uff0c.\u3002;\uff1b]", text))
    score += min(punct / 5.0, 3.0)
    # Penalize high link density heavily -- this is what kills nav/menus
    # and "recommended novels" lists that are just clusters of <a> text.
    score *= (1.0 - link_density(tag)) ** 2
    # Penalize very short text disguised as a "paragraph" (UI chrome like
    # "Reply", "Like", "0 Comments").
    if n_chars < MIN_PARAGRAPH_CHARS:
        score *= 0.3
    # Penalize if the class/id string matches known noise keywords.
    if matches_any(class_id_string(tag), NOISE_KEYWORDS):
        score *= 0.15
    return score


def collect_leaves(root: Tag) -> list[Tag]:
    """Find candidate leaf nodes: <p>/<pre>/<blockquote>, plus <div>/<span>
    that carry direct text (not just via nested block children) -- some
    novel sites (especially Chinese ones) dump chapter text straight into
    <div> nodes separated by <br> instead of using <p> tags.
    """
    leaves: list[Tag] = []
    for tag in root.find_all(True):
        if tag.name in LEAF_TAGS:
            leaves.append(tag)
        elif tag.name in ("div", "span"):
            # "direct text" = at least one NavigableString child with
            # non-trivial content, i.e. this div isn't purely a wrapper
            # around other block elements.
            direct_text = "".join(
                c for c in tag.contents if isinstance(c, NavigableString)
            )
            if char_count(direct_text) >= MIN_PARAGRAPH_CHARS:
                leaves.append(tag)
    return leaves


def score_containers(root: Tag) -> dict[int, float]:
    """Score every element by propagating leaf scores up to parent and
    grandparent, exactly like Readability.js does. Returns {id(tag): score}
    alongside a lookup we rebuild by tag identity.
    """
    scores: dict[int, float] = {}
    tag_by_id: dict[int, Tag] = {}

    leaves = collect_leaves(root)
    for leaf in leaves:
        s = score_leaf(leaf)
        if s <= 0:
            continue

        # The leaf's own container is usually its parent (for <p> inside
        # a wrapping <div>), so we credit parent fully and grandparent
        # at half weight -- this lets the real "chapter-content" div win
        # even if individual <p> tags don't carry class hints themselves.
        parent = leaf.parent
        grandparent = parent.parent if parent else None

        for node, weight in ((parent, 1.0), (grandparent, 0.5)):
            if node is None or not isinstance(node, Tag):
                continue
            if node.name in STRUCTURAL_SKIP:
                continue
            key = id(node)
            tag_by_id[key] = node
            scores[key] = scores.get(key, 0.0) + s * weight

    # Apply container-level bonuses/penalties on top of the propagated score.
    for key, node in tag_by_id.items():
        cid = class_id_string(node)
        if matches_any(cid, GOOD_HINTS):
            # Earlier (more specific) hints in GOOD_HINTS matter more;
            # give a flat bonus for any match, generic "content" already
            # sorted last so it contributes least in practice since more
            # specific containers will already have higher raw scores.
            scores[key] *= 1.4
        if matches_any(cid, NOISE_KEYWORDS):
            scores[key] *= 0.2
        # Fast-path structural bonus: <article> / role=main are strong
        # signals almost every modern reader layout respects.
        if node.name == "article" or node.get("role") == "main":
            scores[key] *= 1.5

    root._novel_extractor_tag_by_id = tag_by_id  # stash for caller
    return scores


# --------------------------------------------------------------------------
# Step 4: pick winner (+ sibling-merge fallback)
# --------------------------------------------------------------------------

def pick_best_container(root: Tag) -> tuple[Optional[Tag], float, float]:
    """Returns (winning_tag, winning_score, runner_up_score)."""
    scores = score_containers(root)
    tag_by_id = getattr(root, "_novel_extractor_tag_by_id", {})
    if not scores:
        return None, 0.0, 0.0

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_key, best_score = ranked[0]
    runner_up_score = ranked[1][1] if len(ranked) > 1 else 0.0
    best_tag = tag_by_id[best_key]

    # Fallback: if the winner barely beats the runner-up AND they're
    # siblings, merge them into a synthetic wrapper -- this handles sites
    # that split chapter text across two adjacent divs (e.g. a "part 1"/
    # "part 2" split around an inline ad).
    if runner_up_score > 0 and best_score / max(runner_up_score, 1e-6) < 1.3:
        runner_key = ranked[1][0]
        runner_tag = tag_by_id[runner_key]
        if (
            best_tag.parent is not None
            and runner_tag.parent is not None
            and best_tag.parent is runner_tag.parent
        ):
            wrapper = BeautifulSoup("<div></div>", "lxml").div
            # Move copies (not originals) into the wrapper so we don't
            # mutate the live tree order.
            import copy
            wrapper.append(copy.copy(best_tag))
            wrapper.append(copy.copy(runner_tag))
            return wrapper, best_score + runner_up_score, 0.0

    return best_tag, best_score, runner_up_score


# --------------------------------------------------------------------------
# Step 5: clean the winning container
# --------------------------------------------------------------------------

def extract_chapter_nav(container: Tag) -> tuple[Optional[str], Optional[str]]:
    """Pull out prev/next chapter links before we strip nav clusters, so the
    app can still offer chapter navigation even though this text is excluded
    from the TTS body.
    """
    prev_href = next_href = None
    for a in container.find_all("a", href=True):
        label = (a.get_text() or "").strip().lower()
        cid = class_id_string(a)
        combined = label + " " + cid
        if "next" in combined or "下一" in combined:
            next_href = next_href or a["href"]
        elif "prev" in combined or "上一" in combined:
            prev_href = prev_href or a["href"]
    return prev_href, next_href


def clean_container(container: Tag) -> Tag:
    """Strip noise-keyword elements and high-link-density junk out of the
    winning container, in place. Returns the same container for chaining.
    """
    for tag in list(container.find_all(True)):
        # A tag may already have been decomposed (removed from the tree)
        # earlier in this same loop, e.g. as a descendant of a noise
        # element we already dropped. Skip it in that case.
        if tag.parent is None:
            continue
        if tag.name in JUNK_TAGS or tag.name in STRUCTURAL_SKIP:
            tag.decompose()
            continue
        cid = class_id_string(tag)
        if matches_any(cid, NOISE_KEYWORDS) or matches_any(cid, CHAPTER_NAV_HINTS):
            tag.decompose()
            continue
        # Kill link-farm elements: short text, mostly links (e.g. a
        # "recommended novels" tile grid or breadcrumb trail).
        text_len = char_count(tag.get_text())
        if text_len > 0 and text_len < 200 and link_density(tag) > 0.6:
            tag.decompose()
    return container


# --------------------------------------------------------------------------
# Step 6: title detection
# --------------------------------------------------------------------------

def clean_title_from_page_title(raw: str) -> str:
    """Strip common ' - SiteName' / '_XX小说网' suffixes from <title> text."""
    parts = TITLE_SEPARATORS.split(raw)
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return raw.strip()
    # Heuristic: the chapter title segment is usually the longest chunk,
    # or the first chunk if lengths are close (site name is often last).
    parts.sort(key=len, reverse=True)
    return parts[0]


def detect_title(soup: BeautifulSoup, container: Tag) -> str:
    # Prefer an h1/h2 inside (or immediately preceding) the content container.
    heading = container.find(["h1", "h2"])
    if heading and char_count(heading.get_text()) >= 2:
        return heading.get_text(strip=True)

    prev_heading = None
    prev = container.find_previous_sibling(["h1", "h2"])
    if prev:
        prev_heading = prev
    if prev_heading and char_count(prev_heading.get_text()) >= 2:
        return prev_heading.get_text(strip=True)

    # Fall back to the document <title>.
    if soup.title and soup.title.string:
        return clean_title_from_page_title(soup.title.string)

    return "Untitled Chapter"


# --------------------------------------------------------------------------
# Step 7: confidence scoring
# --------------------------------------------------------------------------

def compute_confidence(
    best_score: float,
    runner_up_score: float,
    content_chars: int,
    page_chars: int,
    final_link_density: float,
    used_good_hint: bool,
) -> float:
    """Blend several weak signals into a single 0..1 confidence estimate."""
    if content_chars < 50:
        return 0.05  # basically nothing usable was found

    # 1) Dominance: how much the winner beat the runner-up by. A landslide
    #    win is a strong signal we found "the" content block, not just
    #    the biggest of several similar blocks.
    dominance = 1.0 - min(runner_up_score / max(best_score, 1e-6), 1.0)

    # 2) Reasonable extraction ratio: real chapter text is usually a
    #    meaningful chunk of the page but rarely the *entire* page (which
    #    would suggest we failed to strip chrome and just grabbed <body>).
    ratio = content_chars / max(page_chars, 1)
    if ratio > 0.95:
        ratio_score = 0.3  # suspicious: probably swallowed the whole page
    else:
        # Sweet spot roughly 5%-70% of page characters.
        ratio_score = 1.0 - abs(ratio - 0.35) / 0.65
        ratio_score = max(0.0, min(1.0, ratio_score))

    # 3) Low link density in the final text is good (real prose isn't
    #    made of links).
    link_score = 1.0 - final_link_density

    # 4) Bonus if a recognizable CMS/reader class hint was involved.
    hint_score = 1.0 if used_good_hint else 0.6

    confidence = (
        0.35 * dominance
        + 0.25 * ratio_score
        + 0.25 * link_score
        + 0.15 * hint_score
    )
    return round(max(0.0, min(1.0, confidence)), 3)


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def extract(html: str, url: Optional[str] = None) -> ExtractionResult:
    soup = BeautifulSoup(html, "lxml")
    page_chars = char_count(soup.get_text())
    preprocess(soup)

    root = soup.body or soup

    # Fast path: an <article> or role="main" that already looks like real
    # prose (decent length, low link density) short-circuits the full
    # scoring pass.
    fast_candidate = root.find("article") or root.find(attrs={"role": "main"})
    if fast_candidate and char_count(fast_candidate.get_text()) > 200:
        if link_density(fast_candidate) < 0.4:
            container = clean_container(fast_candidate)
            prev_href, next_href = extract_chapter_nav(fast_candidate)
            title = detect_title(soup, container)
            content = get_display_text(container)
            confidence = compute_confidence(
                best_score=1.0,
                runner_up_score=0.0,
                content_chars=char_count(content),
                page_chars=page_chars,
                final_link_density=link_density(container),
                used_good_hint=True,
            )
            return ExtractionResult(
                title=title,
                content=content,
                confidence=confidence,
                prev_chapter_href=prev_href,
                next_chapter_href=next_href,
                debug={"path": "fast-path-article"},
            )

    best_tag, best_score, runner_up_score = pick_best_container(root)
    if best_tag is None:
        # Total failure -- nothing scoreable. Return the raw body text as
        # a last-resort fallback with near-zero confidence so the app
        # knows to prompt manual selection or show the raw page.
        fallback_text = get_display_text(root)
        return ExtractionResult(
            title=detect_title(soup, root),
            content=fallback_text,
            confidence=0.05,
            debug={"path": "total-fallback"},
        )

    prev_href, next_href = extract_chapter_nav(best_tag)
    container = clean_container(best_tag)
    title = detect_title(soup, container)
    content = get_display_text(container)

    used_good_hint = matches_any(class_id_string(best_tag), GOOD_HINTS)
    confidence = compute_confidence(
        best_score=best_score,
        runner_up_score=runner_up_score,
        content_chars=char_count(content),
        page_chars=page_chars,
        final_link_density=link_density(container),
        used_good_hint=used_good_hint,
    )

    return ExtractionResult(
        title=title,
        content=content,
        confidence=confidence,
        prev_chapter_href=prev_href,
        next_chapter_href=next_href,
        debug={
            "path": "scored",
            "best_score": round(best_score, 2),
            "runner_up_score": round(runner_up_score, 2),
        },
    )


def get_display_text(container: Tag) -> str:
    """Render the cleaned container back to plain text, preserving
    paragraph breaks (this is what actually gets read out by TTS).
    Punctuation/whitespace is preserved here even though it was excluded
    from *scoring* -- scoring and output are deliberately decoupled.
    """
    # Convert <br> to newlines before extracting text, since many CJK
    # novel sites separate paragraphs with <br><br> instead of <p>.
    for br in container.find_all("br"):
        br.replace_with("\n")

    block_tags = LEAF_TAGS | {"div", "h1", "h2", "h3", "h4"}
    lines: list[str] = []
    for el in container.find_all(True):
        if el.name in block_tags:
            # Only take direct/leaf-level text to avoid duplicating text
            # that also belongs to a nested paragraph we'll visit next.
            if el.find(list(block_tags - {"div"})):
                continue  # has block children; let those emit instead
            text = el.get_text(separator=" ", strip=True)
            text = re.sub(r"[ \t]+", " ", text)
            if char_count(text) >= 3:
                lines.append(text)

    if not lines:
        # Nothing matched the block-tag walk (e.g. content was bare text
        # nodes directly under the container) -- fall back to raw get_text.
        raw = container.get_text(separator="\n", strip=True)
        lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]

    # De-duplicate consecutive identical lines (common artifact of nested
    # wrapper divs both matching the block-tag walk).
    deduped: list[str] = []
    for ln in lines:
        if not deduped or deduped[-1] != ln:
            deduped.append(ln)

    return "\n\n".join(deduped)


# --------------------------------------------------------------------------
# Test harness
# --------------------------------------------------------------------------

def _load_html(source: str) -> str:
    """Load HTML from a local file path or, if it looks like a URL, fetch it."""
    if source.startswith("http://") or source.startswith("https://"):
        import requests
        resp = requests.get(source, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; NovelExtractorTester/1.0)"
        })
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding
        return resp.text
    with open(source, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def run_test_harness(sources: list[str]) -> None:
    """Given a list of local HTML file paths or URLs, run extraction on each
    and print title/content-preview/confidence so results can be eyeballed.
    """
    for src in sources:
        print("=" * 80)
        print(f"SOURCE: {src}")
        try:
            html = _load_html(src)
        except Exception as e:
            print(f"  !! failed to load: {e}")
            continue

        result = extract(html, url=src if src.startswith("http") else None)
        preview = result.content[:400].replace("\n", " ⏎ ")
        print(f"  TITLE      : {result.title}")
        print(f"  CONFIDENCE : {result.confidence}")
        print(f"  CHARS      : {char_count(result.content)}")
        print(f"  PREV/NEXT  : {result.prev_chapter_href} / {result.next_chapter_href}")
        print(f"  DEBUG      : {result.debug}")
        print(f"  PREVIEW    : {preview}...")
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python novel_extractor.py <html_file_or_url> [more...]")
        print("       python novel_extractor.py --json <html_file_or_url>")
        sys.exit(1)

    args = sys.argv[1:]
    as_json = False
    if args[0] == "--json":
        as_json = True
        args = args[1:]

    if as_json:
        html = _load_html(args[0])
        result = extract(html, url=args[0] if args[0].startswith("http") else None)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        run_test_harness(args)
