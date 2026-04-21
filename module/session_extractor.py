"""LinkedIn session extractor using Playwright in stealth mode.

Logs in with email/password and extracts the cookies + CSRF token
needed by module.linkedin_search
"""

import asyncio
import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlencode

from playwright.async_api import async_playwright, BrowserContext, Page
from dotenv import load_dotenv
from module.paths import PROJECT_ROOT, SESSION_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stealth configuration
# ---------------------------------------------------------------------------

REALISTIC_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)

STEALTH_SCRIPT = """
// Disable navigator.webdriver
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Spoof plugins length
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5]
});

// Spoof languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en']
});

// Spoof chrome runtime
window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };

// Override permissions
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);

// Remove automation indicators
delete navigator.__proto__.webdriver;
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def human_typing(page: Page, selector: str, text: str) -> None:
    """Type text with human-like delays."""
    element = await page.wait_for_selector(selector, timeout=10000)
    await element.click()
    await asyncio.sleep(random.uniform(0.2, 0.5))

    for char in text:
        await page.keyboard.type(char, delay=random.uniform(30, 100))
        await asyncio.sleep(random.uniform(0.01, 0.05))


async def smooth_mouse_move(page: Page, x: int, y: int) -> None:
    """Move mouse with realistic easing."""
    await page.mouse.move(x, y, steps=random.randint(8, 15))
    await asyncio.sleep(random.uniform(0.1, 0.3))


async def warm_up_browser(page: Page) -> None:
    """Visit normal sites to appear more human-like."""
    sites = [
        "https://www.google.com",
        "https://www.wikipedia.org",
    ]

    logger.info("Warming up browser...")
    for site in sites:
        try:
            await smooth_mouse_move(page, random.randint(300, 800), random.randint(200, 500))
            await page.goto(site, wait_until="domcontentloaded", timeout=10000)
            await asyncio.sleep(random.uniform(1.0, 2.0))
            logger.debug(f"Visited {site}")
        except Exception as e:
            logger.debug(f"Could not visit {site}: {e}")


def load_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Load LinkedIn credentials from .env."""
    load_dotenv()
    email = os.getenv("LINKEDIN_EMAIL") or os.getenv("LINKEDIN_USERNAME")
    password = os.getenv("LINKEDIN_PASSWORD")
    return email, password


def format_cookie_string(cookies: list[dict]) -> str:
    """Format cookies as a single string for the Cookie header."""
    parts = []
    for c in cookies:
        value = c['value']
        # Remove surrounding quotes if present
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        parts.append(f"{c['name']}={value}")
    return "; ".join(parts)


def update_env_file(cookie_string: str, csrf_token: str) -> None:
    """Update .env file with new LinkedIn credentials."""
    env_path = PROJECT_ROOT / ".env"

    lines = []
    if env_path.exists():
        lines = env_path.read_text().splitlines()

    # Remove old LI_COOKIE and LI_CSRF_TOKEN lines
    lines = [
        line for line in lines
        if not line.startswith("LI_COOKIE=") and not line.startswith("LI_CSRF_TOKEN=")
    ]

    # Append new credentials
    lines.append("")
    lines.append("# LinkedIn API credentials (auto-generated from session)")
    lines.append(f"LI_COOKIE={cookie_string}")
    lines.append(f"LI_CSRF_TOKEN={csrf_token}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info(f"Updated .env file at {env_path}")


# ---------------------------------------------------------------------------
# Core: stealth login + session extraction
# ---------------------------------------------------------------------------

async def extract_session(
    email: Optional[str] = None,
    password: Optional[str] = None,
    headless: bool = False,
    output_dir: Optional[str] = None,
) -> Tuple[str, str]:
    """Login to LinkedIn and extract session cookies + CSRF token.

    Parameters
    ----------
    email : str, optional
        LinkedIn email. Falls back to .env.
    password : str, optional
        LinkedIn password. Falls back to .env.
    headless : bool
        Run browser headless (default: False for debugging).
    output_dir : str, optional
        Directory to save session JSON.

    Returns
    -------
    Tuple[str, str]
        (cookie_string, csrf_token)
    """
    # Load credentials
    if not email or not password:
        env_email, env_password = load_credentials()
        email = email or env_email
        password = password or env_password

    if not email or not password:
        raise ValueError(
            "LinkedIn credentials not found. "
            "Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD in .env"
        )

    output_dir = output_dir or str(SESSION_DIR)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        # Launch with stealth-like settings
        browser = await pw.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )

        # Create context with realistic settings
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=REALISTIC_USER_AGENT,
            locale="en-US",
            timezone_id="Asia/Kolkata",
        )

        # Apply stealth script
        await context.add_init_script(STEALTH_SCRIPT)

        page = await context.new_page()

        try:
            # Step 1: Warm up browser
            await warm_up_browser(page)

            # Step 2: Navigate to LinkedIn login
            logger.info("Navigating to LinkedIn login...")
            await smooth_mouse_move(page, 600, 400)
            await page.goto(
                "https://www.linkedin.com/login",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await asyncio.sleep(random.uniform(1.0, 2.0))

            # Step 3: Fill credentials with human-like behavior
            logger.info("Entering credentials...")

            # Email
            await human_typing(page, "#username", email)
            await asyncio.sleep(random.uniform(0.3, 0.8))

            # Password
            await human_typing(page, "#password", password)
            await asyncio.sleep(random.uniform(0.3, 0.8))

            # Step 4: Submit form
            await smooth_mouse_move(page, 500, 600)
            await asyncio.sleep(random.uniform(0.2, 0.5))

            submit_btn = await page.wait_for_selector(
                'button[type="submit"]', timeout=10000
            )
            await submit_btn.click()

            # Step 5: Wait for navigation
            logger.info("Waiting for login to complete...")
            try:
                await page.wait_for_url(
                    lambda url: (
                        "feed" in url
                        or "checkpoint" in url
                        or "challenge" in url
                        or "authwall" in url
                    ),
                    timeout=60000,
                )
            except Exception:
                logger.warning("Navigation timeout — checking current state...")

            # Step 6: Check for security checkpoints
            current_url = page.url
            if any(x in current_url for x in ["checkpoint", "challenge"]):
                logger.warning(
                    "⚠ Security checkpoint detected. "
                    "Please complete it manually in the browser..."
                )
                # Wait up to 5 minutes for manual completion
                for _ in range(300):
                    if "feed" in page.url:
                        break
                    await asyncio.sleep(1)
                else:
                    raise RuntimeError("Manual login timed out")

            if "authwall" in current_url or "login" in current_url:
                raise RuntimeError(
                    f"Login failed. Current URL: {current_url}. "
                    "Check your credentials."
                )

            # Step 7: Verify login
            logger.info("Verifying login...")
            await asyncio.sleep(2)

            if "feed" not in page.url:
                logger.warning(
                    f"Not on feed page (URL: {page.url}). "
                    "Proceeding anyway — session may still be valid."
                )

            # Step 8: Extract cookies
            logger.info("Extracting session cookies...")
            cookies = await context.cookies()

            # Format cookie string
            cookie_string = format_cookie_string(cookies)

            # Extract CSRF token (JSESSIONID)
            jsessions = [c for c in cookies if c["name"] == "JSESSIONID"]
            if not jsessions:
                raise RuntimeError("JSESSIONID cookie not found")

            csrf_token = jsessions[0]["value"]
            # Remove quotes if present
            if csrf_token.startswith('"') and csrf_token.endswith('"'):
                csrf_token = csrf_token[1:-1]

            # Step 9: Save session to JSON
            session_path = Path(output_dir) / "linkedin_session.json"
            storage = await context.storage_state()
            session_path.write_text(json.dumps(storage, indent=2), encoding="utf-8")
            logger.info(f"Session saved to {session_path}")

            # Step 10: Update .env file
            update_env_file(cookie_string, csrf_token)

            logger.info("✅ Session extraction complete!")
            return cookie_string, csrf_token

        finally:
            await browser.close()


# ---------------------------------------------------------------------------
# Quick test: verify session works with the API
# ---------------------------------------------------------------------------

async def test_session_with_api(
    cookie: Optional[str] = None,
    csrf: Optional[str] = None,
) -> bool:
    """Test extracted session by calling the Voyager API.

    Makes a single search_companies() call and verifies it succeeds.
    """
    if not cookie or not csrf:
        load_dotenv()
        cookie = cookie or os.getenv("LI_COOKIE")
        csrf = csrf or os.getenv("LI_CSRF_TOKEN")

    if not cookie or not csrf:
        raise ValueError("Session credentials not found in .env")

    logger.info("Testing session with Voyager API...")

    try:
        from module.linkedin_search import search_companies

        result, _raw = search_companies(
            keywords="test",
            start=0,
            count=1,
            cookie=cookie,
            csrf_token=csrf,
        )

        logger.info(
            f"✅ Session is valid! "
            f"Total results: {result.metadata.total_result_count}"
        )
        return True

    except Exception as e:
        logger.error(f"❌ Session test failed: {e}")
        return False


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract LinkedIn session via stealth login")
    parser.add_argument("--email", help="LinkedIn email")
    parser.add_argument("--password", help="LinkedIn password")
    parser.add_argument("--headless", action="store_true", help="Run headless")
    parser.add_argument("--test", action="store_true", help="Test session after extraction")
    args = parser.parse_args()

    cookie_str, csrf_str = asyncio.run(
        extract_session(
            email=args.email,
            password=args.password,
            headless=args.headless,
        )
    )

    if args.test:
        success = asyncio.run(test_session_with_api(cookie_str, csrf_str))
        exit(0 if success else 1)
