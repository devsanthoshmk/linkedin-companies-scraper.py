# LinkedIn Company Search Scraper

Professional LinkedIn company scraper that works both as:
- a CLI tool (`scraper.py`) with automatic session management
- an importable Python module (`module/`)

Detailed docs are in [`docs/`](docs).

## Project Structure

```text
linkedin/
├── scraper.py
├── module/
│   ├── __init__.py
│   ├── linkedin_search.py
│   ├── session_extractor.py
│   └── paths.py
├── tests/
│   └── test_session.py
├── output/
│   ├── results/
│   ├── progress/
│   └── session/
└── docs/
    ├── architecture.md
    ├── cli.md
    ├── configuration.md
    ├── contributing.md
    ├── error-handling.md
    └── module.md
```

## Installation / Quick Start

```bash
pip install playwright curl-cffi pydantic python-dotenv
playwright install chromium
```

Create `.env` at project root:

```env
LINKEDIN_EMAIL=your_email
LINKEDIN_PASSWORD=your_password
```

Run:

```bash
python scraper.py "Real Estate" --cap 20
```

## CLI Usage

Primary command:

```bash
python scraper.py [keywords] [options]
```

Flags:
- `keywords` positional, optional only when using info/test flags
- `-l, --location` city/country query (interactive LinkedIn geo picker if not in built-in map)
- `--cap INT` max number of companies
- `--all` fetch all visible results (up to around 1000)
- `-o, --output PATH` output JSON path
- `--delay FLOAT` delay between pages (default `5.0`)
- `--max-retries INT` retries per page (default `3`)
- `--refresh-session` force fresh login before search
- `--headless` run session refresh browser headless
- `--test-session` test session and exit
- `--list-geos` print built-in geo map and exit
- `--full` save full raw API pages instead of minimal JSON

Other CLI entry points:
- `python -m module.session_extractor [--email --password --headless --test]`
- `python -m module.linkedin_search [keywords] [--all --geo ...]`
- `python tests/test_session.py`

Full CLI reference: [`docs/cli.md`](docs/cli.md)

## Module Usage

```python
from module.linkedin_search import search_companies

result, raw = search_companies(
    keywords="Real Estate",
    location="Mumbai",  # optional
    start=0,
    count=10,
)

print(result.metadata.total_result_count)
print(len(result.companies))
```

Full module/API docs: [`docs/module.md`](docs/module.md)

## Full Documentation

See [`docs/`](docs) for:
- CLI reference
- module API reference
- architecture and scraping flow
- configuration
- error handling
- contribution guide
