#!/usr/bin/env python3
"""
bypasser.py
===========

Cloudflare Bypasser for Novel Scrapers - Python Implementation
Inspired by https://github.com/Parasgaming122/external-sources/tree/main/bypasser

Features:
- 4-Tier Architecture for bypassing Cloudflare protection
- Browser-like header emulation with User-Agent rotation
- Session caching with cookie replay
- Rate limiting with exponential backoff
- Challenge page detection
- Works standalone without external services

Usage:
    from bypasser import Bypasser
    
    bp = Bypasser()
    html = bp.fetch("https://example.com")
    
    # Or use convenience functions
    from bypasser import fetch, smart_fetch
    
    html = fetch("https://example.com")
"""

from __future__ import annotations

import re
import time
import random
import hashlib
from typing import Dict, Optional, List, Tuple, Any
from dataclasses import dataclass, field
from urllib.parse import urlparse

try:
    import requests
    from requests.cookies import RequestsCookieJar
except ImportError:
    raise ImportError("Required package: pip install requests")


# ============================================================================
# Configuration
# ============================================================================

@dataclass
class BypasserConfig:
    """Configuration for the bypasser."""
    debug: bool = False
    mode: str = "standalone"
    
    # Request delays (seconds)
    request_delay_min: float = 0.5
    request_delay_max: float = 2.0
    
    # Retry settings
    max_retries: int = 3
    retry_backoff: float = 2.0
    
    # Cookie TTL (seconds)
    cookie_ttl: int = 3600
    
    # Timeout (seconds)
    timeout: int = 30
    
    # Domain-specific overrides
    domain_overrides: Dict[str, Dict] = field(default_factory=dict)


# Default configuration
DEFAULT_CONFIG = BypasserConfig()


# ============================================================================
# User-Agent Rotation
# ============================================================================

USER_AGENTS = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    # Chrome Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    # Firefox
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
    # Safari
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    # Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

ACCEPT_LANGUAGES = [
    "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
]


# ============================================================================
# Challenge Detection Patterns
# ============================================================================

CHALLENGE_PATTERNS = [
    # Cloudflare specific
    r"cf-browser-verification",
    r"challenge-platform",
    r"jschl-answer",
    r"cf_chl_opt",
    r"cdn-cgi/challenge",
    r"Just a moment",
    r"Checking your browser before",
    r"Attention Required",
    r"cf-turnstile",
    r"__cf_bm",
    r"cf_clearance",
    # Generic bot protection
    r"hcaptcha",
    r"g-recaptcha",
    r"geetest",
    r"imperva",
    r"_Incapsula_Resource",
    # Status indicators
    r"403 Forbidden",
    r"Access Denied",
    r"Bot Detection",
    # Chinese site protections
    r"安全验证",
    r"人机验证",
    r"访问频繁",
    r"请稍后重试",
]

CHALLENGE_REGEX = re.compile("|".join(CHALLENGE_PATTERNS), re.IGNORECASE)


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class FetchResult:
    """Result of a fetch operation."""
    success: bool
    html: str
    status_code: int = 0
    tier: int = 1
    elapsed_ms: float = 0.0
    cookies: Dict[str, str] = field(default_factory=dict)
    error: str = ""


@dataclass
class CachedSession:
    """Cached session with cookies."""
    cookies: Dict[str, str]
    user_agent: str
    created_at: float
    domain: str


# ============================================================================
# Main Bypasser Class
# ============================================================================

class Bypasser:
    """
    Cloudflare Bypasser with 4-tier architecture.
    
    Tiers:
    1. Plain HTTP with browser-like headers (<200ms)
    2. Cached session/cookies replay (~300ms)
    3. Enhanced retry with UA rotation + delays (3-12s)
    4. Fallback strategies / best effort
    """
    
    def __init__(self, config: Optional[BypasserConfig] = None):
        self.config = config or DEFAULT_CONFIG
        
        # Session cache (Tier 2)
        self.session_cache: Dict[str, CachedSession] = {}
        
        # Rate limiting
        self.last_request: Dict[str, float] = {}
        self.request_count: Dict[str, int] = {}
        
        # User-Agent rotation index
        self.ua_index = 0
        
        # Statistics
        self.stats = {
            "tier1_hits": 0,
            "tier2_hits": 0,
            "tier3_hits": 0,
            "tier4_hits": 0,
            "failures": 0,
        }
        
        # Session object for cookie persistence
        self.session = requests.Session()
    
    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc.lower()
    
    def _get_cache_key(self, domain: str) -> str:
        """Generate cache key from domain."""
        return hashlib.md5(domain.encode()).hexdigest()
    
    def _get_next_ua(self) -> str:
        """Get next User-Agent in rotation."""
        ua = USER_AGENTS[self.ua_index]
        self.ua_index = (self.ua_index + 1) % len(USER_AGENTS)
        return ua
    
    def _get_accept_language(self) -> str:
        """Get random accept-language header."""
        return random.choice(ACCEPT_LANGUAGES)
    
    def _is_challenge_page(self, status_code: int, body: str) -> bool:
        """Check if response is a challenge page."""
        # Check status codes
        if status_code in (403, 429, 503):
            return True
        
        # Check body for challenge patterns (first 15KB)
        if body:
            check_body = body[:15000].lower()
            if CHALLENGE_REGEX.search(check_body):
                return True
        
        return False
    
    def _cache_get(self, domain: str) -> Optional[CachedSession]:
        """Get cached session for domain."""
        key = self._get_cache_key(domain)
        cached = self.session_cache.get(key)
        
        if cached:
            now = time.time()
            if (now - cached.created_at) < self.config.cookie_ttl:
                self.stats["tier2_hits"] += 1
                return cached
            else:
                # Expired
                del self.session_cache[key]
        
        return None
    
    def _cache_put(self, domain: str, cookies: Dict[str, str], user_agent: str):
        """Cache session for domain."""
        key = self._get_cache_key(domain)
        self.session_cache[key] = CachedSession(
            cookies=cookies,
            user_agent=user_agent,
            created_at=time.time(),
            domain=domain,
        )
    
    def _cache_invalidate(self, domain: str):
        """Invalidate cached session for domain."""
        key = self._get_cache_key(domain)
        if key in self.session_cache:
            del self.session_cache[key]
    
    def _build_headers(self, domain: str, use_cached: bool = True) -> Dict[str, str]:
        """Build browser-like headers."""
        headers = {
            "User-Agent": self._get_next_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": self._get_accept_language(),
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
            "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }
        
        # Add cached cookies if available
        if use_cached:
            cached = self._cache_get(domain)
            if cached and cached.cookies:
                cookie_str = "; ".join(f"{k}={v}" for k, v in cached.cookies.items())
                if cookie_str:
                    headers["Cookie"] = cookie_str
                    headers["User-Agent"] = cached.user_agent or headers["User-Agent"]
        
        return headers
    
    def _enforce_rate_limit(self, domain: str):
        """Enforce rate limiting for domain."""
        now = time.time()
        last_time = self.last_request.get(domain, 0)
        count = self.request_count.get(domain, 0)
        
        # Get domain-specific config
        domain_config = self.config.domain_overrides.get(domain, {})
        delay_min = domain_config.get("request_delay_min", self.config.request_delay_min)
        delay_max = domain_config.get("request_delay_max", self.config.request_delay_max)
        
        # Increase delay after multiple requests
        if count > 10:
            delay_min *= 1.5
            delay_max *= 1.5
        
        required_delay = delay_min + random.random() * (delay_max - delay_min)
        elapsed = now - last_time
        
        if elapsed < required_delay and count > 0:
            sleep_time = required_delay - elapsed
            if self.config.debug:
                print(f"[BYPASS] Rate limit: sleeping {sleep_time:.2f}s for {domain}")
            time.sleep(sleep_time)
        
        self.last_request[domain] = now
        self.request_count[domain] = count + 1
    
    def _extract_cookies(self, response: requests.Response) -> Dict[str, str]:
        """Extract important cookies from response."""
        cookies = {}
        
        for cookie in response.cookies:
            name = cookie.name.lower()
            # Store important cookies
            if any(kw in name for kw in ["cf", "session", "token", "auth", "phpsessid"]):
                cookies[cookie.name] = cookie.value
                if self.config.debug:
                    print(f"[BYPASS] Cached cookie: {cookie.name} for {cookie.domain}")
        
        return cookies
    
    def _tier1_request(self, method: str, url: str, options: Optional[Dict] = None) -> FetchResult:
        """Tier 1: Plain HTTP with browser emulation."""
        options = options or {}
        domain = self._get_domain(url)
        
        self._enforce_rate_limit(domain)
        
        headers = self._build_headers(domain, use_cached=True)
        
        try:
            # Prepare request data
            kwargs = {
                "headers": headers,
                "timeout": self.config.timeout,
                "allow_redirects": True,
            }
            
            if options.get("data"):
                kwargs["data"] = options["data"]
            
            # Make initial request
            response = self.session.request(method, url, **kwargs)
            response.encoding = response.apparent_encoding
            
            # Check for JS-based challenge (ixdzs8 style)
            if response.status_code == 200 and self._is_js_challenge(response.text):
                if self.config.debug:
                    print(f"[BYPASS] Detected JS challenge, attempting token extraction")
                
                # Extract token from JavaScript
                import re
                token_match = re.search(r'let token = "([^"]+)"', response.text)
                if token_match:
                    token = token_match.group(1)
                    # Build challenge URL
                    from urllib.parse import urlparse, parse_qs, urlencode
                    parsed = urlparse(url)
                    # Add challenge parameter
                    if '?' in url:
                        challenge_url = f"{url}&challenge={token}"
                    else:
                        challenge_url = f"{url}?challenge={token}"
                    
                    # Make second request with challenge token
                    response = self.session.request(method, challenge_url, **kwargs)
                    response.encoding = response.apparent_encoding
            
            # Extract cookies
            cookies = self._extract_cookies(response)
            if cookies:
                self._cache_put(domain, cookies, headers["User-Agent"])
            
            # Check if successful
            is_challenge = self._is_challenge_page(response.status_code, response.text)
            
            if response.status_code == 200 and not is_challenge:
                self.stats["tier1_hits"] += 1
                return FetchResult(
                    success=True,
                    html=response.text,
                    status_code=response.status_code,
                    tier=1,
                    cookies=cookies,
                )
            else:
                return FetchResult(
                    success=False,
                    html=response.text,
                    status_code=response.status_code,
                    tier=1,
                    cookies=cookies,
                    error=f"Status {response.status_code}" + (" (challenge)" if is_challenge else ""),
                )
                
        except requests.RequestException as e:
            if self.config.debug:
                print(f"[BYPASS] Tier 1 error: {e}")
            return FetchResult(
                success=False,
                html="",
                tier=1,
                error=str(e),
            )
    
    def _is_js_challenge(self, body: str) -> bool:
        """Check if response contains JavaScript-based challenge."""
        if not body:
            return False
        
        # Check for common JS challenge patterns
        challenge_patterns = [
            r'let token = "[^"]+"',
            r'window\.location\.href.*challenge',
            r'請稍等，正在進行安全驗證',
            r'正在验证浏览器',
        ]
        
        for pattern in challenge_patterns:
            if re.search(pattern, body, re.IGNORECASE):
                return True
        
        return False
    
    def _tier2_cached(self, method: str, url: str, options: Optional[Dict] = None) -> FetchResult:
        """Tier 2: Use cached session with fresh request."""
        options = options or {}
        domain = self._get_domain(url)
        
        # Invalidate old cache and make fresh request
        self._cache_invalidate(domain)
        
        result = self._tier1_request(method, url, options)
        result.tier = 2
        
        if result.success:
            self.stats["tier2_hits"] += 1
        
        return result
    
    def _tier3_retry(self, method: str, url: str, options: Optional[Dict] = None) -> FetchResult:
        """Tier 3: Retry with exponential backoff and UA rotation."""
        options = options or {}
        domain = self._get_domain(url)
        
        domain_config = self.config.domain_overrides.get(domain, {})
        max_retries = options.get("retries", domain_config.get("max_retries", self.config.max_retries))
        
        last_result = None
        
        for attempt in range(1, max_retries + 1):
            if self.config.debug:
                print(f"[BYPASS][T3] Retry {attempt}/{max_retries} for {url}")
            
            # Exponential backoff
            if attempt > 1:
                backoff = (self.config.retry_backoff ** (attempt - 1)) * 0.5
                if self.config.debug:
                    print(f"[BYPASS][T3] Backoff: {backoff:.2f}s")
                time.sleep(backoff)
            
            # Force fresh request
            options["use_cache"] = False
            result = self._tier1_request(method, url, options)
            
            if result.success:
                self.stats["tier3_hits"] += 1
                return result
            
            last_result = result
            self._cache_invalidate(domain)
        
        self.stats["failures"] += 1
        return last_result or FetchResult(
            success=False,
            html="",
            tier=3,
            error="All retries failed",
        )
    
    def _tier4_fallback(self, method: str, url: str, options: Optional[Dict] = None) -> FetchResult:
        """Tier 4: Last resort fallback."""
        if self.config.debug:
            print("[BYPASS][T4] Final fallback attempt")
        
        result = self._tier1_request(method, url, options)
        result.tier = 4
        
        if result.success:
            self.stats["tier4_hits"] += 1
        
        return result
    
    def fetch(self, url: str, method: str = "GET", data: Optional[Dict] = None, 
              options: Optional[Dict] = None) -> str:
        """
        Fetch URL with 4-tier bypass strategy.
        
        Args:
            url: URL to fetch
            method: HTTP method (GET or POST)
            data: POST data (if method is POST)
            options: Additional options (retries, timeout, etc.)
        
        Returns:
            HTML content as string
        """
        options = options or {}
        if data:
            options["data"] = data
        
        method = method.upper()
        
        if self.config.debug:
            print(f"[BYPASS] Fetch: {method} {url}")
        
        start_time = time.time()
        
        # Tier 1: Plain HTTP
        result = self._tier1_request(method, url, options)
        
        if result.success or (result.html and len(result.html) > 100 and not self._is_challenge_page(result.status_code, result.html)):
            result.elapsed_ms = (time.time() - start_time) * 1000
            if self.config.debug:
                print(f"[BYPASS] ✓ Tier {result.tier} ({result.elapsed_ms:.0f}ms)")
            return result.html
        
        # Tier 2: Cached session
        if self.config.debug:
            print("[BYPASS] Tier 1 failed, trying Tier 2...")
        result = self._tier2_cached(method, url, options)
        
        if result.success or (result.html and len(result.html) > 100 and not self._is_challenge_page(result.status_code, result.html)):
            result.elapsed_ms = (time.time() - start_time) * 1000
            if self.config.debug:
                print(f"[BYPASS] ✓ Tier {result.tier} ({result.elapsed_ms:.0f}ms)")
            return result.html
        
        # Tier 3: Retry with rotation
        if self.config.debug:
            print("[BYPASS] Tier 2 failed, trying Tier 3...")
        result = self._tier3_retry(method, url, options)
        
        if result.success or (result.html and result.html != ""):
            result.elapsed_ms = (time.time() - start_time) * 1000
            if self.config.debug:
                print(f"[BYPASS] ✓ Tier {result.tier} ({result.elapsed_ms:.0f}ms)")
            return result.html
        
        # Tier 4: Best effort fallback
        if self.config.debug:
            print("[BYPASS] Tier 3 failed, trying Tier 4...")
        result = self._tier4_fallback(method, url, options)
        
        result.elapsed_ms = (time.time() - start_time) * 1000
        if self.config.debug:
            print(f"[BYPASS] {'✓' if result.success else '✗'} Tier {result.tier} ({result.elapsed_ms:.0f}ms)")
        
        return result.html or ""
    
    def get(self, url: str, options: Optional[Dict] = None) -> Dict[str, Any]:
        """Convenience method for GET requests."""
        html = self.fetch(url, method="GET", options=options)
        if html:
            return {"success": True, "body": html}
        return {"success": False, "body": ""}
    
    def post(self, url: str, data: Dict, options: Optional[Dict] = None) -> Dict[str, Any]:
        """Convenience method for POST requests."""
        html = self.fetch(url, method="POST", data=data, options=options)
        if html:
            return {"success": True, "body": html}
        return {"success": False, "body": ""}
    
    def search(self, url: str, data: Dict, options: Optional[Dict] = None) -> str:
        """Convenience method for search (POST) requests."""
        return self.fetch(url, method="POST", data=data, options=options) or ""
    
    def clear_cache(self):
        """Clear all cached sessions."""
        self.session_cache.clear()
        self.last_request.clear()
        self.request_count.clear()
        self.stats = {
            "tier1_hits": 0,
            "tier2_hits": 0,
            "tier3_hits": 0,
            "tier4_hits": 0,
            "failures": 0,
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get bypasser status and statistics."""
        return {
            "mode": self.config.mode,
            "stats": self.stats,
            "cached_sessions": len(self.session_cache),
            "version": "1.0.0",
            "tiers_available": [1, 2, 3, 4],
        }


# ============================================================================
# Module-level Convenience Functions
# ============================================================================

_default_bypasser: Optional[Bypasser] = None


def _get_bypasser() -> Bypasser:
    """Get or create default bypasser instance."""
    global _default_bypasser
    if _default_bypasser is None:
        _default_bypasser = Bypasser()
    return _default_bypasser


def fetch(url: str, method: str = "GET", data: Optional[Dict] = None, 
          options: Optional[Dict] = None, debug: bool = False) -> str:
    """
    Fetch URL with Cloudflare bypass.
    
    Args:
        url: URL to fetch
        method: HTTP method (default: GET)
        data: POST data (optional)
        options: Additional options (optional)
        debug: Enable debug output (default: False)
    
    Returns:
        HTML content as string
    """
    if debug:
        bp = Bypasser(BypasserConfig(debug=True))
    else:
        bp = _get_bypasser()
    return bp.fetch(url, method=method, data=data, options=options)


def smart_fetch(url: str, options: Optional[Dict] = None) -> str:
    """Smart fetch with automatic method detection."""
    return fetch(url, options=options)


def get(url: str, options: Optional[Dict] = None) -> Dict[str, Any]:
    """GET request with bypass."""
    return _get_bypasser().get(url, options=options)


def post(url: str, data: Dict, options: Optional[Dict] = None) -> Dict[str, Any]:
    """POST request with bypass."""
    return _get_bypasser().post(url, data, options=options)


def search(url: str, data: Dict, options: Optional[Dict] = None) -> str:
    """Search (POST) request with bypass."""
    return _get_bypasser().search(url, data, options=options)


def clear_cache():
    """Clear all cached sessions."""
    _get_bypasser().clear_cache()


def get_status() -> Dict[str, Any]:
    """Get bypasser status."""
    return _get_bypasser().get_status()


# ============================================================================
# CLI Interface
# ============================================================================

if __name__ == "__main__":
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="Cloudflare Bypasser CLI")
    parser.add_argument("url", help="URL to fetch")
    parser.add_argument("--method", "-m", default="GET", choices=["GET", "POST"],
                        help="HTTP method (default: GET)")
    parser.add_argument("--data", "-d", help="POST data (JSON format)")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")
    parser.add_argument("--stats", action="store_true", help="Show statistics after fetch")
    
    args = parser.parse_args()
    
    # Parse POST data if provided
    post_data = None
    if args.data:
        import json
        try:
            post_data = json.loads(args.data)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON data: {e}", file=sys.stderr)
            sys.exit(1)
    
    # Create bypasser with debug if requested
    config = BypasserConfig(debug=args.debug)
    bp = Bypasser(config)
    
    # Fetch URL
    print(f"Fetching: {args.method} {args.url}", file=sys.stderr)
    html = bp.fetch(args.url, method=args.method, data=post_data)
    
    # Output result
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Saved to: {args.output}", file=sys.stderr)
    else:
        print(html)
    
    # Show statistics if requested
    if args.stats:
        status = bp.get_status()
        print(f"\nStatistics:", file=sys.stderr)
        print(f"  Tier 1 hits: {status['stats']['tier1_hits']}", file=sys.stderr)
        print(f"  Tier 2 hits: {status['stats']['tier2_hits']}", file=sys.stderr)
        print(f"  Tier 3 hits: {status['stats']['tier3_hits']}", file=sys.stderr)
        print(f"  Tier 4 hits: {status['stats']['tier4_hits']}", file=sys.stderr)
        print(f"  Failures: {status['stats']['failures']}", file=sys.stderr)
        print(f"  Cached sessions: {status['cached_sessions']}", file=sys.stderr)
