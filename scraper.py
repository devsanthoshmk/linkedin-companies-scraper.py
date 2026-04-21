"""Unified LinkedIn Company Scraper CLI with automatic session management.

Features
--------
• Auto-detects expired sessions and refreshes them via stealth login
• Keyword search with location/geo filtering
• Result capping (fetch exactly N results)
• Saves raw LinkedIn API responses as JSON — zero field loss
• Fetch all results or limit by page count
• Progress display with deduplication
• Session validation before any API call

Usage
-----
    # Basic search (auto-saves JSON)
    python scraper.py "Real Estate"

    # With location
    python scraper.py "Real Estate" -l "Mumbai"

    # Cap results to 50 companies
    python scraper.py "Real Estate" --cap 50

    # Custom output file
    python scraper.py "Real Estate" -o realestate_bangalore.json

    # Fetch ALL results (no cap)
    python scraper.py "Real Estate" --all

    # Force session refresh
    python scraper.py "Real Estate" --refresh-session

    # Show help
    python scraper.py --help
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from module.linkedin_search import (
    EntityResultViewModel,
    SearchResponse,
    print_companies,
    search_companies,
    search_geo_locations,
    GEO_URN_MAP,
)
from module.paths import RESULTS_DIR
from module.session_extractor import (
    extract_session,
    test_session_with_api,
    load_credentials,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------

SESSION_EXPIRED_MARKERS = [
    "401",
    "403",
    "UNAUTHORIZED",
    "SESSION_EXPIRED",
    "ACCESS_TOKEN_EXPIRED",
]

SESSION_MISSING_MARKERS = [
    "LI_COOKIE not found",
    "LI_CSRF_TOKEN not found",
    "credentials not found",
]


def _env_has_credentials() -> bool:
    """Return True if LI_COOKIE and LI_CSRF_TOKEN exist in environment."""
    load_dotenv()
    return bool(os.getenv("LI_COOKIE") and os.getenv("LI_CSRF_TOKEN"))


def _get_credentials() -> tuple[str, str]:
    """Return (cookie, csrf) from environment."""
    load_dotenv()
    cookie = os.getenv("LI_COOKIE", "")
    csrf = os.getenv("LI_CSRF_TOKEN", "")
    if not cookie or not csrf:
        raise EnvironmentError("LI_COOKIE or LI_CSRF_TOKEN missing from .env")
    return cookie, csrf


def _is_session_expired(cookie: Optional[str], csrf: Optional[str]) -> bool:
    """Quick-check whether the current session still works."""
    if not cookie or not csrf:
        return True
    try:
        import asyncio

        return not asyncio.run(test_session_with_api(cookie, csrf))
    except Exception:
        return True


def _refresh_session(headless: bool = True) -> tuple[str, str]:
    """Run the stealth login to get a fresh session."""
    import asyncio

    logger.info("🔄 Refreshing LinkedIn session…")
    email, password = load_credentials()
    cookie, csrf = asyncio.run(
        extract_session(email=email, password=password, headless=headless)
    )
    # Reload so the current process sees the new values
    load_dotenv(override=True)
    logger.info("✅ Session refreshed successfully!")
    return cookie, csrf


def ensure_session(headless: bool = True, force_refresh: bool = False) -> tuple[str, str]:
    """Guarantee a valid session — auto-refresh if expired or missing.

    Parameters
    ----------
    headless : bool
        Run stealth browser headless during refresh.
    force_refresh : bool
        Skip expiry check and always refresh.

    Returns
    -------
    tuple[str, str]
        (cookie_string, csrf_token)
    """
    if force_refresh or not _env_has_credentials():
        if not _env_has_credentials():
            logger.info("🔑 No session found in .env — extracting new session…")
        return _refresh_session(headless=headless)

    cookie, csrf = _get_credentials()

    if force_refresh or _is_session_expired(cookie, csrf):
        logger.info("⚠ Session appears to be expired.")
        return _refresh_session(headless=headless)

    logger.info("✅ Session is valid.")
    return cookie, csrf


# ---------------------------------------------------------------------------
# Location resolver — interactive geo selection via LinkedIn API
# ---------------------------------------------------------------------------

def resolve_location_interactive(
    location_query: str,
    cookie: Optional[str] = None,
    csrf: Optional[str] = None,
) -> tuple[Optional[str], Optional[set[str]]]:
    """Query LinkedIn's geo typeahead API and let user pick a location.

    Parameters
    ----------
    location_query : str
        Human-readable location string (e.g. "Mumbai", "vandavasi").
    cookie : str, optional
        LinkedIn session cookie.
    csrf : str, optional
        CSRF token.

    Returns
    -------
    tuple[str, set[str]] or tuple[None, None]
        (geo_urn_id, geo_filter_words) — geo_filter_words is a set of
        city/region words extracted from the geo title, for client-side
        matching. Both None if user cancels.
    """
    from module.linkedin_search import _extract_geo_city, _extract_location_words

    # First check if it's already in the built-in map
    key = location_query.strip().lower()
    if key in GEO_URN_MAP:
        urn = GEO_URN_MAP[key]
        # Use the key itself as the city word
        city = key.title()
        words = _extract_location_words(city)
        print(f"📍 Location '{location_query}' found in built-in map (URN: {urn})")
        return (urn, words)

    # Query LinkedIn's typeahead API
    print(f"\n🔍 Searching LinkedIn for geo locations matching: '{location_query}'")
    try:
        geo_resp = search_geo_locations(
            keywords=location_query,
            cookie=cookie,
            csrf_token=csrf,
        )
    except Exception as e:
        print(f"  ⚠ Geo search failed: {e}")
        print("  Proceeding without location filter.")
        return (None, None)

    if not geo_resp.locations:
        print(f"  ⚠ No geo locations found for '{location_query}'.")
        print("  Proceeding without location filter.")
        return (None, None)

    # Display options
    print(f"\n  Found {geo_resp.raw_count} location(s):\n")
    print(f"  {'#':<4} {'Location':<45} {'Geo ID':<12} {'FSD Geo URN'}")
    print(f"  {'-' * 110}")
    for i, loc in enumerate(geo_resp.locations, 1):
        print(
            f"  {i:<4} {(loc.title or ''):<45} "
            f"{loc.geo_id:<12} {(loc.fsd_geo_urn or '')}"
        )

    # If only one result, use it automatically
    if len(geo_resp.locations) == 1:
        loc = geo_resp.locations[0]
        selected_id = loc.geo_id or (loc.tracking_urn or "").split(":")[-1]
        city = _extract_geo_city(loc.title or "")
        words = _extract_location_words(city)
        print(f"\n  ✅ Auto-selected: {loc.title} (Geo ID: {selected_id})")
        return (selected_id, words)

    # Ask user to pick
    while True:
        try:
            choice = input(
                f"\n  Select a location (1-{len(geo_resp.locations)}) or 0 to skip: "
            ).strip()
            if choice == "0":
                print("  ⏭ Skipping location filter.")
                return (None, None)
            idx = int(choice) - 1
            if 0 <= idx < len(geo_resp.locations):
                selected = geo_resp.locations[idx]
                selected_id = selected.geo_id or (selected.tracking_urn or "").split(":")[-1]
                city = _extract_geo_city(selected.title or "")
                words = _extract_location_words(city)
                print(f"\n  ✅ Selected: {selected.title} (Geo ID: {selected_id})")
                return (selected_id, words)
            else:
                print(f"  ⚠ Invalid choice. Enter a number between 1 and {len(geo_resp.locations)}.")
        except (ValueError, EOFError, KeyboardInterrupt):
            print("\n  ⏭ Skipping location filter.")
            return (None, None)


# ---------------------------------------------------------------------------
# Smart fetcher with cap support
# ---------------------------------------------------------------------------


@dataclass
class FetchResult:
    companies: list[EntityResultViewModel] = field(default_factory=list)
    total_available: int = 0
    fetched: int = 0
    raw_responses: list[dict] = field(default_factory=list)  # Raw API responses


def fetch_with_cap(
    keywords: str,
    location: Optional[str] = None,
    cap: Optional[int] = None,
    cookie: Optional[str] = None,
    csrf: Optional[str] = None,
    delay: float = 5.0,
    max_retries: int = 3,
    verbose: bool = True,
    geo_filter_words: Optional[set[str]] = None,
) -> FetchResult:
    """Fetch companies with an optional cap and client-side geo filtering.

    When *cap* is set, the function paginates until it has exactly *cap*
    unique companies (or runs out of results).

    When *geo_filter_words* is provided, companies are filtered client-side
    by checking if their ``primarySubtitle`` contains any of the geo words.
    This is necessary because LinkedIn's Voyager API treats ``companyHqGeo``
    as a ranking signal rather than a strict filter.

    Parameters
    ----------
    keywords : str
        Search query.
    location : str, optional
        Geo URN ID (numeric) passed to the API's ``companyHqGeo`` param.
    cap : int, optional
        Maximum number of companies to return.
    cookie / csrf : str, optional
        Session credentials.
    delay : float
        Seconds to wait between pages.
    max_retries : int
        Retries per page on failure.
    verbose : bool
        Print progress to stdout.
    geo_filter_words : set[str], optional
        Location words extracted from the geo title (e.g. {"chennai"}).

    Returns
    -------
    FetchResult
        Deduplicated company list with metadata.
    """
    from module.linkedin_search import matches_geo_filter

    result = FetchResult()
    seen_urls: set[str] = set()
    page = 0
    per_page = 10
    consecutive_failures = 0
    geo_filtered_out = 0  # Count of companies skipped due to geo mismatch

    if verbose:
        print(f"\n{'=' * 60}")
        print(f"🔍 Searching: \"{keywords}\"")
        if location:
            print(f"📍 Location: {location}")
        if geo_filter_words:
            geo_label = " ".join(sorted(geo_filter_words))
            print(f"🗺️  Geo filter: {geo_label}")
        if cap:
            print(f"📊 Cap: {cap} companies")
        else:
            print("📊 Fetching ALL results")
        print(f"{'=' * 60}\n")

    while True:
        # Check if we've hit the cap
        if cap and result.fetched >= cap:
            if verbose:
                print(f"\n✅ Cap reached: {result.fetched} companies fetched.")
            break

        # Determine how many to request this page
        remaining = cap - result.fetched if cap else per_page
        request_count = min(per_page, remaining) if cap else per_page

        fetched = False
        last_response: Optional[SearchResponse] = None

        for attempt in range(1, max_retries + 1):
            try:
                resp, raw = search_companies(
                    keywords=keywords,
                    location=location,
                    start=page * per_page,
                    count=request_count,
                    cookie=cookie,
                    csrf_token=csrf,
                )
                result.raw_responses.append(raw)
                last_response = resp

                if page == 0:
                    result.total_available = resp.metadata.total_result_count
                    if verbose:
                        print(f"Total results on LinkedIn: {result.total_available}\n")

                # Deduplicate + geo filter
                new_companies = []
                for c in resp.companies:
                    url = c.navigation_url or ""
                    # Skip duplicates
                    if url in seen_urls or not url:
                        continue
                    seen_urls.add(url)

                    # Client-side geo filter
                    if geo_filter_words:
                        if not matches_geo_filter(c, geo_filter_words, search_keywords=keywords):
                            geo_filtered_out += 1
                            continue

                    new_companies.append(c)
                    result.fetched += 1

                    # Hard stop if cap reached mid-page
                    if cap and result.fetched >= cap:
                        break

                result.companies.extend(new_companies)

                if verbose:
                    if new_companies:
                        print_companies(new_companies, start=result.fetched - len(new_companies))
                    total_skipped = len(resp.companies) - len(new_companies)
                    if total_skipped > 0:
                        reasons = []
                        if geo_filtered_out > 0:
                            reasons.append(f"{geo_filtered_out} geo-filtered")
                        dupes = total_skipped - geo_filtered_out
                        if dupes > 0:
                            reasons.append(f"{dupes} duplicates")
                        print(f"  ({', '.join(reasons)} skipped)")

                consecutive_failures = 0
                fetched = True
                break

            except RuntimeError as e:
                error_msg = str(e)
                # Detect session expiry mid-fetch
                if "HTTP 401" in error_msg or "HTTP 403" in error_msg:
                    logger.warning("⚠ Session likely expired (HTTP 401/403).")
                    raise  # Re-raise so caller can refresh session
                wait = delay * attempt
                if verbose:
                    print(f"\n  ⚠ Error: {error_msg[:100]}, attempt {attempt}. Retrying in {wait}s…")
                time.sleep(wait)

            except Exception as e:
                wait = delay * attempt
                if verbose:
                    print(f"\n  ⚠ Error on page {page + 1}, attempt {attempt}: {e}")
                    print(f"  Retrying in {wait}s…")
                time.sleep(wait)

        if not fetched:
            if verbose:
                print(f"\n✗ Failed after {max_retries} retries. Stopping at page {page + 1}.")
                print(f"  Fetched {result.fetched} companies before failure.")
            break

        page += 1

        # Safety cap: LinkedIn shows ~1000 visible results max
        if page >= 100:
            if verbose:
                print(f"\n⚠ Page limit reached (100 pages). Stopping.")
            break

        # No more results on this page
        if last_response and len(last_response.companies) < request_count:
            if verbose:
                print(f"\n✅ No more results after page {page}.")
            break

        if verbose:
            print(f"\n{'—' * 60}")
            print(f"Page {page + 1} — {result.fetched} unique so far")
            time.sleep(delay)

    if verbose:
        print(f"\n{'=' * 60}")
        print(f"✅ Done! Fetched {result.fetched} unique companies.")
        if result.total_available:
            print(f"   (LinkedIn shows {result.total_available} total — capped by visibility)")
        print(f"{'=' * 60}\n")

    return result


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Convert text to a safe filename slug."""
    import re

    text = text.strip().lower()
    # Replace non-alphanumeric chars with hyphens
    text = re.sub(r"[^a-z0-9]+", "-", text)
    # Remove leading/trailing hyphens
    text = text.strip("-")
    return text or "search"


def resolve_output_path(
    output: Optional[str],
    keywords: Optional[str] = None,
    location: Optional[str] = None,
    fmt: str = "csv",
) -> str:
    """Determine the output file path, creating directories if needed.

    If *output* is not provided, generates a filename from the query
    keywords (and optional location), e.g.:
        "Real Estate" + "Mumbai"  →  real_estate_mumbai_20260413_173507.csv
    """
    if not output:
        from datetime import datetime

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        parts = []
        if keywords:
            parts.append(_slugify(keywords))
        if location:
            parts.append(_slugify(location))

        base = "_".join(parts) if parts else "linkedin_companies"
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        output = str(RESULTS_DIR / f"{base}_{ts}.{fmt}")

    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def save_results(
    companies: list[EntityResultViewModel],
    keywords: Optional[str] = None,
    location: Optional[str] = None,
    output: Optional[str] = None,
    fmt: Optional[str] = None,
    verbose: bool = True,
    raw_responses: Optional[list[dict]] = None,
    minimal: bool = True,
) -> str:
    """Save results to file.

    By default saves minimal clean JSON with only essential fields:
    company_name, industry_location, followers, description, logo_url,
    company_page_url, company_urn.

    Set minimal=False to save raw API responses (all fields).

    Parameters
    ----------
    companies : list
        Companies to save.
    keywords : str, optional
        Search keywords (used for auto-generated filename).
    location : str, optional
        Location filter (used for auto-generated filename).
    output : str, optional
        File path. Auto-generated from *keywords* if not provided.
    fmt : str, optional
        Always "json" (default). Kept for backward compatibility.
    verbose : bool
        Print confirmation message.
    raw_responses : list, optional
        Raw API response dicts from each page. Only used when minimal=False.
    minimal : bool
        If True (default), save only essential fields. If False, save raw API data.

    Returns
    -------
    str
        Path of the written file.
    """
    if not companies:
        if verbose:
            print("⚠ No companies to save.")
        return ""

    filepath = resolve_output_path(output, keywords=keywords, location=location, fmt="json")

    if minimal:
        # Minimal clean JSON — only essential fields for CSV conversion
        with open(filepath, "w", encoding="utf-8") as f:
            data = [c.to_minimal_dict() for c in companies]
            json.dump(data, f, indent=2, ensure_ascii=False)
    else:
        # Full raw API responses — exactly as LinkedIn returned them
        if raw_responses:
            output_data = {
                "search_query": keywords,
                "location": location,
                "total_pages_fetched": len(raw_responses),
                "total_companies": len(companies),
                "pages": raw_responses,
            }
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
        else:
            with open(filepath, "w", encoding="utf-8") as f:
                data = [c.to_dict() for c in companies]
                json.dump(data, f, indent=2, ensure_ascii=False)

    if verbose:
        print(f"💾 Saved {len(companies)} companies → {filepath}")

    return filepath


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scraper",
        description="LinkedIn Company Scraper — with automatic session management.\n"
                    "Saves raw LinkedIn API responses as JSON — zero field loss.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic search (saves JSON automatically)
  python scraper.py "Real Estate"

  # With location filter
  python scraper.py "Real Estate" -l "Mumbai"

  # Cap to 50 results
  python scraper.py "Real Estate" --cap 50

  # Custom output file
  python scraper.py "Software" -l "Bangalore" -o data/software_blr.json

  # Fetch ALL results
  python scraper.py "AI" --all

  # Force session refresh
  python scraper.py "Tech" --refresh-session

  # Show visible geo tags
  python scraper.py --list-geos
        """,
    )

    # Core arguments
    parser.add_argument(
        "keywords",
        nargs="?",
        default=None,
        help='Search keywords, e.g. "Real Estate"',
    )
    parser.add_argument(
        "-l", "--location",
        default=None,
        help='City or country name (e.g. "Mumbai", "India")',
    )
    parser.add_argument(
        "--cap",
        type=int,
        default=None,
        help="Maximum number of companies to fetch (overrides --all)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="fetch_all",
        help="Fetch ALL visible results (up to LinkedIn's ~1000 limit)",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output JSON file path (default: auto-generated from query)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help="Delay between pages in seconds (default: 5)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Max retries per page on failure (default: 3)",
    )

    # Session management
    parser.add_argument(
        "--refresh-session",
        action="store_true",
        help="Force a fresh stealth login before searching",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run stealth browser headless during session refresh",
    )
    parser.add_argument(
        "--test-session",
        action="store_true",
        help="Test current session and exit",
    )

    # Info
    parser.add_argument(
        "--list-geos",
        action="store_true",
        help="List supported geo locations and exit",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Save full raw API response (all fields). Default is minimal clean JSON.",
    )

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # --list-geos
    if args.list_geos:
        from module.linkedin_search import GEO_URN_MAP

        print("\n📍 Supported Geo Locations:\n")
        print(f"{'Location':<30} {'URN ID'}")
        print("-" * 60)
        for loc, urn in sorted(GEO_URN_MAP.items()):
            print(f"{loc:<30} {urn}")
        print()
        return 0

    # --test-session
    if args.test_session:
        import asyncio

        if not _env_has_credentials():
            logger.info("🔑 No session found. Extracting new session…")
            cookie, csrf = _refresh_session(headless=args.headless)
        else:
            cookie, csrf = _get_credentials()
            logger.info("Testing current session…")

        success = asyncio.run(test_session_with_api(cookie, csrf))
        return 0 if success else 1

    # Keywords are required
    if not args.keywords:
        parser.print_help()
        logger.error("Error: keywords argument is required.")
        return 1

    # -----------------------------------------------------------------------
    # 1. Ensure valid session
    # -----------------------------------------------------------------------
    cookie, csrf = ensure_session(
        headless=args.headless,
        force_refresh=args.refresh_session,
    )

    # -----------------------------------------------------------------------
    # 1.5. Resolve location via LinkedIn geo API if provided
    # -----------------------------------------------------------------------
    geo_urn: Optional[str] = None
    geo_filter_words: Optional[set[str]] = None
    location_display = args.location  # For output filename
    if args.location:
        geo_urn, geo_filter_words = resolve_location_interactive(
            location_query=args.location,
            cookie=cookie,
            csrf=csrf,
        )

    # -----------------------------------------------------------------------
    # 2. Fetch results (with cap or all)
    # -----------------------------------------------------------------------
    try:
        result = fetch_with_cap(
            keywords=args.keywords,
            location=geo_urn,
            cap=args.cap if args.cap else (None if args.fetch_all else None),
            cookie=cookie,
            csrf=csrf,
            delay=args.delay,
            max_retries=args.max_retries,
            geo_filter_words=geo_filter_words,
        )
    except RuntimeError as e:
        error_msg = str(e)
        if "HTTP 401" in error_msg or "HTTP 403" in error_msg:
            logger.warning("⚠ Session expired mid-fetch. Refreshing and retrying…")
            cookie, csrf = _refresh_session(headless=args.headless)
            result = fetch_with_cap(
                keywords=args.keywords,
                location=geo_urn,
                cap=args.cap,
                cookie=cookie,
                csrf=csrf,
                delay=args.delay,
                max_retries=args.max_retries,
                geo_filter_words=geo_filter_words,
            )
        else:
            raise

    # -----------------------------------------------------------------------
    # 3. Save results if requested
    # -----------------------------------------------------------------------
    if result.companies:
        save_results(
            result.companies,
            keywords=args.keywords,
            location=location_display,
            output=args.output,
            raw_responses=result.raw_responses or None,
            minimal=not args.full,
        )
    else:
        logger.warning("⚠ No companies found matching your criteria.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
