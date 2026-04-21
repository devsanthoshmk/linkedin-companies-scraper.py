"""Test script to verify LinkedIn session is working.

Reads LI_COOKIE and LI_CSRF_TOKEN from .env and makes a test API call.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from module.paths import PROJECT_ROOT as MODULE_PROJECT_ROOT

# Load local project .env first, then allow inherited env/ancestor .env
load_dotenv(MODULE_PROJECT_ROOT / ".env")
load_dotenv()


def test_session():
    """Test LinkedIn session by making a single API call."""
    cookie = os.getenv("LI_COOKIE")
    csrf = os.getenv("LI_CSRF_TOKEN")

    if not cookie or not csrf:
        print("❌ Session credentials not found in .env")
        print("Run: python -m module.session_extractor --test")
        print("\nNote: Ensure credentials exist in environment or .env")
        return False

    print("Testing LinkedIn session...")
    print(f"Cookie length: {len(cookie)}")
    print(f"CSRF token: {csrf[:20]}...")

    try:
        from module.linkedin_search import search_companies

        result, _raw = search_companies(
            keywords="test",
            start=0,
            count=5,
            cookie=cookie,
            csrf_token=csrf,
        )

        print(f"\n✅ Session is valid!")
        print(f"Total results: {result.metadata.total_result_count}")
        print(f"Companies returned: {len(result.companies)}")

        if result.companies:
            print("\nSample results:")
            for i, company in enumerate(result.companies[:3], 1):
                print(f"  {i}. {company.name} — {company.location}")

        return True

    except Exception as e:
        print(f"\n❌ Session test failed: {e}")
        print("\nYour session may have expired.")
        print("Run: python -m module.session_extractor")
        return False


if __name__ == "__main__":
    import sys

    success = test_session()
    sys.exit(0 if success else 1)
