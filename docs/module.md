# Module Reference

Code is organized under `module/` with three Python modules:
- `module.linkedin_search`
- `module.session_extractor`
- `module.paths`

`module.__init__` does not currently re-export symbols.

## `module.paths`

Centralized path constants:
- `PROJECT_ROOT`
- `OUTPUT_DIR`
- `RESULTS_DIR`
- `PROGRESS_DIR`
- `SESSION_DIR`

These are `pathlib.Path` objects and are used by both CLI and module code.

## `module.session_extractor`

Session bootstrap and validation utilities.

## Key Functions

- `load_credentials() -> tuple[str | None, str | None]`
- `extract_session(email=None, password=None, headless=False, output_dir=None) -> tuple[str, str]`
- `test_session_with_api(cookie=None, csrf=None) -> bool`
- `update_env_file(cookie_string, csrf_token) -> None`
- `format_cookie_string(cookies) -> str`

## Runtime Effects

- Reads `LINKEDIN_EMAIL`/`LINKEDIN_USERNAME` and `LINKEDIN_PASSWORD`.
- Writes `LI_COOKIE` and `LI_CSRF_TOKEN` to `.env` at project root.
- Writes browser storage JSON to `output/session/linkedin_session.json` (default).

## Programmatic Usage

```python
import asyncio
from module.session_extractor import extract_session, test_session_with_api

cookie, csrf = asyncio.run(extract_session(headless=True))
ok = asyncio.run(test_session_with_api(cookie, csrf))
print(ok)
```

## `module.linkedin_search`

Low-level LinkedIn Voyager API client and response models.

## Models

- `TextViewModel`
- `VectorArtifact`
- `VectorImage`
- `NonEntityCompanyLogo`
- `ImageDetailData`
- `ImageAttribute`
- `ImageViewModel`
- `NavigationContext`
- `EntityResultViewModel`
- `SearchMetadata`
- `PaginationMetadata`
- `SearchResponse`
- `GeoResult`
- `GeoTypeaheadResponse`

## Primary Public API

- `search_companies(keywords, location=None, start=0, count=10, cookie=None, csrf_token=None) -> tuple[SearchResponse, dict]`
- `search_geo_locations(keywords, cookie=None, csrf_token=None) -> GeoTypeaheadResponse`
- `matches_geo_filter(company, geo_filter_words, search_keywords=None) -> bool`
- `write_companies(companies, output_path=None, fmt="csv", minimal=False) -> str`
- `fetch_all_companies(keywords, location=None, cookie=None, csrf_token=None, delay=5.0, max_retries=3) -> list[EntityResultViewModel]`
- `print_results(results)`
- `print_companies(companies, start=0)`
- `print_geo_results(results)`
- `GEO_URN_MAP` (dict of common location aliases to geo IDs)

## `EntityResultViewModel` convenience properties

- `name`
- `location`
- `followers`
- `description`
- `logo_url`
- `company_id`

## `EntityResultViewModel` serialization helpers

- `to_dict()`
- `to_minimal_dict()`

## Integration Example

```python
import os
from dotenv import load_dotenv
from module.linkedin_search import search_companies

load_dotenv()

result, raw = search_companies(
    keywords="Real Estate",
    location="Mumbai",
    start=0,
    count=10,
    cookie=os.getenv("LI_COOKIE"),
    csrf_token=os.getenv("LI_CSRF_TOKEN"),
)

print("total:", result.metadata.total_result_count)
for company in result.companies[:3]:
    print(company.name, company.location, company.navigation_url)
```

## Output Integration Example

```python
from module.linkedin_search import write_companies

# Minimal JSON
write_companies(result.companies, "output/results/companies.json", fmt="json", minimal=True)

# Full CSV
write_companies(result.companies, "output/results/companies.csv", fmt="csv", minimal=False)
```

## Notes for Integrators

- If `cookie`/`csrf_token` are omitted, the client reads `LI_COOKIE` and `LI_CSRF_TOKEN` from environment.
- `search_companies()` returns a tuple `(parsed_model, raw_json_dict)`.
- LinkedIn-specific anti-bot or auth failures are raised as exceptions (for example non-200 HTTP statuses).
