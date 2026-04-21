# Architecture

## Core Idea

The project separates concerns between:
- orchestration (`scraper.py`)
- low-level LinkedIn API access (`module/linkedin_search.py`)
- session extraction and refresh (`module/session_extractor.py`)
- path conventions (`module/paths.py`)

This keeps the top-level CLI stable while internal API/session logic evolves.

## Components

- `scraper.py`
  - Main user-facing CLI.
  - Validates/refreshes session.
  - Resolves location to geo ID (interactive when needed).
  - Paginates with retries and deduplication.
  - Saves minimal or full JSON output.
- `module/linkedin_search.py`
  - Voyager GraphQL request construction.
  - Geo typeahead endpoint calls.
  - Pydantic models for normalized parsing.
  - Convenience printers/writers.
- `module/session_extractor.py`
  - Playwright login flow with stealth-style browser setup.
  - Cookie + CSRF extraction.
  - `.env` update and session verification.
- `module/paths.py`
  - Shared output path constants.

## End-to-End Scraping Flow

1. User runs `python scraper.py ...`.
2. CLI parses flags and mode:
   - info/test mode (`--list-geos`, `--test-session`) or search mode.
3. Search mode checks for valid `LI_COOKIE` + `LI_CSRF_TOKEN`.
4. If missing/expired/forced refresh, extractor runs to produce new credentials.
5. Optional location query is resolved:
   - built-in geo map direct hit, or
   - LinkedIn geo typeahead + optional interactive selection.
6. Fetch loop executes via `search_companies()`:
   - paginated requests
   - deduplication by `navigation_url`
   - optional client-side geo filtering
   - retry logic on failures.
7. If HTTP 401/403 appears mid-run, session refresh is triggered and fetch retried.
8. Results are written to disk:
   - minimal clean JSON by default
   - full raw API pages with `--full`.

## Data and Directory Flow

- Session artifacts:
  - `.env` (`LI_COOKIE`, `LI_CSRF_TOKEN`)
  - `output/session/linkedin_session.json`
- Search outputs:
  - `output/results/*.json` (via `scraper.py`)
  - optional CSV/JSON from `module.linkedin_search` writer helpers
- Progress snapshots for legacy all-pages flow:
  - `output/progress/companies_progress.csv`

## Design Decisions

- Keep `scraper.py` at repo root as the stable operator entry point.
- Keep reusable and testable internals in `module/`.
- Preserve raw response access for debugging/auditing while defaulting to cleaner minimal output.
- Use Pydantic models to keep parsing strict and explicit.
- Centralize output paths so all components write to consistent locations.
