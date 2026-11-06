# Python LinkedIn company scraper

## Purpose

This project is a Python LinkedIn scraper for B2B company lead extraction and market research. The tool extracts company profiles, industry tags, follower counts, headquarter locations, descriptions, and LinkedIn URLs from search results.

You can run the scraper as a command line script for bulk data collection or import the functions as a Python library.

## Architecture

The system separates browser authentication from HTTP data extraction across two components.

```text
scraper.py                 CLI coordinator and session recovery manager
module/
  session_extractor.py     Playwright browser automation for login and cookie extraction
  linkedin_search.py       curl_cffi client for Voyager GraphQL API queries
  paths.py                 Path definitions for session state and output files
output/
  results/                 Default destination for extracted JSON and CSV files
  session/                 Cached Playwright browser storage
```

1. Session extraction. `module/session_extractor.py` launches Chromium using Playwright. It logs into LinkedIn, handles checkpoint challenges, and extracts the `li_at` cookie and `JSESSIONID` CSRF token. The script writes credentials to `.env` and stores browser context in `output/session/linkedin_session.json`.
2. Direct API communication. `module/linkedin_search.py` queries the internal LinkedIn Voyager GraphQL endpoint using `curl_cffi`. The client impersonates Firefox TLS and JA3 fingerprints. This approach avoids HTML page parsing and bot blocks.
3. Automatic session recovery. When LinkedIn returns HTTP 401 or HTTP 403 status codes during a run, `scraper.py` triggers a browser session refresh, updates tokens in `.env`, and resumes pagination from the current page offset.
4. Response parsing. Pydantic models validate raw JSON payloads from the `voyagerSearchDashClusters` endpoint. The parser maps records into structured company models.

## Setup

### Prerequisites

Install Python 3.10 or newer.

### Installation

Clone the repository and install required packages:

```bash
git clone https://github.com/devsanthoshmk/linkedin-companies-scraper.py.git
cd linkedin-companies-scraper.py
pip install playwright curl-cffi pydantic python-dotenv
playwright install chromium
```

### Environment variables

Create a `.env` file in the project root:

```env
LINKEDIN_EMAIL=your_email@example.com
LINKEDIN_PASSWORD=your_password
```

On the first run, Playwright logs in with these credentials. The script writes `LI_COOKIE` and `LI_CSRF_TOKEN` into `.env` automatically. If you already have active session cookies from your browser, you can provide them directly:

```env
LI_COOKIE=your_li_at_cookie_value
LI_CSRF_TOKEN="ajax:your_jsessionid_value"
```

## Usage

### Command line interface

The primary CLI entry point is `scraper.py`.

Run a search query by company keyword:

```bash
python scraper.py "Software" --cap 50
```

Filter results by location:

```bash
python scraper.py "Real Estate" --location "Mumbai" --cap 20
```

Scrape all visible search results up to the platform pagination limit:

```bash
python scraper.py "Fintech" --location "London" --all
```

Save full raw GraphQL responses with all metadata fields:

```bash
python scraper.py "Healthcare" --cap 30 --full
```

Verify active session credentials against the LinkedIn API:

```bash
python scraper.py --test-session
```

Print preset location names:

```bash
python scraper.py --list-geos
```

#### Command line options

| Option | Type | Default | Description |
|---|---|---|---|
| `keywords` | string | none | Search keywords. Required unless running information commands. |
| `-l, --location` | string | none | City or country name. Matches presets or starts interactive typeahead. |
| `--cap` | integer | none | Maximum number of deduplicated companies to collect. |
| `--all` | flag | false | Scrape all visible search results up to approximately 1000 items. |
| `-o, --output` | string | auto | Custom path for the output file. |
| `--delay` | float | 5.0 | Pause between page requests in seconds. |
| `--max-retries` | integer | 3 | Retry attempts per failed page before skipping. |
| `--refresh-session` | flag | false | Force a browser login before starting the search. |
| `--headless` | flag | false | Run Playwright in headless mode during session extraction. |
| `--test-session` | flag | false | Test active session tokens with an API call and exit. |
| `--list-geos` | flag | false | Print all 28 preset geographic location names and exit. |
| `--full` | flag | false | Save complete raw GraphQL page payloads instead of cleaned records. |

### Secondary commands

Extract session tokens manually:

```bash
python -m module.session_extractor --email your_email@example.com --password your_password
```

Run API queries directly from the search module:

```bash
python -m module.linkedin_search "Biotechnology" --location "Boston" --count 10
```

Run test suite:

```bash
python tests/test_session.py
```

### Python library usage

Import `search_companies` to integrate scraping into Python pipelines:

```python
from module.linkedin_search import search_companies

result, raw_response = search_companies(
    keywords="Cybersecurity",
    location="San Francisco",
    start=0,
    count=25,
)

print(f"Total count: {result.metadata.total_result_count}")
for company in result.companies:
    name = company.title.text if company.title else "Unknown"
    print(f"{name}: {company.navigation_url}")
```

## Configuration

### Geographic locations

The scraper contains 28 preset location shortcuts:
- Locations in India include Bangalore, Bengaluru, Mumbai, Delhi, Chennai, Hyderabad, Pune, Kolkata, Ahmedabad, Kochi, Coimbatore, Jaipur, Chandigarh, Gurugram, Gurgaon, Noida, Thane, Navi Mumbai, and India.
- Global locations include United States, USA, New York, San Francisco Bay Area, London, United Kingdom, Singapore, Dubai, and UAE.

If you pass a location not present in the shortcut list, the scraper queries LinkedIn's typeahead API and displays an interactive menu so you can select the correct geographic identifier.

### Delays and rate limits

LinkedIn limits search request frequencies. Keep `--delay` at 3.0 seconds or higher during large extractions. The client adds a random delay between 0.5 and 2.0 seconds before every HTTP request to avoid uniform timing patterns.

### Session management

Session extraction opens a visible browser window by default. If LinkedIn displays a captcha or two factor verification screen, you can solve it in the open browser. Use `--headless` when executing on remote servers without graphical displays.

## Output format

The scraper saves default results to `output/results/<query>_<location>_<timestamp>.json`.

Each entry in the default minimal format contains 7 fields:

```json
[
  {
    "company_name": "Acme Analytics",
    "industry_location": "Information Technology • New York, NY",
    "followers": "25K followers",
    "description": "Provider of enterprise analytics platforms.",
    "logo_url": "https://media.licdn.com/dms/image/v2/...",
    "company_page_url": "https://www.linkedin.com/company/acme-analytics",
    "company_urn": "urn:li:company:12345678"
  }
]
```

When you use the `--full` flag, the output contains the complete unprocessed GraphQL responses across all retrieved pages.

## Known limitations

1. Visible result limit. LinkedIn caps search results at 100 pages of 10 items. Queries return a maximum of approximately 1,000 companies.
2. Proxy support. The client routes requests through the local network IP address.
3. Account rate limits. Aggressive scraping volume can trigger temporary account restrictions. Use reasonable caps and request delays.

## Documentation links

Detailed guides are available in the [`docs/`](docs) directory:
- [`docs/cli.md`](docs/cli.md) provides reference for CLI arguments.
- [`docs/module.md`](docs/module.md) provides reference for Python module functions and data models.
- [`docs/architecture.md`](docs/architecture.md) explains system design and network flow.
- [`docs/configuration.md`](docs/configuration.md) explains setup options and environment keys.
- [`docs/error-handling.md`](docs/error-handling.md) explains recovery steps for authentication and network errors.
