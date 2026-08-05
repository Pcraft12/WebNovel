#!/usr/bin/env python3
"""
Novel Chapter Content Extractor
--------------------------------
Generic heuristic algorithm to extract the main chapter text (title + body)
from arbitrary novel-reading websites. Designed to work for both English
and Chinese content, without per‑site rules.

The algorithm combines:
- Structural signals (most <p> tags, text density, link density)
- Common CMS class/id patterns (as hints)
- Noise blocklist (comments, ads, navigation, recommendations)
- Fallback merging of adjacent good candidates

Output: { "title": str, "content": str, "confidence": float }

This is a prototyping/testing script for the content‑extraction layer
of an Android novel reader app. Once validated, the logic will be ported
to Kotlin/JS.
"""

import re
import sys
import argparse
from typing import Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag, NavigableString

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------

# Common content container class/id patterns (used as positive hints)
CONTENT_PATTERNS = re.compile(
    r'(article|content|chapter|read|txt|book|novel|text|entry|body|main)',
    re.I
)

# Noise patterns – elements with these words in class/id are likely
# navigation, ads, comments, recommendations, etc.
NOISE_PATTERNS = re.compile(
    r'(comment|recommend|related|nav|footer|sidebar|share|advertisement|'
    r'ad\b|disqus|breadcrumb|prev|next|chapter-list|copyright|notice|'
    r'推荐|评论|相关|导航|广告|分享|版权|公告|上一章|下一章)',
    re.I
)

# Title separators for stripping site name from <title>
TITLE_SEPARATORS = re.compile(r'[—–\-_|:：»›]')

# Chinese site suffixes to strip
CN_SUFFIXES = re.compile(r'(小说网|读书网|中文网|阅读网|文学网|小说|免费|全文|最新章节)$')

# Punctuation (both CJK and Latin) to ignore when scoring content length
PUNCTUATION = re.compile(r'[\s\.,!?;:()\[\]{}"\'`~@#$%^&*+=|\\<>/…—\-『』「」（）【】；：！？，。、]')


# ----------------------------------------------------------------------
# Core extractor class
# ----------------------------------------------------------------------

class NovelContentExtractor:
    """
    Extracts title and main content from a raw HTML chapter page.
    """

    def __init__(self, html: Optional[str] = None, url: Optional[str] = None):
        """
        :param html: Raw HTML string (if already fetched)
        :param url:  URL of the page (used for fetching and title fallback)
        """
        self.raw_html = html
        self.url = url
        self.soup = None
        self.title = ""
        self.content = ""
        self.confidence = 0.0

    def fetch(self, url: str) -> str:
        """Fetch HTML from a URL (with reasonable timeout and headers)."""
        headers = {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/91.0.4472.124 Safari/537.36')
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = resp.apparent_encoding or 'utf-8'
        return resp.text

    def parse(self, html: str) -> None:
        """Parse HTML with BeautifulSoup (lxml parser)."""
        self.raw_html = html
        self.soup = BeautifulSoup(html, 'lxml')

    def extract(self) -> Dict[str, Union[str, float]]:
        """
        Run the extraction pipeline and return a result dict.
        """
        if self.raw_html is None and self.url is not None:
            self.raw_html = self.fetch(self.url)

        if self.raw_html is None:
            return {"title": "", "content": "", "confidence": 0.0}

        if self.soup is None:
            self.parse(self.raw_html)

        # 1. Pre‑clean obvious noise from the whole document
        self._remove_noise_elements()

        # 2. Find the best content block
        best = self._select_best_candidate()
        if best is None:
            # Fallback: use entire body (low confidence)
            body = self.soup.find('body')
            if body:
                content = self._clean_element(body)
                title = self._detect_title(body)
                return {"title": title, "content": content, "confidence": 0.2}
            else:
                return {"title": "", "content": "", "confidence": 0.0}

        # 3. Clean the chosen block (remove leftover noise inside)
        clean_content = self._clean_element(best)

        # 4. Detect title from the block or page <title>
        title = self._detect_title(best)

        # 5. Compute confidence
        confidence = self._compute_confidence(best)

        self.title = title
        self.content = clean_content
        self.confidence = confidence

        return {
            "title": title,
            "content": clean_content,
            "confidence": confidence
        }

    # ------------------------------------------------------------------
    # Pre‑cleaning
    # ------------------------------------------------------------------

    def _remove_noise_elements(self) -> None:
        """
        Remove elements whose class/id strongly indicate they are
        navigation, ads, comments, etc.
        """
        if self.soup is None:
            return

        # Find all elements with class or id attributes
        for el in self.soup.find_all(attrs={'class': True}):
            classes = ' '.join(el.get('class', []))
            if NOISE_PATTERNS.search(classes):
                el.decompose()
                continue

        for el in self.soup.find_all(attrs={'id': True}):
            el_id = el.get('id', '')
            if NOISE_PATTERNS.search(el_id):
                el.decompose()
                continue

        # Also remove script, style, iframe, noscript, etc.
        for tag in self.soup(['script', 'style', 'iframe', 'noscript', 'svg']):
            tag.decompose()

        # Remove elements with role="navigation" or "banner"
        for el in self.soup.find_all(attrs={'role': True}):
            role = el.get('role', '').lower()
            if role in ('navigation', 'banner', 'complementary', 'contentinfo'):
                el.decompose()

    # ------------------------------------------------------------------
    # Candidate selection
    # ------------------------------------------------------------------

    def _select_best_candidate(self) -> Optional[Tag]:
        """
        Returns the single best content block (Tag) or None.
        """
        if self.soup is None:
            return None

        # Fast‑path: <article> or role="main" or <main>
        main = self.soup.find('article') or self.soup.find('main')
        if not main:
            main = self.soup.find(attrs={'role': 'main'})
        if main:
            # Still score it to be sure, but give it a boost
            candidates = [main]
        else:
            # Otherwise collect all possible container elements
            candidates = self._get_candidate_elements()

        if not candidates:
            return None

        # Score each candidate
        scored = []
        for el in candidates:
            score = self._score_element(el)
            if score > 0:
                scored.append((score, el))

        if not scored:
            return None

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Take the highest scoring element
        best_score, best_el = scored[0]

        # Optional: merge with adjacent good candidates if they are siblings
        # (simplistic: if the second best is adjacent and has close score, merge)
        # For simplicity, we return the best alone.
        # Advanced merging can be added later.

        return best_el

    def _get_candidate_elements(self) -> List[Tag]:
        """
        Returns a list of candidate container elements (div, section, main,
        article, etc.) that might contain the main text.
        """
        candidates = []
        # Use common block tags
        for tag in self.soup.find_all(['div', 'section', 'article', 'main']):
            # Skip if it has a parent that is already a candidate? We want independent blocks.
            # We'll just collect all, scoring will handle.
            candidates.append(tag)

        # If no candidates found, fallback to body
        if not candidates:
            body = self.soup.find('body')
            if body:
                candidates.append(body)

        return candidates

    # ------------------------------------------------------------------
    # Scoring heuristics
    # ------------------------------------------------------------------

    def _score_element(self, el: Tag) -> float:
        """
        Compute a score for a candidate element based on text density,
        link density, paragraph count, and content‑class hints.
        """
        if el is None:
            return 0.0

        # Basic stats
        text = el.get_text(separator=' ', strip=True)
        if not text:
            return 0.0

        # Total character count (non‑punctuation, whitespace stripped for scoring)
        clean_text = PUNCTUATION.sub('', text)
        char_count = len(clean_text)
        if char_count < 20:   # too short to be the main content
            return 0.0

        # Number of descendant tags
        tag_count = len(el.find_all())
        if tag_count == 0:
            return 0.0

        # Density: characters per tag
        density = char_count / max(1, tag_count)

        # Link density: proportion of link text to total text
        link_text = ''.join(a.get_text(strip=True) for a in el.find_all('a'))
        link_clean = PUNCTUATION.sub('', link_text)
        link_density = len(link_clean) / max(1, char_count)

        # Reward for many <p> tags with substantial text
        p_tags = el.find_all('p')
        good_p = 0
        for p in p_tags:
            p_text = PUNCTUATION.sub('', p.get_text(strip=True))
            if len(p_text) > 30:
                good_p += 1

        # Boost for common content class/id patterns
        class_hint = 0
        class_attr = el.get('class')
        if class_attr:
            class_str = ' '.join(class_attr)
            if CONTENT_PATTERNS.search(class_str):
                class_hint = 1.5
        el_id = el.get('id', '')
        if CONTENT_PATTERNS.search(el_id):
            class_hint = max(class_hint, 1.5)

        # Penalise very high link density (typical of navigation or recommendations)
        link_penalty = 1.0
        if link_density > 0.5:
            link_penalty = 0.3
        elif link_density > 0.3:
            link_penalty = 0.6

        # Penalise elements with many very short text nodes (comment lists, UI)
        # Count text nodes with length < 5 characters (after stripping)
        short_text_nodes = 0
        total_text_nodes = 0
        for child in el.descendants:
            if isinstance(child, NavigableString) and child.parent.name != 'script':
                s = child.strip()
                if s:
                    total_text_nodes += 1
                    if len(s) < 5:
                        short_text_nodes += 1
        short_ratio = short_text_nodes / max(1, total_text_nodes)
        short_penalty = 1.0
        if short_ratio > 0.5:
            short_penalty = 0.4
        elif short_ratio > 0.3:
            short_penalty = 0.7

        # Combine scores
        score = (density * 0.4) + (good_p * 5.0) + (class_hint * 10.0)
        score *= link_penalty * short_penalty

        # Normalise density? Not needed, we just compare relative scores.
        return score

    # ------------------------------------------------------------------
    # Cleaning a selected block
    # ------------------------------------------------------------------

    def _clean_element(self, el: Tag) -> str:
        """
        Remove leftover noise inside the chosen block and return clean HTML
        as a string (or just text? The requirement says "actual chapter text",
        but we might want to preserve some formatting like paragraphs.
        We'll return the inner HTML with basic formatting stripped.
        For TTS, plain text is sufficient.
        We'll return text with paragraphs separated by newlines.
        """
        # Make a copy to avoid modifying the original
        clone = el.__copy__()

        # Remove elements that are likely noise inside (using same patterns)
        for tag in clone.find_all(attrs={'class': True}):
            classes = ' '.join(tag.get('class', []))
            if NOISE_PATTERNS.search(classes):
                tag.decompose()
        for tag in clone.find_all(attrs={'id': True}):
            tag_id = tag.get('id', '')
            if NOISE_PATTERNS.search(tag_id):
                tag.decompose()

        # Also remove hidden elements
        for tag in clone.find_all(attrs={'style': True}):
            style = tag.get('style', '').lower()
            if 'display:none' in style or 'visibility:hidden' in style:
                tag.decompose()

        # Extract text with paragraph separation
        # We'll get all text, but we want to keep paragraph boundaries.
        # Use <p> and <br> as newline indicators.
        for br in clone.find_all('br'):
            br.replace_with('\n')
        for p in clone.find_all('p'):
            p_text = p.get_text(strip=True)
            if p_text:
                p.replace_with(p_text + '\n\n')
            else:
                p.decompose()

        # Get remaining text, collapse multiple newlines
        text = clone.get_text(separator=' ', strip=True)
        # Replace multiple spaces/newlines with single newline for readability
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = text.strip()

        return text

    # ------------------------------------------------------------------
    # Title detection
    # ------------------------------------------------------------------

    def _detect_title(self, candidate: Tag) -> str:
        """
        Attempt to find the chapter title from the candidate block or page <title>.
        """
        # Look for h1/h2 inside candidate
        for heading in ['h1', 'h2']:
            h = candidate.find(heading)
            if h:
                title = h.get_text(strip=True)
                if title:
                    return title

        # Fallback to page <title>
        if self.soup and self.soup.title:
            title = self.soup.title.get_text(strip=True)
            # Strip common site name suffixes
            title = self._clean_title(title)
            if title:
                return title

        # Last resort: use URL path
        if self.url:
            path = urlparse(self.url).path
            parts = path.split('/')
            if parts:
                last = parts[-1].replace('-', ' ').replace('_', ' ')
                if last:
                    return last.strip()

        return ""

    def _clean_title(self, title: str) -> str:
        """
        Remove site name suffixes from a title string.
        """
        # Split on common separators and take the first non‑empty part
        parts = TITLE_SEPARATORS.split(title)
        if parts:
            title = parts[0].strip()

        # Remove common Chinese site suffixes
        title = CN_SUFFIXES.sub('', title).strip()

        # Also remove common English suffixes like " - NovelSite", " | Read online"
        title = re.sub(r'\s*[–—\-_|:»›]\s*.*$', '', title).strip()

        return title

    # ------------------------------------------------------------------
    # Confidence estimation
    # ------------------------------------------------------------------

    def _compute_confidence(self, candidate: Tag) -> float:
        """
        Compute a confidence score between 0 and 1 based on:
        - Score of the best candidate relative to others
        - Presence of content class hints
        - Text length
        """
        # We'll use the candidate's score, but normalise roughly
        score = self._score_element(candidate)
        # Clamp to 0-1 range (empirical)
        confidence = min(1.0, score / 100.0)

        # Boost if candidate has a content class/id
        class_attr = candidate.get('class')
        if class_attr:
            class_str = ' '.join(class_attr)
            if CONTENT_PATTERNS.search(class_str):
                confidence = min(1.0, confidence + 0.2)
        el_id = candidate.get('id', '')
        if CONTENT_PATTERNS.search(el_id):
            confidence = min(1.0, confidence + 0.2)

        # If text is short, lower confidence
        text = candidate.get_text(strip=True)
        clean_text = PUNCTUATION.sub('', text)
        if len(clean_text) < 100:
            confidence *= 0.5

        return round(confidence, 2)


# ----------------------------------------------------------------------
# Test harness
# ----------------------------------------------------------------------

def test_extractor(url_or_file: str) -> None:
    """
    Run extractor on a URL or local HTML file and print results.
    """
    if url_or_file.startswith('http://') or url_or_file.startswith('https://'):
        # Live URL
        extractor = NovelContentExtractor(url=url_or_file)
    else:
        # Local file
        try:
            with open(url_or_file, 'r', encoding='utf-8') as f:
                html = f.read()
            extractor = NovelContentExtractor(html=html)
        except Exception as e:
            print(f"Error reading file: {e}")
            return

    result = extractor.extract()
    print("=" * 60)
    print(f"URL/File: {url_or_file}")
    print(f"Title    : {result['title']}")
    print(f"Confidence: {result['confidence']}")
    print("-" * 60)
    print("Content (first 500 chars):")
    print(result['content'][:500] + ("..." if len(result['content']) > 500 else ""))
    print("=" * 60)
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Extract novel chapter content from arbitrary HTML."
    )
    parser.add_argument(
        'inputs', nargs='+',
        help='URL(s) or local HTML file(s) to process'
    )
    parser.add_argument(
        '--output', '-o', choices=['json', 'text'], default='text',
        help='Output format (default: text)'
    )
    args = parser.parse_args()

    for inp in args.inputs:
        test_extractor(inp)

if __name__ == '__main__':
    main()
