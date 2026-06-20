# Lead Generation Scraping Platform V1

A fault-tolerant scraping platform built for Google Maps lead generation. Workers are ephemeral; Supabase is the permanent source of truth.

## What is included

- `worker.py`: Playwright worker loop with atomic job claiming, heartbeats, and deduped business inserts.
- `recovery.py`: Stale worker recovery and failed-job retry logic.
- `supabase_schema.sql`: Supabase/PostgreSQL schema and atomic claim function.
- `.env.example`: Example configuration for local or Colab runs.

## Setup

1. Create a Supabase project.
2. Run `supabase_schema.sql` in the Supabase SQL editor.
3. Create a `.env` file from `.env.example` and set `SUPABASE_URL` and `SUPABASE_KEY`.

## Install

```bash
pip install playwright supabase python-dotenv
playwright install chromium
```

## Run a worker

```bash
python worker.py
```

## Run recovery

```bash
python recovery.py
```

## Job flow

1. Worker registers itself in `workers`.
2. Worker claims one pending job atomically using `claim_pending_job`.
3. Worker scrapes Google Maps for the tile.
4. Worker inserts deduplicated businesses into `businesses`.
5. Worker marks the job `completed` or `failed`.
6. Heartbeats are written every 60 seconds.

## Notes

- Workers should use restricted Supabase credentials.
- Duplicate business inserts are prevented via `place_id` and fingerprint fallback.
- Stale running jobs are reset after `STALE_THRESHOLD_MIN` minutes.
- Failed jobs are requeued after `FAILED_RECOVER_MIN` minutes.

## Future improvements

- proxy support
- richer detail extraction for website / phone / socials
- thin API layer between worker and Supabase
- job generation from tile lists
