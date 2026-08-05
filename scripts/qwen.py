#!/usr/bin/env python3
"""
novel_extractor.py

Generic chapter-text extractor for arbitrary novel-reading websites.

Purpose:
    Given raw HTML from an unknown novel site, extract only:
        - chapter title
        - chapter body text

    and strip out:
        - navigation
        - ads
        - comments
        - recommended novels
        - author notes
        - prev/next chapter clusters
        - site chrome / boilerplate

Output:
    {
        "title": str,
        "content": str,
        "confidence": float  # 0.0..1.0
    }

Dependencies:
    pip install beautifulsoup4 lxml requests

Usage:
    python novel_extractor.py saved_chapter.html
    python novel_extractor.py https://example.com/chapter-1.html
    python novel_extractor.py file_english.html file_chinese.html --preview 800
    python novel_extractor.py https://example.com/chapter.html --json

Design notes:
    This is intentionally heuristic, not a scraper for one fixed site.
    The scoring logic is inspired by Readability-style content extraction:
        - text density
        - paragraph density
        - link density penalty
        - short-node penalty
        - class/id hints as soft signals only
        - structural fast paths for <article> and role="main"
"""

import argparse
import json
import math
import re
import sys
from collections import namedtuple
from pathlib import Path
from urllib.parse import urlparse

try:
    from bs4 import BeautifulSoup, Comment, NavigableString, Tag
except ImportError:
    sys.exit(
        "BeautifulSoup4 is required.\n"
        "Install with: pip install beautifulsoup4 lxml"
    )

# Optional, only needed if you want the harness to fetch live URLs.
try:
    import requests
except ImportError:
    requests = None


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

Candidate = namedtuple("Candidate", "score tag feat")


# ---------------------------------------------------------------------------
# Regex / keyword configuration
#
# These are generic hints, not per-site rules.
# Tune carefully over time.
# ---------------------------------------------------------------------------

# Collapse whitespace for normalized visible text.
_WS_RE = re.compile(r"\s+", re.UNICODE)

# Used only for SCORING.
# Removes punctuation/symbols and underscore so English and Chinese are both
# scored by meaningful characters, not whitespace-delimited words.
# Final extracted output is NOT passed through this; punctuation is preserved.
_SCORING_STRIP_RE = re.compile(r"[^\w\s]|_", re.UNICODE)

# Soft positive class/id hints.
# These are hints only. A block can still win without them.
HINT_ATTR_RE = re.compile(
    r"chapter|content|article|entry|post|text|body|read|reader|story|fiction|novel|book|txt|main|bq|contents|"
    r"chaptercontent|readcontent|booktxt|novelcontent|entry-content|article-content|chapter-content|book-content|"
    r"story-content|fiction-content|main-content|post-content|entry-body|article-body|story-body|chapter-body|"
    r"txtcontent|noveltext|booktext|chaptertext|readtext|fictiontext|storytext|"
    r"内容|章节|正文|小说|阅读",
    re.I,
)

# Soft negative class/id hints.
# Applied as penalties during scoring and as removal hints during cleaning.
NEGATIVE_ATTR_RE = re.compile(
    r"comment|reply|replies|recommend|related|popular|hot|ranking|rank|nav|menu|footer|sidebar|widget|share|social|"
    r"advert|adsense|banner|promo|sponsor|disqus|breadcrumb|pagination|pager|\bprev(ious)?\b|\bnext\b|chapter-nav|"
    r"author|note|footnote|copyright|toc|directory|catalog|bookmark|vote|donate|reward|tip|login|register|search|subscribe|"
    r"(?<![A-Za-z0-9_])ad[s_.-]?|"
    r"评论|回复|推荐|相关|热门|排行|导航|菜单|页脚|页眉|侧边|分享|广告|版权|声明|目录|书架|加入书签|打赏|投票|上一章|下一章|作者有话说|作者说|书友|互动|登录|注册|搜索|订阅",
    re.I,
)

# Used for removing small UI-like text blocks after candidate selection.
# This is intentionally conservative: it mostly matches whole labels.
NEGATIVE_LABEL_RE = re.compile(
    r"^\s*[«»<>\[\]【】「」『』\s]*("
    r"上一章|下一章|前一章|后一章|目录|书架|加入书签|推荐本书|推荐|相关推荐|推荐阅读|评论|打赏|投票|分享|广告|作者有话说|作者说|版权声明|免责声明|"
    r"prev(?:ious)?\s*chapter|next\s*chapter|previous\s*chapter|table\s*of\s*contents|"
    r"recommended(?:\s*(?:novels?|books?|chapters?|reading))?|"
    r"related\s*(?:novels?|books?|chapters?)?|"
    r"comments?(?:\s*\(\d+\))?|"
    r"share(?:\s*(?:this|on|to))?|"
    r"donate|bookmark|advertisement"
    r")[»<>\[\]【】「」『』\s\d.:：,，!！?？_-]*$",
    re.I,
)

# Helps prefer headings that look like chapter titles.
CHAPTER_TITLE_RE = re.compile(
    r"\b(?:chapter|chap|episode|part|section|book|volume|prologue|epilogue)\s*[\dIVXLCDM]+|"
    r"第\s*[0-9〇零一二三四五六七八九十百千两\d]+\s*[章节卷回部集篇]|"
    r"^\s*\d+\s*[\.、]\s*|"
    r"^\s*[IVXLCDM]+\s*[:.、]?\s*$",
    re.I,
)

# Hidden-element detection.
# Avoid matching responsive helpers like "hidden-xs" by requiring no extra
# word character or hyphen immediately before/after the token.
STYLE_HIDDEN_RE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)
HIDDEN_RE = re.compile(
    r"(?<![\w-])(hidden|sr-only|visually-hidden|display-none)(?![\w-])",
    re.I,
)

# Title cleanup: split common title separators.
# If no site-like suffix is removed, the original title is preserved as-is.
TITLE_SEP_RE = re.compile(r"\s*[\|｜]\s*|\s*[-–—]\s*|\s*[:：]\s*|\s*_+\s*")

# Generic site-like suffixes for <title> cleanup.
SITEISH_END_RE = re.compile(
    r"(novels?|read(?:ing|er)?|books?|fictions?|stor(?:y|ies)|web|site|home|online|free|latest|txt|download|app|official|portal|hub|zone|space|club|net|org)$",
    re.I,
)
SITEISH_CN_END_RE = re.compile(
    r"(小说|阅读|阅读器|章节|正文|网|书屋|书城|文学|在线|免费|最新|书网|书斋)$"
)

# Generic host tokens to ignore when cleaning <title>.
# Not domain-specific rules; just common non-content host fragments.
GENERIC_HOST_TOKENS = {
    "www", "m", "wap", "app", "blog", "html", "php", "asp", "aspx", "jsp",
    "cgi", "com", "org", "net", "edu", "gov", "io", "co", "us", "uk", "cc",
    "top", "xyz", "vip", "club", "site", "online", "store", "dev", "test",
    "localhost", "127", "0",
}

# Tags that are almost never useful for TTS chapter text.
NON_TEXT_TAGS = [
    "script", "style", "noscript", "template", "iframe", "svg", "math",
    "canvas", "audio", "video", "object", "embed", "form", "button",
    "input", "select", "textarea", "label", "option", "datalist", "dialog",
    "img", "picture", "source", "hr", "track", "map", "area", "frame",
    "frameset", "applet",
]

# Candidate container tags for density scoring.
CANDIDATE_TAGS = [
    "div", "section", "article", "main", "td", "center", "body",
]

# Block-like tags used when converting the selected root into final text.
TEXT_BLOCK_TAGS = [
    "p", "div", "section", "article", "main", "blockquote", "pre", "li",
    "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "figure", "figcaption",
    "dd", "dt",
]

# During final cleaning, remove these descendants from the selected block.
CLEAN_REMOVE_TAGS = NON_TEXT_TAGS + ["nav", "footer", "header", "aside"]


# ---------------------------------------------------------------------------
# Small text helpers
# ---------------------------------------------------------------------------

def _norm(s):
    """Normalize whitespace for display/text comparison."""
    if s is None:
        return ""
    return _WS_RE.sub(" ", str(s)).strip()


def _scoring_len(s):
    """
    Language-agnostic scoring length.

    Uses character count after removing whitespace and punctuation.
    This avoids word-count bias against Chinese, which has no spaces.
    """
    if not s:
        return 0
    s = _SCORING_STRIP_RE.sub("", s)
    s = _WS_RE.sub("", s)
    return len(s)


def _attr_text(tag):
    """
    Concatenate useful attribute values for class/id heuristic matching.
    Lowercased.
    """
    if not isinstance(tag, Tag):
        return ""

    parts = []
    for attr_name in (
        "id",
        "class",
        "role",
        "aria-label",
        "title",
        "itemprop",
        "data-type",
        "data-module",
        "data-component",
        "data-name",
        "data-action",
    ):
        value = tag.get(attr_name)
        if not value:
            continue
        if isinstance(value, list):
            value = " ".join(str(x) for x in value)
        parts.append(str(value))

    return " ".join(parts).lower()


def _is_hidden(tag):
    """
    Heuristic for hidden UI elements.
    Hidden elements are usually not the main chapter text.
    """
    if not isinstance(tag, Tag):
        return False

    style = tag.get("style") or ""
    if isinstance(style, list):
        style = " ".join(style)

    if STYLE_HIDDEN_RE.search(style):
        return True

    if str(tag.get("aria-hidden", "")).lower() == "true":
        return True

    if tag.has_attr("hidden"):
        return True

    attrs = _attr_text(tag)
    if HIDDEN_RE.search(attrs):
        return True

    return False


# ---------------------------------------------------------------------------
# Parsing and preprocessing
# ---------------------------------------------------------------------------

def _parse_soup(markup):
    """
    Parse HTML bytes or string.
    Prefer lxml if available; fall back to Python's html.parser.
    """
    try:
        return BeautifulSoup(markup, "lxml")
    except Exception:
        return BeautifulSoup(markup, "html.parser")


def _strip_for_scoring(soup):
    """
    Remove elements that should not contribute to scoring:
        - scripts/styles
        - embedded media/forms
        - comments
        - hidden elements

    This does NOT remove nav/footer/aside/header here; those are penalized
    by scoring and removed later inside the selected content block.
    """
    # Remove HTML comments.
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # Remove non-text/UI tags.
    for tag in soup.find_all(NON_TEXT_TAGS):
        tag.decompose()

    # Remove hidden elements.
    # Convert to list first because decompose mutates the tree.
    for tag in soup.find_all(True):
        if isinstance(tag, Tag) and _is_hidden(tag):
            tag.decompose()


# ---------------------------------------------------------------------------
# Feature extraction and scoring
# ---------------------------------------------------------------------------

def _element_features(tag, text=None, chars=None):
    """
    Compute heuristic features for one candidate container.

    Important signals:
        - chars: punctuation-stripped character count
        - density: chars / descendant tag count
        - p_ratio: how much text is inside <p>
        - link_density: how much text is inside <a>
        - long_run_ratio: long consecutive text chunks
        - short_string_ratio: many short UI-like strings
        - attr hints: positive/negative class/id patterns
    """
    if text is None:
        text = _norm(tag.get_text(" ", strip=True))
    if chars is None:
        chars = _scoring_len(text)

    all_tags = tag.find_all(True)
    tag_count = len(all_tags) + 1

    # Link text is usually navigation/recommendations, not prose.
    link_chars = 0
    for a in tag.find_all("a"):
        link_chars += _scoring_len(_norm(a.get_text(" ", strip=True)))
    link_density = link_chars / chars if chars else 1.0

    # Paragraphs are a strong prose signal.
    p_tags = tag.find_all("p")
    p_chars = 0
    for p in p_tags:
        p_chars += _scoring_len(_norm(p.get_text(" ", strip=True)))
    p_ratio = p_chars / chars if chars else 0.0
    p_count = len(p_tags)
    avg_p = p_chars / p_count if p_count else 0.0

    # Text-node/run statistics.
    # This helps sites that use <br> instead of <p>.
    string_lens = []
    for s in tag.stripped_strings:
        string_lens.append(_scoring_len(s))

    total_strings = len(string_lens)
    short_strings = sum(1 for length in string_lens if 0 < length <= 30)
    long_run_chars = sum(length for length in string_lens if length >= 60)

    short_string_ratio = short_strings / total_strings if total_strings else 0.0
    long_run_ratio = long_run_chars / chars if chars else 0.0

    # Attribute hints.
    attrs = _attr_text(tag)
    hint = bool(HINT_ATTR_RE.search(attrs))
    negative = bool(NEGATIVE_ATTR_RE.search(attrs))

    # A parent hint can help when the real container is an unclassed inner div.
    parent_hint = False
    if tag.parent is not None and isinstance(tag.parent, Tag):
        parent_hint = bool(HINT_ATTR_RE.search(_attr_text(tag.parent)))

    density = chars / tag_count if tag_count else 0.0

    return {
        "chars": chars,
        "tag_count": tag_count,
        "density": density,
        "link_chars": link_chars,
        "link_density": link_density,
        "p_chars": p_chars,
        "p_ratio": p_ratio,
        "p_count": p_count,
        "avg_p": avg_p,
        "long_run_chars": long_run_chars,
        "long_run_ratio": long_run_ratio,
        "short_string_ratio": short_string_ratio,
        "hint": hint,
        "negative": negative,
        "parent_hint": parent_hint,
    }


def _score_tag(tag, text=None, chars=None):
    """
    Score a candidate container.

    Higher score means more likely to be main chapter content.
    """
    feat = _element_features(tag, text=text, chars=chars)

    # Ignore very small blocks as main content candidates.
    if feat["chars"] < 60:
        return 0.0, feat

    score = feat["density"]

    # Reward larger blocks, but sublinearly.
    score *= math.log10(feat["chars"] + 10)

    # Reward paragraph-heavy blocks.
    score *= 1.0 + min(feat["p_ratio"], 1.0) * 1.5

    # Reward long average paragraph length.
    if feat["avg_p"] >= 80:
        score *= 1.15
    if feat["avg_p"] >= 200:
        score *= 1.15

    # Reward having multiple paragraphs, capped.
    score *= 1.0 + min(feat["p_count"], 30) * 0.02

    # Reward long text runs even when <p> is not used.
    score *= 1.0 + min(feat["long_run_ratio"], 1.0) * 0.6

    # Penalize link-heavy blocks hard.
    # Nav bars, recommended lists, prev/next clusters are link-heavy.
    link_density = min(1.0, feat["link_density"])
    if link_density > 0:
        score *= max(0.05, (1.0 - link_density) ** 2)

    # Penalize many short strings.
    # This helps comment threads, menus, labels, UI widgets.
    short_ratio = min(1.0, feat["short_string_ratio"])
    if feat["p_ratio"] < 0.4:
        score *= max(0.3, 1.0 - short_ratio * 0.7)
    else:
        # If it is very paragraph-heavy, be gentler.
        score *= max(0.6, 1.0 - short_ratio * 0.3)

    # Structural tag bonuses/penalties.
    if tag.name in ("article", "main"):
        score *= 1.6
    elif tag.name == "section":
        score *= 1.05
    elif tag.name == "div":
        score *= 1.0
    elif tag.name == "td":
        score *= 0.85
    elif tag.name == "body":
        score *= 0.75
    else:
        score *= 0.6

    # Attribute hints.
    if feat["hint"]:
        score *= 1.5
    if feat["parent_hint"]:
        score *= 1.1
    if feat["negative"]:
        score *= 0.25

    # Extra structural penalties.
    if tag.name in ("nav", "footer", "aside"):
        score *= 0.2
    if tag.name == "header":
        score *= 0.5

    return score, feat


def _collect_candidates(soup):
    """
    Collect and score candidate containers.
    """
    candidates = []

    root = soup.body or soup.find("html") or soup
    tags = soup.find_all(CANDIDATE_TAGS)

    # Make sure we always consider the root/body as a fallback candidate.
    if not any(tag is root for tag in tags):
        tags.append(root)

    for tag in tags:
        if not isinstance(tag, Tag):
            continue

        text = _norm(tag.get_text(" ", strip=True))
        chars = _scoring_len(text)
        if chars < 60:
            continue

        score, feat = _score_tag(tag, text=text, chars=chars)
        if score > 0:
            candidates.append(Candidate(score=score, tag=tag, feat=feat))

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def _fast_path_candidates(soup):
    """
    Fast-path semantic checks:
        - <article>
        - <main>
        - role="main"

    These are strong signals, but still scored and compared against the
    general density candidates.
    """
    tags = soup.find_all(["article", "main"])

    for tag in soup.find_all(attrs={"role": "main"}):
        if not any(tag is existing for existing in tags):
            tags.append(tag)

    out = []
    for tag in tags:
        if not isinstance(tag, Tag):
            continue

        text = _norm(tag.get_text(" ", strip=True))
        chars = _scoring_len(text)
        if chars < 120:
            continue

        score, feat = _score_tag(tag, text=text, chars=chars)

        # Only fast-path semantic containers that do not look link-heavy.
        if feat["link_density"] <= 0.35 and not feat["negative"] and score > 0:
            out.append(Candidate(score=score, tag=tag, feat=feat))

    out.sort(key=lambda c: c.score, reverse=True)
    return out


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------

def _is_ancestor(node, possible_ancestor):
    """Return True if possible_ancestor is an ancestor of node."""
    parent = getattr(node, "parent", None)
    while parent is not None:
        if parent is possible_ancestor:
            return True
        parent = parent.parent
    return False


def _related(a, b):
    """Return True if two tags are the same or one contains the other."""
    if a is b:
        return True
    return _is_ancestor(a, b) or _is_ancestor(b, a)


def _structurally_adjacent(tags):
    """
    Very small adjacency check for merge fallback.

    We allow merge if selected blocks share a parent or grandparent.
    This avoids merging random blocks from unrelated page regions.
    """
    if len(tags) < 2:
        return True

    parents = {tag.parent for tag in tags if tag.parent is not None}
    if len(parents) == 1:
        return True

    grandparents = {
        tag.parent.parent
        for tag in tags
        if tag.parent is not None and tag.parent.parent is not None
    }
    return len(grandparents) == 1


def _choose_selection(candidates):
    """
    Choose either:
        - one dominant candidate
        - a merged set of adjacent strong candidates

    Returns:
        (selection_list, mode, margin)
        mode is "single", "merged", or "none"
    """
    if not candidates:
        return [], "none", 1.0

    best = candidates[0]

    # Prefer a more specific descendant if it is almost as strong as a wrapper.
    # Example:
    #   <div class="content">       <- high score because of class hint
    #       <div id="chaptertext">  <- actually cleaner
    for cand in candidates[1:12]:
        if cand.score >= best.score * 0.90 and _is_ancestor(cand.tag, best.tag):
            if cand.feat["chars"] >= best.feat["chars"] * 0.65:
                best = cand
                break

    remaining = [c for c in candidates if c.tag is not best.tag]

    # For margin, prefer comparing against an unrelated candidate.
    unrelated = [
        c for c in candidates
        if c.tag is not best.tag and not _related(c.tag, best.tag)
    ]
    second = unrelated[0] if unrelated else (remaining[0] if remaining else None)

    if second and best.score:
        margin = (best.score - second.score) / best.score
        margin = max(0.0, min(1.0, margin))
    else:
        margin = 1.0

    # Merge fallback:
    # If no single block is dominant, merge multiple strong adjacent blocks.
    if best.feat["chars"] < 300 or margin < 0.25:
        strong = [
            c for c in candidates[:10]
            if c.score >= best.score * 0.35 and c.feat["chars"] >= 80
        ]

        specific = []
        for cand in strong:
            if not any(_related(cand.tag, s.tag) for s in specific):
                specific.append(cand)

        if len(specific) >= 2:
            total_chars = sum(c.feat["chars"] for c in specific)
            tags = [c.tag for c in specific]

            if total_chars > best.feat["chars"] * 1.25 and _structurally_adjacent(tags):
                # Sort roughly by document order.
                specific.sort(key=lambda c: (getattr(c.tag, "sourceline", 0) or 0))
                return specific, "merged", margin

    return [best], "single", margin


def _estimate_confidence(selection, mode, margin):
    """
    Estimate extraction confidence.

    This is intentionally conservative so the Android app can decide whether to:
        - trust extraction
        - fall back to full-page reading
        - ask the user to manually select content
    """
    if not selection:
        return 0.0

    total_chars = sum(c.feat["chars"] for c in selection)
    if total_chars <= 0:
        return 0.0

    total_link_chars = sum(c.feat["link_chars"] for c in selection)
    total_p_chars = sum(c.feat["p_chars"] for c in selection)
    total_long_chars = sum(c.feat["long_run_chars"] for c in selection)

    link_density = min(1.0, total_link_chars / total_chars)
    p_ratio = min(1.0, total_p_chars / total_chars)
    long_ratio = min(1.0, total_long_chars / total_chars)

    # Length component: reaches 1.0 around 1200 scoring chars.
    length_comp = min(1.0, total_chars / 1200.0)

    # Text quality component: paragraph or long-run prose.
    text_comp = 0.35 + 0.65 * min(1.0, max(p_ratio, long_ratio * 0.8))

    # Link penalty.
    link_comp = max(0.0, 1.0 - link_density * 1.5)

    # Dominance/margin component.
    margin_comp = 0.55 + 0.45 * min(1.0, margin * 2.0)

    mode_mult = 1.0 if mode == "single" else 0.75
    negative_mult = 0.7 if any(c.feat["negative"] for c in selection) else 1.0
    hint_mult = 1.05 if any(c.feat["hint"] for c in selection) else 1.0

    confidence = (
        length_comp
        * text_comp
        * link_comp
        * margin_comp
        * mode_mult
        * negative_mult
        * hint_mult
    )

    return max(0.0, min(1.0, confidence))


# ---------------------------------------------------------------------------
# Title detection and cleanup
# ---------------------------------------------------------------------------

def _host_tokens(url):
    """
    Extract useful host tokens for title cleanup.
    Example:
        https://read.novelsite.com/chapter.html
        -> ["read", "novelsite"]
    """
    if not url:
        return []

    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return []

    if not host:
        return []

    tokens = re.split(r"[^a-z0-9\u4e00-\u9fff]+", host)
    return [
        t for t in tokens
        if t and t not in GENERIC_HOST_TOKENS and len(t) > 2
    ]


def _is_siteish_title_part(part, host_tokens):
    """
    Return True if a title segment looks like a site suffix rather than
    the chapter title.

    Examples:
        "NovelSite"
        "Read Novel Online"
        "小说阅读网"
        "example.com"
    """
    low = part.lower()
    chars = _scoring_len(part)

    # Host-token match.
    # Be a little conservative so we do not remove real title words too easily.
    for token in host_tokens:
        if not token:
            continue
        if len(token) >= 4 and re.search(r"\b" + re.escape(token) + r"\b", low):
            return True
        if token in low and chars <= 12:
            return True

    # Generic English site-like suffix.
    if chars <= 25 and SITEISH_END_RE.search(low):
        return True

    # Generic Chinese site-like suffix.
    if chars <= 12 and SITEISH_CN_END_RE.search(part):
        return True

    return False


def _clean_title(raw, url=None):
    """
    Clean a raw title.

    Strategy:
        - split on common separators: | - — _ :
        - remove site-like segments from the ends
        - if nothing site-like was removed, return original raw title
    """
    raw = _norm(raw)
    if not raw:
        return ""

    parts = [p.strip() for p in TITLE_SEP_RE.split(raw) if p.strip()]
    if len(parts) <= 1:
        return raw

    host_tokens = _host_tokens(url)
    work = parts[:]
    changed = False

    # Remove site-like suffixes from the end.
    while work and _is_siteish_title_part(work[-1], host_tokens):
        work.pop()
        changed = True

    # Remove site-like prefixes from the beginning, if still leaving a title.
    while work and len(work) > 1 and _is_siteish_title_part(work[0], host_tokens):
        work.pop(0)
        changed = True

    # If we did not remove anything, preserve the original punctuation/format.
    if not changed:
        return raw

    # If everything looked site-like, keep the longest original segment.
    if not work:
        work = [max(parts, key=_scoring_len)]

    return " - ".join(work)


def _in_negative_container(tag):
    """
    Used by heading scoring to reject headings inside nav/footer/aside or
    strongly negative containers.
    """
    parent = tag.parent
    steps = 0

    while parent is not None and parent.name != "body" and steps < 6:
        if isinstance(parent, Tag):
            if parent.name in ("nav", "footer", "aside"):
                return True

            attrs = _attr_text(parent)
            if NEGATIVE_ATTR_RE.search(attrs) and not HINT_ATTR_RE.search(attrs):
                return True

        parent = parent.parent
        steps += 1

    return False


def _heading_score(tag):
    """
    Score a possible title heading.
    """
    text = _norm(tag.get_text(" ", strip=True))
    chars = _scoring_len(text)

    if chars < 2 or chars > 150:
        return -1.0

    score = float(chars)

    if tag.name == "h1":
        score += 25
    elif tag.name == "h2":
        score += 15
    elif tag.name == "h3":
        score += 8

    attrs = _attr_text(tag)

    if HINT_ATTR_RE.search(attrs):
        score += 20
    if NEGATIVE_ATTR_RE.search(attrs):
        score -= 30

    if CHAPTER_TITLE_RE.search(text):
        score += 40

    if _in_negative_container(tag):
        score -= 60

    return score


def _best_heading(tags):
    """Return best heading tag and its score from an iterable of tags."""
    best = None
    best_score = 0.0

    for tag in tags:
        score = _heading_score(tag)
        if score > best_score:
            best_score = score
            best = tag

    return best, best_score


def _title_from_candidate(candidate, url):
    """
    Try to find a title near the selected content candidate.
    """
    if not candidate:
        return ""

    tag = candidate.tag

    # Headings inside the candidate.
    inside_best, inside_score = _best_heading(tag.find_all(["h1", "h2", "h3"]))

    # Headings immediately before the candidate.
    # Many sites put <h1>Chapter Title</h1> just above the content div.
    prev_best, prev_score = _best_heading(
        tag.find_all_previous(["h1", "h2", "h3"], limit=5)
    )

    if prev_score > inside_score:
        best = prev_best
        score = prev_score
    else:
        best = inside_best
        score = inside_score

    if best is not None and score > 15:
        return _clean_title(best.get_text(" ", strip=True), url)

    return ""


def _title_from_meta(soup, url):
    """
    Use og:title / twitter:title if present.
    """
    for prop in ("og:title", "twitter:title"):
        tag = soup.find("meta", attrs={"property": prop}) or soup.find(
            "meta", attrs={"name": prop}
        )
        if tag and tag.get("content"):
            title = _clean_title(tag.get("content"), url)
            if title and _scoring_len(title) >= 3:
                return title
    return ""


def _title_from_page_headings(soup, url):
    """
    Fallback to the best h1/h2 on the page.
    """
    best, score = _best_heading(soup.find_all(["h1", "h2"]))
    if best is not None and score > 10:
        return _clean_title(best.get_text(" ", strip=True), url)
    return ""


def _detect_title(soup, selection, url):
    """
    Title detection order:
        1. heading near selected candidate
        2. meta og:title / twitter:title
        3. best page h1/h2
        4. <title> tag cleanup
    """
    if selection:
        title = _title_from_candidate(selection[0], url)
        if title and _scoring_len(title) >= 2:
            return title

    title = _title_from_meta(soup, url)
    if title and _scoring_len(title) >= 3:
        return title

    title = _title_from_page_headings(soup, url)
    if title and _scoring_len(title) >= 2:
        return title

    if soup.title and soup.title.string:
        title = _clean_title(soup.title.string, url)
        if title and _scoring_len(title) >= 2:
            return title

    return ""


# ---------------------------------------------------------------------------
# Final content cleaning and text serialization
# ---------------------------------------------------------------------------

def _clean_content_root(root):
    """
    Clean the selected candidate in-place before final text extraction.

    This is where we remove:
        - nav/footer/header/aside descendants
        - hidden elements
        - negative class/id containers
        - link-heavy blocks
        - small UI labels
        - obvious prev/next/recommend/comment blocks
    """
    # Remove comments.
    for comment in root.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # Remove obvious non-content tags.
    for tag in root.find_all(CLEAN_REMOVE_TAGS):
        if tag is root:
            continue
        tag.decompose()

    # Remove hidden elements.
    for tag in root.find_all(True):
        if tag is root or tag.parent is None:
            continue
        if _is_hidden(tag):
            tag.decompose()

    # Remove negative attribute containers.
    # If a container has both negative and strong positive hints, keep it only
    # if it looks strongly like prose.
    for tag in root.find_all(True):
        if tag is root or tag.parent is None:
            continue

        attrs = _attr_text(tag)
        if not NEGATIVE_ATTR_RE.search(attrs):
            continue

        text = _norm(tag.get_text(" ", strip=True))
        chars = _scoring_len(text)

        p_chars = 0
        for p in tag.find_all("p"):
            p_chars += _scoring_len(_norm(p.get_text(" ", strip=True)))

        p_ratio = p_chars / max(chars, 1)

        # Keep only if it is large, paragraph-heavy, and also has positive hints.
        if not (chars > 800 and p_ratio > 0.6 and HINT_ATTR_RE.search(attrs)):
            tag.decompose()

    # Remove link-heavy blocks.
    # Recommended novels, chapter lists, prev/next clusters, etc.
    for tag in root.find_all(
        ["div", "section", "ul", "ol", "table", "aside", "footer", "nav", "p", "li"]
    ):
        if tag is root or tag.parent is None:
            continue

        text = _norm(tag.get_text(" ", strip=True))
        chars = _scoring_len(text)

        if chars == 0:
            tag.decompose()
            continue

        link_chars = 0
        for a in tag.find_all("a"):
            link_chars += _scoring_len(_norm(a.get_text(" ", strip=True)))

        link_density = link_chars / chars if chars else 1.0

        if (link_density > 0.5 and chars < 500) or link_density > 0.8:
            tag.decompose()

    # Remove small UI-like labels.
    for tag in root.find_all(True):
        if tag is root or tag.parent is None:
            continue

        text = _norm(tag.get_text(" ", strip=True))
        chars = _scoring_len(text)

        if 0 < chars <= 80 and NEGATIVE_LABEL_RE.match(text):
            tag.decompose()

    # Handle anchors.
    # If anchor text looks like UI/navigation, remove it.
    # Otherwise unwrap the link but keep the text.
    for a in root.find_all("a"):
        if a.parent is None:
            continue

        text = _norm(a.get_text(" ", strip=True))
        chars = _scoring_len(text)

        if NEGATIVE_LABEL_RE.match(text) or chars < 40:
            a.decompose()
        else:
            a.unwrap()

    # Remove empty tags.
    for tag in root.find_all(True):
        if tag is root or tag.parent is None:
            continue
        if tag.name == "br":
            continue

        text = _norm(tag.get_text(" ", strip=True))
        if not text and not tag.find("img"):
            tag.decompose()


def _extract_text_from_root(root, title):
    """
    Convert cleaned selected root into final TTS-friendly text.

    Goals:
        - preserve paragraph breaks
        - avoid duplicating parent/child block text
        - remove title if it appears at the start
        - drop remaining small UI labels
    """
    title_norm = _norm(title) if title else ""

    # Remove heading(s) that are essentially the detected title.
    if title_norm:
        for h in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            h_text = _norm(h.get_text(" ", strip=True))
            if not h_text:
                continue

            same = h_text == title_norm
            similar = (
                title_norm
                and (h_text in title_norm or title_norm in h_text)
                and abs(_scoring_len(h_text) - _scoring_len(title_norm)) <= 20
            )

            if same or similar:
                h.decompose()

    # Convert <br> into line breaks before text serialization.
    for br in root.find_all("br"):
        br.replace_with("\n")

    blocks = []

    def add_text(txt):
        t = _norm(txt)
        if not t:
            return
        if _scoring_len(t) == 0:
            return

        # Skip exact title lines.
        if title_norm:
            if t == title_norm:
                return
            # Skip short lines that are just title plus minor punctuation.
            if t.startswith(title_norm) and _scoring_len(t) <= _scoring_len(title_norm) + 30:
                return

        # Skip remaining obvious UI labels.
        if _scoring_len(t) <= 80 and NEGATIVE_LABEL_RE.match(t):
            return

        # Avoid consecutive duplicates.
        if blocks and blocks[-1] == t:
            return

        blocks.append(t)

    def add_raw(raw):
        for line in str(raw).split("\n"):
            add_text(line)

    # If there are no block-level descendants, treat the whole root as prose.
    # This handles simple <div>...<br>...</div> chapter layouts.
    if not root.find(TEXT_BLOCK_TAGS):
        add_raw(root.get_text(" ", strip=False))
    else:
        # Preserve long direct text outside block children.
        direct_parts = []
        for child in root.children:
            if isinstance(child, NavigableString) and not isinstance(child, Comment):
                direct_parts.append(str(child))

        if direct_parts:
            direct = " ".join(direct_parts)
            if _scoring_len(direct) > 60:
                add_raw(direct)

        # Emit leaf block nodes only, to avoid parent+child duplication.
        for el in root.find_all(TEXT_BLOCK_TAGS):
            if el.parent is None:
                continue
            if el.find(TEXT_BLOCK_TAGS):
                continue
            add_raw(el.get_text(" ", strip=False))

    # Last resort.
    if not blocks:
        add_raw(root.get_text(" ", strip=False))

    # If the first block still starts with the title, strip that prefix.
    if blocks and title_norm:
        first = blocks[0]
        if first.startswith(title_norm):
            rest = first[len(title_norm):].lstrip(" \t\r\n-—:：.。,，")
            if rest and _scoring_len(rest) > 0:
                blocks[0] = rest
            else:
                blocks.pop(0)

    return "\n\n".join(blocks).strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_chapter(html, url=None):
    """
    Extract chapter title/body from raw HTML.

    Args:
        html: str or bytes containing HTML.
        url: optional source URL, used only for title cleanup.

    Returns:
        {
            "title": str,
            "content": str,
            "confidence": float,
        }
    """
    soup = _parse_soup(html)

    # Preprocess for scoring.
    _strip_for_scoring(soup)

    # General density candidates.
    candidates = _collect_candidates(soup)

    # Semantic fast-path candidates.
    fast = _fast_path_candidates(soup)

    if fast:
        # Combine fast-path and general candidates, de-duplicated by identity.
        combined = fast + candidates
        seen = []
        unique = []
        for cand in combined:
            if not any(cand.tag is existing for existing in seen):
                seen.append(cand.tag)
                unique.append(cand)
        candidates = sorted(unique, key=lambda c: c.score, reverse=True)

    selection, mode, margin = _choose_selection(candidates)

    # If nothing reasonable was found, fall back to body with low confidence.
    if not selection:
        root = soup.body or soup.find("html") or soup
        title = _detect_title(soup, [], url)

        _clean_content_root(root)
        content = _extract_text_from_root(root, title)

        final_chars = _scoring_len(content)
        confidence = min(0.2, final_chars / 1000.0) if final_chars else 0.0

        return {
            "title": title,
            "content": content,
            "confidence": round(max(0.0, min(1.0, confidence)), 3),
        }

    # Detect title before destructive final cleaning.
    title = _detect_title(soup, selection, url)

    # Extract and clean each selected block.
    parts = []
    for cand in selection:
        root = cand.tag

        # Skip if a previous cleaning step removed this root.
        if (
            root.parent is None
            and getattr(root, "name", "") != "body"
            and root is not soup
        ):
            continue

        _clean_content_root(root)
        part = _extract_text_from_root(root, title)
        if part:
            parts.append(part)

    content = "\n\n".join(parts).strip()

    confidence = _estimate_confidence(selection, mode, margin)

    # Adjust confidence based on final extracted length.
    final_chars = _scoring_len(content)
    if final_chars < 150:
        confidence *= max(0.0, final_chars / 150.0)
    if final_chars == 0:
        confidence = 0.0

    confidence = max(0.0, min(1.0, confidence))

    return {
        "title": title,
        "content": content,
        "confidence": round(confidence, 3),
    }


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

def _load_source(source, timeout):
    """
    Load HTML from a local file or URL.

    Returns:
        (html_bytes_or_str, url_or_none)
    """
    if source.startswith("http://") or source.startswith("https://"):
        if requests is None:
            raise RuntimeError(
                "requests is required for URL input. Install with: pip install requests"
            )

        resp = requests.get(
            source,
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; NovelExtractorPrototype/1.0; "
                    "+https://example.com/bot)"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        resp.raise_for_status()

        # Let BeautifulSoup/UnicodeDammit handle encoding detection.
        return resp.content, source

    path = Path(source)
    return path.read_bytes(), None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Generic novel chapter extractor for arbitrary HTML pages."
    )
    parser.add_argument(
        "sources",
        nargs="*",
        help="HTML files or http(s) URLs to extract.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON result for each source.",
    )
    parser.add_argument(
        "--preview",
        type=int,
        default=500,
        help="Number of content characters to preview in non-JSON mode.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="HTTP timeout in seconds.",
    )

    args = parser.parse_args()

    if not args.sources:
        parser.print_help()
        sys.exit(1)

    for source in args.sources:
        try:
            html, url = _load_source(source, args.timeout)
            result = extract_chapter(html, url=url)
        except Exception as exc:
            print(f"ERROR extracting {source}: {exc}", file=sys.stderr)
            continue

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            continue

        print("=" * 100)
        print("SOURCE    :", source)
        print("TITLE     :", result["title"])
        print("CONFIDENCE:", result["confidence"])
        print("CONTENT   :")

        preview = result["content"][: args.preview]
        if len(result["content"]) > args.preview:
            preview += " ..."

        print(preview)
        print()


if __name__ == "__main__":
    main()
