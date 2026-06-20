import os
import logging
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
STALE_THRESHOLD_MIN = int(os.getenv("STALE_THRESHOLD_MIN", "15"))
FAILED_RECOVER_MIN = int(os.getenv("FAILED_RECOVER_MIN", "60"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("lead-recovery")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def recover_stale_running_jobs():
    stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_THRESHOLD_MIN)
    response = supabase.table("workers").select("worker_id").lt("last_heartbeat", stale_cutoff.isoformat()).execute()
    if response.error:
        logger.error("Failed to query stale workers: %s", response.error)
        return

    stale_workers = [row["worker_id"] for row in (response.data or [])]
    if not stale_workers:
        logger.info("No stale workers found.")
        return

    logger.info("Resetting jobs assigned to stale workers: %s", stale_workers)
    update_response = supabase.table("jobs").update(
        {
            "status": "pending",
            "assigned_worker": None,
            "claimed_at": None,
        }
    ).in_("assigned_worker", stale_workers).eq("status", "running").execute()

    if update_response.error:
        logger.error("Failed to reset stale running jobs: %s", update_response.error)
        return

    logger.info("Reset %d running jobs to pending.", len(stale_workers))


def recover_failed_jobs():
    failed_cutoff = datetime.now(timezone.utc) - timedelta(minutes=FAILED_RECOVER_MIN)
    response = supabase.table("job_attempts").select("job_id,ended_at").eq("result", "failed").lt("ended_at", failed_cutoff.isoformat()).execute()
    if response.error:
        logger.error("Failed to query failed attempts: %s", response.error)
        return

    failed_job_ids = list({row["job_id"] for row in (response.data or [])})
    if not failed_job_ids:
        logger.info("No failed jobs ready for retry.")
        return

    logger.info("Requeueing failed jobs: %s", failed_job_ids)
    update_response = supabase.table("jobs").update(
        {
            "status": "pending",
            "assigned_worker": None,
            "claimed_at": None,
        }
    ).in_("id", failed_job_ids).execute()

    if update_response.error:
        logger.error("Failed to reset failed jobs: %s", update_response.error)
        return

    logger.info("Requeued %d failed jobs.", len(failed_job_ids))


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise EnvironmentError("SUPABASE_URL and SUPABASE_KEY must be set in the environment.")

    recover_stale_running_jobs()
    recover_failed_jobs()


if __name__ == "__main__":
    main()
