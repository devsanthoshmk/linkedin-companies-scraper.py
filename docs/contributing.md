# Contributing

## Scope

This repository is currently scraper-focused:
- root CLI in `scraper.py`
- reusable internals in `module/`
- runtime checks in `tests/`
- documentation in `docs/`

## Setup

```bash
pip install playwright curl-cffi pydantic python-dotenv
playwright install chromium
```

Create `.env` with LinkedIn credentials and generate session:

```bash
python -m module.session_extractor --test
```

## Validation Before PR

Run:

```bash
python -m compileall -q scraper.py module tests
python tests/test_session.py
python scraper.py "Real Estate" --cap 2
```

Notes:
- Network access is required for integration commands.
- `tests/test_session.py` is an integration script (not isolated unit tests).

## Documentation Rule

If behavior changes, update:
- `README.md` (minimal user-facing entry)
- relevant files in `docs/`

Docs should mirror current code behavior, including known limitations.
