import hashlib
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from threading import Event, Thread

from dotenv import load_dotenv
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
WORKER_ID = os.getenv("WORKER_ID") or f"worker-{uuid.uuid4().hex[:8]}"
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "60"))
MAX_RESULTS_PER_TILE = int(os.getenv("MAX_RESULTS_PER_TILE", "100"))
MAX_SCROLL_STEPS = int(os.getenv("MAX_SCROLL_STEPS", "40"))
SCROLL_WAIT_MS = int(os.getenv("SCROLL_WAIT_MS", "3500"))
SCROLL_STABLE_RETRIES = int(os.getenv("SCROLL_STABLE_RETRIES", "2"))
HEADLESS = os.getenv("HEADLESS", "false").lower() in ("1", "true", "yes")
JOB_CLAIM_RPC_NAME = os.getenv("JOB_CLAIM_RPC_NAME", "claim_pending_job")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("lead-scraper")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_message(level: str, message: str) -> None:
    try:
        supabase.table("logs").insert(
            {
                "level": level,
                "source": WORKER_ID,
                "message": message,
            }
        ).execute()
    except Exception as exc:
        logger.warning("Unable to write log to Supabase: %s", exc)


def upsert_worker(current_job=None, status="active") -> None:
    try:
        payload = {
            "worker_id": WORKER_ID,
            "status": status,
            "current_job": current_job,
            "last_heartbeat": timestamp_utc(),
        }
        supabase.table("workers").upsert(payload).execute()
    except Exception as exc:
        logger.warning("Worker registration failed: %s", exc)


def send_heartbeat(current_job=None) -> None:
    try:
        payload = {
            "last_heartbeat": timestamp_utc(),
            "current_job": current_job,
        }
        supabase.table("workers").update(payload).eq("worker_id", WORKER_ID).execute()
    except Exception as exc:
        logger.warning("Heartbeat update failed: %s", exc)


def claim_job():
    try:
        response = supabase.rpc(JOB_CLAIM_RPC_NAME, {"worker_id_param": WORKER_ID}).execute()
        if hasattr(response, "error") and response.error:
            logger.error("Job claim RPC error: %s", response.error)
            return None
        data = getattr(response, "data", None)
        if not data:
            return None
        return data[0] if isinstance(data, list) else data
    except Exception as exc:
        logger.error("Claim job failed: %s", exc)
        return None


def mark_job_status(job_id, status, completed=False) -> None:
    payload = {"status": status}
    if completed:
        payload["completed_at"] = timestamp_utc()
    try:
        supabase.table("jobs").update(payload).eq("id", job_id).execute()
    except Exception as exc:
        logger.error("Failed to update job %s status to %s: %s", job_id, status, exc)


def record_job_attempt(job_id, worker_id):
    try:
        response = supabase.table("job_attempts").insert(
            {
                "job_id": job_id,
                "worker_id": worker_id,
                "started_at": timestamp_utc(),
                "result": "running",
            }
        ).execute()
        data = getattr(response, "data", None)
        if not data:
            logger.warning("Failed to create job attempt: no data returned")
            return None
        return data[0].get("id") if isinstance(data, list) else data.get("id")
    except Exception as exc:
        logger.warning("Failed to create job attempt: %s", exc)
        return None


def update_job_attempt(attempt_id, result, error_message=None):
    if not attempt_id:
        return
    payload = {
        "ended_at": timestamp_utc(),
        "result": result,
        "error_message": error_message,
    }
    try:
        supabase.table("job_attempts").update(payload).eq("id", attempt_id).execute()
    except Exception as exc:
        logger.warning("Failed to update job attempt %s: %s", attempt_id, exc)


def parse_place_id(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(r"!1s([^!]+)", url)
    if match:
        return match.group(1)
    match = re.search(r"/place/([^/]+)", url)
    return match.group(1) if match else None


def make_fingerprint(name: str | None, url: str | None, address: str | None) -> str:
    text = f"{name or ''}|{url or ''}|{address or ''}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def safe_text(locator):
    try:
        return locator.inner_text(timeout=1000).strip()
    except (PlaywrightTimeoutError, PlaywrightError):
        return None
    except Exception:
        return None


def accept_consent(page) -> None:
    selectors = [
        'button:has-text("I agree")',
        'button:has-text("Accept all")',
        'button:has-text("Agree")',
        'button:has-text("Accept")',
        'button:has-text("Got it")',
    ]
    for selector in selectors:
        try:
            button = page.locator(selector)
            if button.count() and button.first.is_visible():
                button.first.click()
                page.wait_for_timeout(1500)
                return
        except Exception:
            continue


def scroll_search_results(page) -> bool:
    try:
        return page.evaluate(
            """
            () => {
                const feed = document.querySelector('div[role="feed"]') || document.querySelector('div[role="list"]') || document.querySelector('div[role="main"]');
                if (!feed) {
                    return false;
                }
                const cards = feed.querySelectorAll('div[role="article"]');
                const target = cards.length ? cards[cards.length - 1] : feed;
                try {
                    target.scrollIntoView({ behavior: 'smooth', block: 'end' });
                } catch (err) {
                    feed.scrollTop = feed.scrollHeight;
                }
                window.scrollBy(0, window.innerHeight);
                return true;
            }
            """
        )
    except Exception:
        return False


def wait_for_search_results(page, timeout_ms=45000) -> bool:
    start_time = time.time()
    result_locators = [
        'div[role="article"]',
        'a[href*="/place/"]',
        'div[aria-label*="Results"]',
    ]
    while time.time() - start_time < timeout_ms / 1000:
        for selector in result_locators:
            try:
                locator = page.locator(selector)
                if locator.count() > 0:
                    logger.info("Search results detected with selector: %s (%d items)", selector, locator.count())
                    return True
            except Exception:
                continue
        time.sleep(1.5)
    return False


def normalize_business_text(raw_text: str) -> str:
    cleaned = raw_text.replace("Sponsored", "").replace("Sponsored\ue5d4", "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def parse_website_from_text(raw_text: str) -> str | None:
    matches = re.findall(r"\b(?:https?://)?(?:www\.)?[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:/[^\s]*)?\b", raw_text)
    for candidate in matches:
        normalized = candidate.strip()
        if re.search(r"google\.com|gstatic\.com|maps\.google\.com|youtube\.com|googleusercontent\.com|doubleclick\.net", normalized, re.IGNORECASE):
            continue
        if not normalized.startswith("http"):
            normalized = "https://" + normalized
        return normalized
    return None


def parse_email_from_text(raw_text: str) -> str | None:
    match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", raw_text)
    return match.group(0) if match else None


def parse_review_count(raw_text: str) -> int | None:
    match = re.search(r"\b([0-9]{1,3}(?:,[0-9]{3})?)\s*reviews?\b", raw_text, re.IGNORECASE)
    if match:
        return int(match.group(1).replace(",", ""))
    match = re.search(r"\b([0-9]{1,3})\)\b", raw_text)
    if match:
        return int(match.group(1))
    return None


def parse_rating_from_text(raw_text: str) -> float | None:
    match = re.search(r"([0-9](?:\.[0-9])?)\s*stars", raw_text, re.IGNORECASE)
    if match:
        return float(match.group(1))
    match = re.search(r"\b([0-9](?:\.[0-9])?)\b", raw_text)
    if match:
        return float(match.group(1))
    return None


def parse_phone_from_text(raw_text: str) -> str | None:
    match = re.search(r"(\+?\d[\d\s\-\(\)]{7,}\d)", raw_text)
    return match.group(1).strip() if match else None


def extract_detail_data(context, maps_url: str) -> dict:
    detail = {}
    try:
        if maps_url.startswith("/"):
            maps_url = f"https://www.google.com{maps_url}"
        detail_page = context.new_page()
        detail_page.goto(maps_url, timeout=90000)
        detail_page.wait_for_timeout(5000)

        raw_text = ""
        try:
            raw_text = detail_page.locator('div[role="main"]').first.inner_text(timeout=10000)
        except Exception:
            raw_text = detail_page.content()

        normalized_text = normalize_business_text(raw_text)
        detail["website"] = parse_website_from_text(normalized_text)
        detail["email"] = parse_email_from_text(normalized_text)
        detail["review_count"] = parse_review_count(normalized_text)

        try:
            rating_element = detail_page.locator('span.MW4etd').first
            if rating_element.count() > 0:
                rating_text = rating_element.inner_text().strip()
                detail["rating"] = float(rating_text)
            else:
                detail["rating"] = parse_rating_from_text(normalized_text)
        except Exception:
            detail["rating"] = parse_rating_from_text(normalized_text)

        detail["phone"] = parse_phone_from_text(normalized_text)
        detail_page.close()
    except Exception as exc:
        logger.debug("Failed to extract detail data for %s: %s", maps_url, exc)
        try:
            detail_page.close()
        except Exception:
            pass
    return detail


def extract_businesses_from_page(page, context):
    businesses = {}
    cards = page.locator('div[role="article"]')
    count = min(cards.count(), MAX_RESULTS_PER_TILE)
    for index in range(count):
        card = cards.nth(index)
        link = card.locator('a[href*="/place/"]').first
        href = link.get_attribute("href")
        if not href:
            continue
        maps_url = href.split("&")[0]
        name = card.get_attribute("aria-label") or safe_text(card.locator('div.qBF1Pd').first) or safe_text(link)
        raw_text = normalize_business_text(safe_text(card) or "")
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

        address = None
        category = None
        rating = None
        review_count = None
        phone = None

        if lines and name:
            normalized_name = name.strip()
            if lines[0] == normalized_name or normalized_name in lines[0]:
                lines = lines[1:]

        if lines:
            filtered = [line for line in lines if not re.search(r"Website|Directions|Open|Closed|Closes|hours?", line, re.IGNORECASE)]
            if filtered:
                lines = filtered

        if lines:
            category = lines[0]
            if len(lines) > 1:
                address_candidate = lines[-1]
                phone_candidate = parse_phone_from_text(address_candidate)
                if phone_candidate and phone_candidate in address_candidate:
                    address_candidate = lines[-2]
                address = address_candidate

        rating_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*[★☆]", raw_text)
        if rating_match:
            try:
                rating = float(rating_match.group(1))
            except ValueError:
                rating = None

        if review_count is None:
            reviews_match = re.search(r"([0-9,]+)\s*reviews?", raw_text, re.IGNORECASE)
            if reviews_match:
                review_count = int(reviews_match.group(1).replace(",", ""))

        if phone is None:
            phone = parse_phone_from_text(raw_text)

        place_id = parse_place_id(maps_url)
        if not place_id:
            place_id = make_fingerprint(name, maps_url, address)

        detail_data = extract_detail_data(context, maps_url)

        business = {
            "place_id": place_id,
            "business_name": name,
            "category": detail_data.get("category") or category,
            "address": detail_data.get("address") or address,
            "website": detail_data.get("website"),
            "phone": detail_data.get("phone") or phone,
            "rating": detail_data.get("rating") or rating,
            "review_count": detail_data.get("review_count") or review_count,
            "maps_url": maps_url,
            "email": detail_data.get("email"),
        }

        businesses[place_id] = business
    return list(businesses.values())


def scrape_tile(job) -> int:
    search_query = f"{job['keyword']} {job['tile']}, {job['city']}, {job['country']}"
    logger.info("Starting scrape for job %s: %s", job["id"], search_query)
    with sync_playwright() as playwright:
        # Allow extra Chromium launch args from environment for Colab/containers
        chromium_args = os.getenv("CHROMIUM_ARGS", "--no-sandbox")
        chromium_args_list = [arg for arg in chromium_args.split() if arg]
        browser = playwright.chromium.launch(headless=HEADLESS, args=chromium_args_list)
        context = browser.new_context(
            locale="en-US",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        page.goto("https://www.google.com/maps", timeout=90000)
        page.wait_for_timeout(8000)
        
        # Log what we see
        title = page.title()
        logger.info("Page title: %s", title)
        
        accept_consent(page)

        # Try to find search input with multiple selectors
        search_input = None
        selectors_to_try = [
            'input[aria-label="Search Google Maps"]',
            'input[placeholder*="Search"]',
            'input[type="text"]',
            'div[role="search"] input',
        ]
        
        for selector in selectors_to_try:
            try:
                element = page.locator(selector)
                if element.count() > 0:
                    logger.info("Found search input with selector: %s", selector)
                    search_input = element.first
                    break
            except Exception as e:
                logger.debug("Selector %s failed: %s", selector, e)
        
        if not search_input:
            logger.error("Could not find search input with any selector")
            logger.info("Page HTML snippet: %s", page.content()[:2000])
            raise Exception("Search input not found on page")
        
        # Try to interact with the search input
        try:
            search_input.wait_for(state="visible", timeout=10000)
        except PlaywrightTimeoutError:
            logger.warning("Search input not visible, trying to click anyway")

        try:
            search_input.click()
        except Exception:
            pass

        search_input.fill(search_query)
        logger.info("Filled search query: %s", search_query)
        page.wait_for_timeout(500)
        search_input.press("Enter")
        
        # Wait for search result indicators rather than networkidle
        if not wait_for_search_results(page, timeout_ms=45000):
            logger.error("Search results never appeared for query: %s", search_query)
            logger.info("Current page URL: %s", page.url)
            logger.info("Page HTML snippet: %s", page.content()[:3000])
            raise Exception("Search results did not load")

        page.wait_for_timeout(3000)

        last_count = -1
        stable_retries = 0
        for step in range(MAX_SCROLL_STEPS):
            cards = page.locator('div[role="article"]')
            count = cards.count()
            logger.info("Scroll step %d: current article count %d", step + 1, count)
            if count >= MAX_RESULTS_PER_TILE:
                logger.info("Reached MAX_RESULTS_PER_TILE (%d), stopping scroll", MAX_RESULTS_PER_TILE)
                break
            if not scroll_search_results(page):
                logger.info("Search results panel not scrollable or missing, stopping scroll attempts")
                break
            page.wait_for_timeout(SCROLL_WAIT_MS)
            new_count = page.locator('div[role="article"]').count()
            logger.info("Scroll step %d: updated article count %d", step + 1, new_count)
            if new_count > count:
                stable_retries = 0
                last_count = new_count
                continue
            page.wait_for_timeout(1500)
            new_count = page.locator('div[role="article"]').count()
            logger.info("Scroll step %d: retry article count %d", step + 1, new_count)
            if new_count > count:
                stable_retries = 0
                last_count = new_count
                continue
            stable_retries += 1
            if stable_retries >= SCROLL_STABLE_RETRIES:
                logger.info("No new results after %d stable retries, stopping", stable_retries)
                break
            logger.info("Retrying scroll because results count did not increase")

        businesses = extract_businesses_from_page(page, context)
        logger.info("Scraped %d businesses from job %s", len(businesses), job["id"]) 

        for business in businesses:
            try:
                supabase.table("businesses").upsert(business, on_conflict="place_id").execute()
            except Exception as exc:
                logger.warning("Business insert failed for %s: %s", business.get("place_id"), exc)

        browser.close()
    return len(businesses)


class HeartbeatThread(Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._stop_event = Event()
        self.current_job = None

    def run(self):
        while not self._stop_event.is_set():
            send_heartbeat(self.current_job)
            self._stop_event.wait(HEARTBEAT_INTERVAL)

    def stop(self):
        self._stop_event.set()


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise EnvironmentError("SUPABASE_URL and SUPABASE_KEY must be set in the environment.")

    upsert_worker()
    send_heartbeat(None)
    heartbeat = HeartbeatThread()
    heartbeat.start()

    try:
        while True:
            job = claim_job()
            if not job:
                logger.info("No pending jobs available. Sleeping for 30 seconds.")
                time.sleep(30)
                continue

            heartbeat.current_job = job["id"]
            attempt_id = record_job_attempt(job["id"], WORKER_ID)
            send_heartbeat(job["id"])

            try:
                scraped_count = scrape_tile(job)
                mark_job_status(job["id"], "completed", completed=True)
                update_job_attempt(attempt_id, "success")
                log_message("INFO", f"Completed job {job['id']} and inserted {scraped_count} businesses.")
            except Exception as exc:
                logger.exception("Job %s failed: %s", job["id"], exc)
                mark_job_status(job["id"], "failed")
                update_job_attempt(attempt_id, "failed", str(exc))
                log_message("ERROR", f"Job {job['id']} failed: {exc}")
            finally:
                heartbeat.current_job = None
                send_heartbeat(None)
                time.sleep(HEARTBEAT_INTERVAL)
    except KeyboardInterrupt:
        logger.info("Worker stopping by keyboard interrupt.")
    finally:
        heartbeat.stop()
        send_heartbeat(None)
        log_message("INFO", "Worker shut down.")


if __name__ == "__main__":
    main()
