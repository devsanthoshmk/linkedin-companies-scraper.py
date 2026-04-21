# CLI Reference

This project currently exposes 4 executable entry points:
- `python scraper.py` (primary)
- `python -m module.session_extractor`
- `python -m module.linkedin_search`
- `python tests/test_session.py`

## 1) `python scraper.py`

Main production CLI with automatic session management and JSON output.

## Usage

```bash
python scraper.py [keywords] [options]
```

## Arguments and Flags

- `keywords` (positional): search keywords (for example `"Real Estate"`).
- `-l, --location LOCATION`: city/country query.
- `--cap CAP`: max number of companies to fetch.
- `--all`: fetch all visible results (around 1000 max).
- `-o, --output OUTPUT`: output JSON path.
- `--delay DELAY`: delay between pages in seconds (default `5.0`).
- `--max-retries MAX_RETRIES`: retries per page (default `3`).
- `--refresh-session`: force fresh session before fetching.
- `--headless`: run browser headless during session extraction.
- `--test-session`: validate session and exit.
- `--list-geos`: print built-in `GEO_URN_MAP` and exit.
- `--full`: save full raw API pages; default is minimal clean JSON.

## Behavior Notes

- If `--list-geos` is used, scraper exits without requiring `keywords`.
- If `--test-session` is used, scraper exits after session check.
- If `keywords` is missing and neither info/test flag is used, help is shown and exit code is `1`.
- Location handling is interactive when the input is not found in built-in geo map:
  - It queries LinkedIn geo typeahead.
  - If one location is returned, it auto-selects.
  - If multiple are returned, it prompts selection.
  - If you cancel/invalid input, location filtering is skipped.
- On HTTP `401/403` during fetch, scraper refreshes session and retries once.

## Output Behavior

- Default output: JSON in `output/results/`.
- Default format: minimal records (`to_minimal_dict()` fields).
- With `--full`: saves raw paginated API responses:
  - `search_query`
  - `location`
  - `total_pages_fetched`
  - `total_companies`
  - `pages`

## Examples

```bash
# Basic search
python scraper.py "Real Estate" --cap 20

# Interactive location resolution
python scraper.py "Software" -l "Bangalore" --cap 30

# Explicit output path
python scraper.py "AI" --cap 10 -o output/results/ai.json

# Save full raw responses
python scraper.py "Fintech" --cap 10 --full

# Test and exit
python scraper.py --test-session

# List built-in geos
python scraper.py --list-geos
```

## Edge Cases

- `--all` currently does not change behavior when `--cap` is omitted; fetch defaults to uncapped in current code path.
- Large uncapped runs can be long and are subject to LinkedIn visibility and anti-bot behavior.
- Network/DNS failures surface as request exceptions from `curl_cffi`.

## Exit Codes

- `0` on success.
- `1` when required search keywords are missing (normal search mode).
- `1` when `--test-session` fails.

---

## 2) `python -m module.session_extractor`

Stealth Playwright login flow to create/refresh LinkedIn API session credentials.

## Usage

```bash
python -m module.session_extractor [options]
```

## Flags

- `--email EMAIL`: LinkedIn email (optional; defaults to `.env`).
- `--password PASSWORD`: LinkedIn password (optional; defaults to `.env`).
- `--headless`: run browser headless.
- `--test`: test extracted session after login.

## Side Effects

- Writes/updates `.env` keys:
  - `LI_COOKIE`
  - `LI_CSRF_TOKEN`
- Writes storage state JSON to:
  - `output/session/linkedin_session.json`

## Example

```bash
python -m module.session_extractor --test
```

---

## 3) `python -m module.linkedin_search`

Low-level search CLI for direct API calls and geo lookups.

## Usage

```bash
python -m module.linkedin_search [keywords] [options]
```

## Arguments and Flags

- `keywords` positional.
- `-l, --location LOCATION`
- `-s, --start START` (default `0`)
- `-c, --count COUNT` (default `10`)
- `--cookie COOKIE`
- `--csrf CSRF`
- `--all`
- `-o, --output OUTPUT` (`.csv` or `.json`, inferred from extension; defaults to CSV if no extension)
- `--delay DELAY` (default `3.0`)
- `--geo LOCATION` (geo typeahead lookup mode)
- `--minimal` (minimal field output in writer)

## Examples

```bash
# Single page
python -m module.linkedin_search "Real Estate" -c 10

# Geo lookup only
python -m module.linkedin_search --geo "vandavasi"

# Fetch all and write CSV
python -m module.linkedin_search "AI" --all -o output/results/ai.csv
```

## Edge Cases

- In `--all` mode, this CLI currently calls `search_companies()` without unpacking the `(SearchResponse, raw_dict)` tuple.
- That mismatch can break `--all` execution in current code.
- Single-page mode is unaffected.

---

## 4) `python tests/test_session.py`

Simple integration check that loads `.env` credentials and performs a test search call.

## Usage

```bash
python tests/test_session.py
```

## Behavior

- Prints session credential presence summary.
- Calls `search_companies(keywords="test", count=5, ...)`.
- Returns exit code `0` for success, `1` for failure.
