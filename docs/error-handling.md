# Error Handling and Troubleshooting

## Session and Auth Errors

## Symptoms

- `HTTP 401` or `HTTP 403` from LinkedIn.
- `"LI_COOKIE or LI_CSRF_TOKEN missing from .env"`.
- Session test fails in `python tests/test_session.py`.

## What current code does

- `scraper.py` validates session before search.
- If missing/invalid, it runs session refresh automatically.
- If 401/403 appears mid-fetch, it refreshes session and retries.

## Recovery

```bash
python -m module.session_extractor --test
python scraper.py "Real Estate" --cap 20 --refresh-session
```

## Network/DNS Errors

Example: `curl: (6) Could not resolve host: www.linkedin.com`

This is infrastructure/network resolution failure, not parser logic failure. Check:
- DNS and internet reachability
- firewall/proxy restrictions
- execution environment sandbox/network policy

## Empty or Low Quality Results

Causes:
- restrictive location filters
- geo selection skipped/cancelled
- LinkedIn ranking/visibility limitations

Checks:
- run without location filter
- use smaller cap first (`--cap 10`)
- verify session using `--test-session`

## Output File Issues

- If no output path is provided, files are written under `output/results/`.
- Parent directories are created automatically.
- If no companies match, scraper logs warning and may skip writing.

## Known Code-Level Edge Cases

- In current `scraper.py`, uncapped behavior is default even without `--all`.
- In current `module.linkedin_search` CLI, `--all` mode has a tuple-handling mismatch and may fail.

These are documented to reflect present behavior.
