#!/usr/bin/env python3
"""
Novel Chapter Content Extractor
================================
A generic, heuristic-based HTML content extractor tuned for novel-reading
websites.  Isolates chapter title + body text from arbitrary HTML, stripping
nav bars, ads, comments, recommendations, author notes, and site chrome.

Designed for prototyping the extraction layer of a WebView-based Android
novel reader with TTS.  Logic here will be ported to Kotlin/JS.

Dependencies:
    pip install beautifulsoup4 lxml readability-lxml requests

Usage:
    python novel_extractor.py --url "https://example.com/chapter/123"
    python novel_extractor.py --file chapter.html
    python novel_extractor.py --test  # runs built-in test harness
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

# Optional: readability-lxml as baseline / fallback
try:
    from readability import Document as ReadabilityDocument
    HAS_READABILITY = True
except ImportError:
    HAS_READABILITY = False

# =============================================================================
# CONFIGURATION — tune these weights as you collect real-world data
# =============================================================================

# Common class/id substrings that strongly hint at chapter content.
# Scored as POSITIVE hints — higher weight = stronger signal.
POSITIVE_PATTERNS = {
    # English
    "chapter-content": 4.0,
    "article-content": 3.5,
    "readcontent": 4.0,
    "read_content": 4.0,
    "entry-content": 3.0,
    "post-content": 3.0,
    "page-content": 2.5,
    "storycontent": 3.5,
    "story-content": 3.5,
    "booktext": 4.0,
    "book_text": 4.0,
    "booktxt": 4.0,
    "book-txt": 4.0,
    "txt": 2.0,
    "text": 1.5,
    "content": 2.0,
    "main": 2.0,
    "article": 2.5,
    "chapter": 3.0,
    "chapter-body": 4.0,
    "chapter_text": 4.0,
    "chapternovel": 3.5,
    "novel-content": 3.5,
    "novelbody": 3.5,
    "novel-body": 3.5,
    # Chinese
    "章节内容": 4.0,
    "章节正文": 4.5,
    "小说正文": 4.0,
    "小说内容": 3.5,
    "正文内容": 4.0,
    "正文": 3.5,
    "内容": 1.5,
    "章节": 2.5,
    "阅读内容": 3.5,
    "阅读正文": 3.5,
    "书内容": 3.0,
    "文本": 2.0,
}

# Negative class/id substrings — these indicate boilerplate / noise.
NEGATIVE_PATTERNS = {
    # English
    "comment", "comments", "disqus", "reply", "replies",
    "recommend", "recommended", "related", "similar",
    "nav", "navbar", "navigation", "menu", "sidebar",
    "footer", "header", "head", "banner", "advertisement", "ad-",
    "ads", "share", "sharing", "social", "breadcrumb",
    "pagination", "pager", "prev", "next", "previous",
    "author-note", "author_note", "authors-note", "footnote",
    "widget", "widgets", "toolbar",
    # Chinese
    "评论", "留言", "回复", "推荐", "相关", "相关推荐",
    "导航", "菜单", "侧边栏", "页脚", "页头", "广告",
    "分享", "社交", "面包屑", "分页", "上一章", "下一章",
    "作者的话", "作者说", "脚注", "小工具", "工具栏",
    "目录", "书页", "书页导航", "章节列表", "最新章节",
}

# Tags that are almost always noise in a chapter context.
NOISE_TAGS = {
    "script", "style", "noscript", "iframe", "canvas",
    "svg", "form", "input", "button", "select", "textarea",
    "aside", "nav", "header", "footer",
}

# Minimum plausible chapter body length (characters).
MIN_CHAPTER_LENGTH = 200

# Inline tags that don't reduce density as much as block tags.
INLINE_TAGS = {
    "a", "b", "strong", "i", "em", "u", "span", "small",
    "sup", "sub", "mark", "del", "ins", "code", "tt",
    "font", "br", "wbr", "img", "ruby", "rt", "rp",
}

# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class CandidateBlock:
    """Represents a DOM subtree candidate for chapter content."""
    element: Tag
    text_length: int = 0          # visible character count (scoring)
    tag_count: int = 0            # number of descendant tags
    p_count: int = 0              # number of <p> descendants
    link_length: int = 0          # character count inside <a> tags
    link_count: int = 0           # number of <a> descendants
    short_text_nodes: int = 0     # text nodes shorter than 20 chars
    long_text_runs: int = 0       # text nodes >= 80 chars (paragraph-like)
    depth: int = 0                # depth from body (or root)
    positive_score: float = 0.0   # from class/id hints
    negative_score: float = 0.0   # from class/id hints
    density_score: float = 0.0    # text_length / max(tag_count, 1)
    final_score: float = 0.0      # combined heuristic score
    is_article_tag: bool = False
    is_main_role: bool = False


@dataclass
class ExtractionResult:
    """Structured output for downstream consumers."""
    title: str = ""
    content: str = ""           # plain text, paragraphs separated by \n\n
    content_html: str = ""      # optional: cleaned HTML fragment
    confidence: float = 0.0
    method: str = ""            # which strategy succeeded
    warnings: list[str] = field(default_factory=list)


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def normalize_text(text: str) -> str:
    """Collapse whitespace, strip leading/trailing."""
    return " ".join(text.split())


def char_count(text: str) -> int:
    """
    Count visible characters, language-agnostic.
    Strips control chars but PRESERVES punctuation in the returned count.
    """
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
    cleaned = cleaned.replace("\u200b", "").replace("\ufeff", "")
    return len(cleaned.strip())


def score_char_count(text: str) -> int:
    """
    Character count for SCORING purposes — strips common punctuation
    so that a block full of "!!!" or "……" doesn't inflate its score.
    """
    text = re.sub(
        r"[\u3000-\u303f\uff00-\uffef\u2000-\u206f"
        r"!\"#$%&\'()*+,\-./:;<=>?@\[\\\]^_`{|}~]+",
        "",
        text,
    )
    return len(text.strip())


def has_negative_indicator(element: Tag) -> bool:
    """Check if element's class or id contains negative keywords."""
    attrs = " ".join([
        " ".join(element.get("class", [])) if isinstance(element.get("class"), list) else element.get("class", ""),
        element.get("id", ""),
    ]).lower()
    for neg in NEGATIVE_PATTERNS:
        if neg.lower() in attrs:
            return True
    return False


def score_class_id_hints(element: Tag) -> tuple[float, float]:
    """
    Return (positive_score, negative_score) based on class/id attributes.
    """
    cls = element.get("class", "")
    if isinstance(cls, list):
        cls = " ".join(cls)
    eid = element.get("id", "")
    combined = f"{cls} {eid}".lower()

    pos = 0.0
    for pattern, weight in POSITIVE_PATTERNS.items():
        if pattern.lower() in combined:
            pos += weight

    neg = 0.0
    for pattern in NEGATIVE_PATTERNS:
        if pattern.lower() in combined:
            neg += 2.0  # uniform penalty weight

    return pos, neg


def clean_title(raw_title: str) -> str:
    """
    Strip common site-name suffixes from page <title>.
    Examples: "Chapter 1 - NovelSite", "第一章_XX小说网"
    """
    raw = normalize_text(raw_title)
    if not raw:
        return ""

    separators = [" - ", " — ", " | ", " _ ", " – ", " :: ", " << ", " >> "]
    for sep in separators:
        if sep in raw:
            parts = raw.split(sep)
            if len(parts) >= 2:
                first = parts[0].strip()
                last = parts[-1].strip()
                if len(last) < len(first) and len(first) > 10:
                    site_indicators = ["novel", "book", "read", "小说", "阅读", "书城", "文学"]
                    if not any(ind in first.lower() for ind in site_indicators):
                        return first
                    second = parts[1].strip() if len(parts) > 1 else ""
                    if second and len(second) > 5:
                        return second
    return raw


def is_prev_next_link(element: Tag) -> bool:
    """Detect prev/next chapter navigation links."""
    text = element.get_text(strip=True).lower()
    patterns = [
        "previous chapter", "next chapter", "prev chapter", "»", "«",
        "上一章", "下一章", "上一页", "下一页", "previous", "next",
        "<", ">", "←", "→",
    ]
    return any(p in text for p in patterns)


# =============================================================================
# CORE EXTRACTION ENGINE
# =============================================================================

class NovelExtractor:
    """
    Generic heuristic extractor for novel chapter pages.
    No per-domain rules — works across arbitrary English & Chinese sites.
    """

    def __init__(self, min_text_length: int = MIN_CHAPTER_LENGTH):
        self.min_text_length = min_text_length

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, html: str, url: str = "") -> ExtractionResult:
        """
        Main entry point.  Accepts raw HTML string, returns ExtractionResult.
        """
        soup = BeautifulSoup(html, "lxml")

        # 1. Pre-clean: remove obvious noise tags
        self._pre_clean(soup)

        # 2. Try fast-path structural hints
        result = self._try_fast_path(soup)
        if result.confidence >= 0.85:
            result.method = "fast-path"
            return result

        # 3. Run density-based candidate scoring over the whole body
        candidates = self._collect_candidates(soup)
        if not candidates:
            result = self._try_readability_fallback(html)
            if result.confidence > 0:
                return result
            return ExtractionResult(
                confidence=0.0,
                method="failed",
                warnings=["No viable content block found."],
            )

        # 4. Pick best candidate (or merge adjacent top candidates)
        best = self._select_best_candidate(candidates)

        # 5. Post-clean the winning block
        cleaned_html = self._post_clean(best.element)
        content_text = self._html_to_text(cleaned_html)

        # 6. Detect title
        title = self._detect_title(soup, best.element, url)

        # 7. Compute confidence
        confidence = self._compute_confidence(best, content_text, candidates)

        # 8. Sanity checks
        warnings = []
        if len(content_text) < self.min_text_length:
            warnings.append(
                f"Extracted text very short ({len(content_text)} chars); "
                "possible paywall, teaser, or extraction failure."
            )
            confidence *= 0.5

        return ExtractionResult(
            title=title,
            content=content_text,
            content_html=str(cleaned_html),
            confidence=round(confidence, 3),
            method="density-heuristic",
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Step 1: Pre-clean
    # ------------------------------------------------------------------

    def _pre_clean(self, soup: BeautifulSoup) -> None:
        """Remove invisible/irrelevant tags and HTML comments."""
        for tag in soup.find_all(NOISE_TAGS):
            tag.decompose()

        # Remove HTML comments (often contain ad scripts or tracking)
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        # Remove elements with strongly negative class/id patterns
        for elem in soup.find_all(True):
            if has_negative_indicator(elem):
                text_len = score_char_count(elem.get_text())
                if text_len < 500:
                    elem.decompose()

    # ------------------------------------------------------------------
    # Step 2: Fast-path structural hints
    # ------------------------------------------------------------------

    def _try_fast_path(self, soup: BeautifulSoup) -> ExtractionResult:
        """
        Look for <article>, <main>, or role="main" — if found and
        it contains substantial text, return immediately with high confidence.
        """
        selectors = [
            "article",
            "main",
            '[role="main"]',
            ".chapter-content",
            ".chapter_content",
            "#chapter-content",
            "#chapter_content",
            ".readcontent",
            "#readcontent",
            ".novel-body",
            "#novel-body",
            ".booktext",
            "#booktext",
        ]

        for sel in selectors:
            elem = soup.select_one(sel)
            if not elem:
                continue
            text = elem.get_text(separator="\n", strip=True)
            char_len = score_char_count(text)
            if char_len >= self.min_text_length:
                cleaned = self._post_clean(elem)
                content = self._html_to_text(cleaned)
                title = self._detect_title(soup, elem, "")
                conf = min(0.95, 0.7 + (char_len / 10000))
                return ExtractionResult(
                    title=title,
                    content=content,
                    content_html=str(cleaned),
                    confidence=round(conf, 3),
                    method="fast-path",
                )

        return ExtractionResult(confidence=0.0, method="fast-path-miss")

    # ------------------------------------------------------------------
    # Step 3: Candidate collection & scoring
    # ------------------------------------------------------------------

    def _collect_candidates(self, soup: BeautifulSoup) -> list[CandidateBlock]:
        """
        Walk the DOM and score every block-level container as a candidate.
        Returns list sorted by final_score descending.
        """
        candidates: list[CandidateBlock] = []
        body = soup.find("body")
        if not body:
            body = soup

        for elem in body.find_all(True):
            if elem.name in {"br", "hr", "img", "meta", "link", "base"}:
                continue
            if not self._is_block_container(elem):
                continue

            cand = self._score_element(elem)
            if cand.text_length >= 50:
                candidates.append(cand)

        candidates.sort(key=lambda c: c.final_score, reverse=True)
        return candidates

    def _is_block_container(self, elem: Tag) -> bool:
        """Determine if an element is a meaningful block-level container."""
        if elem.name in {"p", "span", "a", "b", "i", "strong", "em", "code"}:
            return False
        has_block_child = any(
            child.name in {"div", "p", "section", "article", "blockquote", "td"}
            for child in elem.children
            if isinstance(child, Tag)
        )
        text_len = score_char_count(elem.get_text())
        return has_block_child or text_len > 100

    def _score_element(self, elem: Tag) -> CandidateBlock:
        """Compute all heuristic scores for a single DOM element."""
        text = elem.get_text(separator="\n", strip=True)
        text_len = char_count(text)
        score_len = score_char_count(text)

        all_tags = list(elem.find_all(True))
        tag_count = len(all_tags)

        p_count = len(elem.find_all("p"))

        links = elem.find_all("a")
        link_count = len(links)
        link_length = sum(char_count(a.get_text()) for a in links)

        short_text_nodes = 0
        long_text_runs = 0
        for txt_node in elem.find_all(string=True):
            if isinstance(txt_node, NavigableString):
                t = str(txt_node).strip()
                if not t:
                    continue
                sc = score_char_count(t)
                if sc < 20:
                    short_text_nodes += 1
                elif sc >= 80:
                    long_text_runs += 1

        depth = 0
        parent = elem.parent
        while parent and parent.name != "body":
            depth += 1
            parent = parent.parent

        pos_hint, neg_hint = score_class_id_hints(elem)

        is_article = elem.name == "article"
        is_main = elem.get("role") == "main" or elem.name == "main"

        # ---- Density score ----
        density = score_len / max(tag_count, 1)

        # ---- Link density penalty ----
        link_ratio = link_length / max(score_len, 1)
        link_penalty = 0.0
        if link_ratio > 0.3:
            link_penalty = link_ratio * 3.0
        elif link_ratio > 0.15:
            link_penalty = link_ratio * 1.5

        # ---- Short-node penalty ----
        short_node_ratio = short_text_nodes / max(tag_count, 1)
        short_penalty = short_node_ratio * 2.0

        # ---- Reward long consecutive runs ----
        long_run_bonus = long_text_runs * 1.5

        # ---- Paragraph bonus ----
        p_bonus = p_count * 2.0

        # ---- Depth penalty (very deep nesting often = widget) ----
        depth_penalty = max(0, (depth - 8)) * 0.3

        # ---- Combine ----
        final = (
            density * 2.0
            + score_len * 0.01
            + p_bonus
            + long_run_bonus
            + pos_hint * 3.0
            - neg_hint * 2.5
            - link_penalty * 10.0
            - short_penalty * 5.0
            - depth_penalty
        )

        if is_article:
            final += 15.0
        if is_main:
            final += 20.0

        return CandidateBlock(
            element=elem,
            text_length=score_len,
            tag_count=tag_count,
            p_count=p_count,
            link_length=link_length,
            link_count=link_count,
            short_text_nodes=short_text_nodes,
            long_text_runs=long_text_runs,
            depth=depth,
            positive_score=pos_hint,
            negative_score=neg_hint,
            density_score=density,
            final_score=final,
            is_article_tag=is_article,
            is_main_role=is_main,
        )

    # ------------------------------------------------------------------
    # Step 4: Candidate selection & merging
    # ------------------------------------------------------------------

    def _select_best_candidate(self, candidates: list[CandidateBlock]) -> CandidateBlock:
        """
        Pick the highest-scoring candidate.
        If the next-highest candidate is structurally adjacent (sibling or
        cousin) and has a score within 30 % of the best, merge them.
        """
        if not candidates:
            raise ValueError("Empty candidate list")

        best = candidates[0]
        if len(candidates) == 1:
            return best

        merged_elem = best.element
        for cand in candidates[1:3]:
            if cand.final_score < best.final_score * 0.3:
                break
            if self._are_adjacent(best.element, cand.element):
                wrapper = BeautifulSoup("", "lxml").new_tag("div")
                best.element.insert_before(wrapper)
                wrapper.append(best.element.extract())
                wrapper.append(cand.element.extract())
                merged_elem = wrapper
                best = self._score_element(merged_elem)
                break

        return best

    def _are_adjacent(self, a: Tag, b: Tag) -> bool:
        """Check if two elements are siblings or near-cousins in the DOM."""
        if a.parent == b.parent:
            return True
        if a.parent and b.parent and a.parent.parent == b.parent.parent:
            return True
        return False

    # ------------------------------------------------------------------
    # Step 5: Post-clean the winning block
    # ------------------------------------------------------------------

    def _post_clean(self, root: Tag) -> Tag:
        """
        Remove remaining noise from inside the selected content block:
        ads, share buttons, prev/next links, author notes, etc.
        Returns a new detached Tag so we don't mutate the original soup.
        """
        clone = BeautifulSoup(str(root), "lxml").find(True)
        if not clone:
            return root

        for elem in list(clone.find_all(True)):
            if not elem or not elem.parent:
                continue

            if elem.name in {"aside", "nav", "header", "footer", "form"}:
                elem.decompose()
                continue

            if has_negative_indicator(elem):
                elem.decompose()
                continue

            if elem.name == "a" and is_prev_next_link(elem):
                elem.decompose()
                continue

            if elem.name in {"p", "div", "span"}:
                txt = normalize_text(elem.get_text())
                if not txt or len(txt) < 2:
                    elem.decompose()
                    continue

        # Remove trailing "author note" paragraphs
        for p in clone.find_all("p"):
            txt = p.get_text(strip=True).lower()
            if any(k in txt for k in {
                "author's note", "author note", "a/n", "author:",
                "作者的话", "作者说", "ps.", "p.s.", "note:", "notes:",
            }):
                for sibling in list(p.find_all_next()):
                    if sibling.parent == p.parent or sibling.parent == p.parent.parent:
                        sibling.decompose()
                p.decompose()

        return clone

    # ------------------------------------------------------------------
    # Step 6: Title detection
    # ------------------------------------------------------------------

    def _detect_title(self, soup: BeautifulSoup, content_elem: Tag, url: str) -> str:
        """
        Multi-strategy title detection:
        1. <h1> inside or immediately before the content block
        2. <h2> with chapter-like text near the content block
        3. Page <title> tag, cleaned of site suffixes
        """
        h1 = content_elem.find("h1")
        if h1:
            t = normalize_text(h1.get_text())
            if t and len(t) < 300:
                return t

        prev = content_elem.find_previous(["h1", "h2"])
        if prev:
            t = normalize_text(prev.get_text())
            if t and 5 < len(t) < 300:
                lower = t.lower()
                if any(k in lower for k in {
                    "chapter", "ch.", "第", "章", "节", "话", "卷",
                    "prologue", "epilogue", "interlude", "part",
                }):
                    return t
                if len(soup.find_all(["h1", "h2"])) <= 2:
                    return t

        page_title = soup.find("title")
        if page_title:
            return clean_title(page_title.get_text())

        for elem in content_elem.find_all(["b", "strong", "h3"]):
            t = normalize_text(elem.get_text())
            if t and 5 < len(t) < 200:
                return t

        return ""

    # ------------------------------------------------------------------
    # Step 7: Confidence scoring
    # ------------------------------------------------------------------

    def _compute_confidence(
        self,
        best: CandidateBlock,
        extracted_text: str,
        all_candidates: list[CandidateBlock],
    ) -> float:
        """
        Compute a 0.0–1.0 confidence score based on multiple signals.
        """
        scores = []

        text_len = len(extracted_text)
        if text_len >= 3000:
            scores.append(1.0)
        elif text_len >= 1000:
            scores.append(0.85)
        elif text_len >= 500:
            scores.append(0.7)
        elif text_len >= 200:
            scores.append(0.5)
        else:
            scores.append(0.2)

        p_ratio = best.p_count / max(best.tag_count, 1)
        scores.append(min(1.0, p_ratio * 5.0))

        link_ratio = best.link_length / max(best.text_length, 1)
        scores.append(max(0.0, 1.0 - link_ratio * 3.0))

        if len(all_candidates) >= 2:
            runner = all_candidates[1].final_score
            if runner > 0:
                dominance = best.final_score / runner
                scores.append(min(1.0, dominance / 3.0))
            else:
                scores.append(1.0)
        else:
            scores.append(0.7)

        if best.positive_score > 0:
            scores.append(min(1.0, best.positive_score / 5.0))
        else:
            scores.append(0.5)

        if best.long_text_runs >= 5:
            scores.append(1.0)
        elif best.long_text_runs >= 2:
            scores.append(0.8)
        else:
            scores.append(0.4)

        avg = sum(scores) / len(scores)
        min_score = min(scores)
        confidence = avg * 0.7 + min_score * 0.3
        return max(0.0, min(1.0, confidence))

    # ------------------------------------------------------------------
    # Fallback: readability-lxml baseline
    # ------------------------------------------------------------------

    def _try_readability_fallback(self, html: str) -> ExtractionResult:
        """Use readability-lxml as a fallback when our heuristics fail."""
        if not HAS_READABILITY:
            return ExtractionResult(confidence=0.0, method="readability-unavailable")

        try:
            doc = ReadabilityDocument(html)
            title = doc.short_title() or ""
            summary = doc.summary(html_partial=True)
            s = BeautifulSoup(summary, "lxml")
            text = self._html_to_text(s)
            conf = 0.55 if len(text) > self.min_text_length else 0.25
            return ExtractionResult(
                title=title,
                content=text,
                content_html=summary,
                confidence=round(conf, 3),
                method="readability-lxml-fallback",
            )
        except Exception as e:
            return ExtractionResult(
                confidence=0.0,
                method=f"readability-error: {e}",
                warnings=[str(e)],
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _html_to_text(self, node: Tag) -> str:
        """
        Convert a BeautifulSoup tag tree to clean plain text.
        Preserves paragraph breaks; strips extra whitespace.
        """
        paragraphs: list[str] = []
        for p in node.find_all("p"):
            txt = normalize_text(p.get_text())
            if txt:
                paragraphs.append(txt)

        if not paragraphs:
            text = node.get_text(separator="\n", strip=True)
            lines = [normalize_text(line) for line in text.splitlines()]
            paragraphs = [line for line in lines if line]

        return "\n\n".join(paragraphs)


# =============================================================================
# TEST HARNESS
# =============================================================================

TEST_URLS = [
    # English novel sites
    "https://www.royalroad.com/fiction/21220/mother-of-learning/chapter/301778/1-good-morning-brother",
    "https://www.webnovel.com/book/ascension-of-the-immortal_26322492006053705/chapter-1-death-and-rebirth_7075408204594889",
    "https://www.wuxiaworld.com/novel/against-the-gods/atg-chapter-1",
    # Chinese novel sites
    "https://www.qidian.com/chapter/1036310450/771234567/",
    "https://www.69shu.com/txt/12345/12345678.html",
]


def fetch_html(url: str, timeout: int = 15) -> str:
    """Fetch HTML with a browser-like User-Agent."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    if resp.encoding == "ISO-8859-1":
        resp.encoding = resp.apparent_encoding
    return resp.text


def run_test(url_or_path: str, extractor: NovelExtractor) -> None:
    """Run extraction on a single URL or file and print results."""
    is_url = bool(urlparse(url_or_path).scheme)
    label = url_or_path if len(url_or_path) < 80 else url_or_path[:77] + "..."

    print("=" * 80)
    print(f"SOURCE: {label}")
    print("=" * 80)

    try:
        if is_url:
            html = fetch_html(url_or_path)
        else:
            with open(url_or_path, "r", encoding="utf-8", errors="ignore") as f:
                html = f.read()
    except Exception as e:
        print(f"FETCH/READ ERROR: {e}\n")
        return

    result = extractor.extract(html, url=url_or_path if is_url else "")

    print(f"METHOD:     {result.method}")
    print(f"CONFIDENCE: {result.confidence}")
    print(f"TITLE:      {result.title or '(none)'}")
    if result.warnings:
        print(f"WARNINGS:   {'; '.join(result.warnings)}")

    preview = result.content[:800]
    if len(result.content) > 800:
        preview += "\n... [truncated]"
    print(f"CONTENT ({len(result.content)} chars):")
    print(textwrap.indent(preview, "    "))
    print()


def run_test_harness(extractor: NovelExtractor, sources: list[str] | None = None) -> None:
    """Run the built-in test harness against a list of URLs or files."""
    sources = sources or TEST_URLS
    for src in sources:
        run_test(src, extractor)


# =============================================================================
# CLI
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generic novel chapter content extractor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --url "https://example.com/chapter/1"
  %(prog)s --file saved_chapter.html
  %(prog)s --test
  %(prog)s --test urls.txt        # one URL per line
        """,
    )
    parser.add_argument("--url", help="Fetch and extract from a live URL")
    parser.add_argument("--file", help="Extract from a local HTML file")
    parser.add_argument(
        "--test",
        nargs="?",
        const="__builtin__",
        metavar="FILE",
        help=(
            "Run test harness.  With no argument, uses built-in URL list. "
            "With a file argument, reads one URL/path per line."
        ),
    )
    parser.add_argument(
        "--min-length",
        type=int,
        default=MIN_CHAPTER_LENGTH,
        help=f"Minimum extracted text length to consider valid (default {MIN_CHAPTER_LENGTH})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of human-readable format",
    )
    args = parser.parse_args()

    extractor = NovelExtractor(min_text_length=args.min_length)

    if args.test:
        if args.test == "__builtin__":
            run_test_harness(extractor)
        else:
            with open(args.test, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            run_test_harness(extractor, lines)
        return

    if args.url:
        html = fetch_html(args.url)
        result = extractor.extract(html, url=args.url)
    elif args.file:
        with open(args.file, "r", encoding="utf-8", errors="ignore") as f:
            html = f.read()
        result = extractor.extract(html)
    else:
        parser.print_help()
        sys.exit(1)

    if args.json:
        print(json.dumps({
            "title": result.title,
            "content": result.content,
            "confidence": result.confidence,
            "method": result.method,
            "warnings": result.warnings,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"Title:      {result.title or '(none)'}")
        print(f"Confidence: {result.confidence}")
        print(f"Method:     {result.method}")
        if result.warnings:
            print(f"Warnings:   {'; '.join(result.warnings)}")
        print(f"\nContent ({len(result.content)} chars):\n")
        print(result.content)


if __name__ == "__main__":
    main()
