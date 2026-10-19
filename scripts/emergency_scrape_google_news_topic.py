"""
Purpose:
    Scrape Google News headlines from a specific topic/region page over a defined date
    range. Uses a headless browser that scrolls to the bottom of the page to ensure
    all content is loaded before extraction. This is a standalone one-off script for
    backfilling a date window; it is NOT integrated into the batch CSV / cron system
    used by scrape_google_news.py.

Notes:
    The target page is reverse-chronological and loads content progressively as the
    user scrolls. The script scrolls in viewport-height steps and stops once the page
    height stops growing (true bottom reached), then extracts all articles in one pass
    and filters to [START_DATE, END_DATE].

    Date inclusivity: START_DATE and END_DATE are Python `date` objects. Article dates
    are derived by calling `.date()` on a parsed UTC datetime, which strips the time
    component. Any article timestamped on START_DATE or END_DATE (regardless of hour)
    will satisfy START_DATE <= article_date <= END_DATE.

    Date extraction: Google News `<time class="hvbAAd">` elements carry a machine-
    readable `datetime` attribute (ISO 8601, e.g. "2026-04-08T19:50:44Z") alongside
    human-readable relative text ("21 hours ago"). We parse the attribute directly.

    The `<time>` element is not a direct sibling of the headline `<a>` — it sits 1-4
    DOM levels up in the parent container. A walk-up helper traverses ancestors until
    it locates the nearest `time.hvbAAd`.

    Output schema extends the existing batch_2 format with one extra per-article field,
    `article_date` (YYYY-MM-DD), which enables downstream date-based filtering. The
    three core fields — headline, link, id — are identical to other batch_2 files.

    Requires Playwright (one-time setup):
        uv add playwright
        playwright install chromium

Input:
    - URL constant (Google News topic page)
    - START_DATE and END_DATE constants (define collection window)

Output:
    - data_headlines/google_news_scraped/batch_2/{date}_United_Kingdom_scraped_{NNN}.json
      JSON object with fields:
        collection_time (str)  : ISO-like timestamp when the script ran
        articles (list)        : list of article objects, each containing:
            headline (str)       : headline text
            link (str)           : full Google News article URL
            id (str)             : UUID v4 unique identifier
            article_date (str)   : publication date as YYYY-MM-DD (not in other batch_2 files)
        country (str)          : "United Kingdom"
        batch_id (str)         : "batch_2"
    - logs/{date}_emergency_scraping.log

Author: Matthew DeVerna
"""

import json
import logging
import os
import random
import re
import sys
import uuid

from datetime import date, datetime
from pathlib import Path

from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print(
        "ERROR: Playwright is not installed.\n"
        "Install it with:\n"
        "  uv add playwright\n"
        "  playwright install chromium"
    )
    sys.exit(1)

# Change to script directory to enable relative paths
os.chdir(Path(__file__).resolve().parent)

# --- Constants ---
URL = "https://news.google.com/topics/CAAqJQgKIh9DQkFTRVFvSUwyMHZNRGR6YzJNU0JXVnVMVWRDS0FBUAE?hl=en-GB&gl=GB"
START_DATE = date(2026, 3, 30)  # inclusive — full day
END_DATE = date(2026, 4, 8)  # inclusive — full day
COUNTRY = "United Kingdom"
BATCH_ID = "batch_2"
OUTPUT_DIR = Path("../data_headlines/google_news_scraped") / BATCH_ID
LOG_DIR = Path("../logs")
SCROLL_PAUSE = 1.5  # seconds to wait after each viewport-height scroll step
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# CSS selectors confirmed against the target page
HEADLINE_SELECTORS = ["a.gPFEn", "a.JtKRv"]
DATE_SELECTOR = "time.hvbAAd"


def setup_logging():
    """
    Set up logging to both stdout and a date-stamped log file.

    Returns
    -------
    logging.Logger
        Configured logger instance.
    """
    LOG_DIR.mkdir(exist_ok=True)
    today = date.today().strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"{today}_emergency_scraping.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger(__name__)


def get_next_file_number(output_dir, country_filename):
    """
    Find the next available file number for a given country within the output directory.

    Parameters
    ----------
    output_dir : Path
        Directory to search for existing files.
    country_filename : str
        Country name as it appears in filenames (spaces already replaced with underscores).

    Returns
    -------
    int
        Next available file number (starting from 1).
    """
    pattern = f"*_{country_filename}_scraped_*.json"
    numbers = [
        int(m.group(1))
        for f in output_dir.glob(pattern)
        if (m := re.search(r"_scraped_(\d+)\.json$", f.name))
    ]
    return max(numbers) + 1 if numbers else 1


def parse_article_date(datetime_attr):
    """
    Parse an ISO 8601 datetime string from a Google News <time datetime="..."> attribute.

    Parameters
    ----------
    datetime_attr : str or None
        The value of the `datetime` HTML attribute (e.g. "2026-04-08T19:50:44Z").

    Returns
    -------
    datetime.date or None
        The date portion of the timestamp, or None if parsing fails.
    """
    if not datetime_attr:
        return None
    try:
        return datetime.fromisoformat(datetime_attr.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def find_date_for_element(el, max_levels=6):
    """
    Walk up the DOM ancestors of a headline element to find its publication date.

    Google News embeds the `<time class="hvbAAd">` element in a sibling or cousin
    container — not as a direct sibling of the headline anchor. This function walks
    up the parent chain and searches each subtree for the date element.

    Parameters
    ----------
    el : bs4.element.Tag
        A BeautifulSoup element (typically an `<a>` headline anchor).
    max_levels : int, optional
        Maximum number of ancestor levels to climb. Default is 6.

    Returns
    -------
    datetime.date or None
        Parsed publication date, or None if not found within max_levels.
    """
    node = el.parent
    for _ in range(max_levels):
        if node is None or node.name in ("[document]", "html", "body"):
            break
        time_el = node.select_one(DATE_SELECTOR)
        if time_el:
            return parse_article_date(time_el.get("datetime"))
        node = node.parent
    return None


def extract_articles_from_html(html):
    """
    Parse a Google News page HTML snapshot and extract all articles with their dates.

    Iterates over all known headline selectors and, for each anchor element, resolves
    the associated publication date via DOM walk-up. Articles without a parseable date
    are skipped. Duplicate links within a single parse are deduplicated.

    Parameters
    ----------
    html : str
        Full HTML content of the current page state.

    Returns
    -------
    list of dict
        Each dict has keys: headline (str), link (str), article_date (datetime.date).
    """
    soup = BeautifulSoup(html, "html.parser")
    articles = []
    seen_links = set()

    for selector in HEADLINE_SELECTORS:
        for el in soup.select(selector):
            headline = el.text.strip()
            if not headline:
                continue

            link = el.get("href", "")
            if "./read/" in link:
                link = link.replace("./read/", "https://news.google.com/articles/")
            elif not link.startswith("http"):
                continue

            if link in seen_links:
                continue
            seen_links.add(link)

            article_date = find_date_for_element(el)
            if article_date is None:
                continue

            articles.append(
                {
                    "headline": headline,
                    "link": link,
                    "article_date": article_date,
                }
            )

    return articles


def scroll_to_bottom(page, logger):
    """
    Scroll to the bottom of the page in viewport-height steps, waiting after each
    step for any newly loaded content to render.

    Stops when the page height stops growing and the scroll position has reached
    the bottom, indicating all content has been loaded.

    Parameters
    ----------
    page : playwright.sync_api.Page
        An active Playwright page already navigated to the target URL.
    logger : logging.Logger
        Logger instance for progress messages.
    """
    logger.info("Scrolling to bottom of page to ensure all content is loaded...")

    # Viewport height is static for the duration of the scroll; evaluate once
    viewport_height = page.evaluate("window.innerHeight")

    while True:
        prev_height = page.evaluate("document.body.scrollHeight")

        page.mouse.wheel(0, viewport_height + random.randint(-100, 100))
        page.wait_for_timeout(int(SCROLL_PAUSE * 1000))

        new_height = page.evaluate("document.body.scrollHeight")
        scroll_y = page.evaluate("window.scrollY")

        # Stop when height stopped growing and scroll position is at/near the bottom
        if new_height == prev_height and scroll_y + viewport_height >= new_height - 50:
            break

    logger.info("Reached bottom of page.")


def main():
    """
    Main execution function.

    Orchestrates the scraping workflow:
    1. Launch a Playwright browser
    2. Navigate to the Google News topic page
    3. Scroll to the bottom to ensure all content is loaded
    4. Extract all articles from the fully-loaded page
    5. Filter to [START_DATE, END_DATE] window
    6. Add UUIDs and save as JSON matching the batch_2 schema
    """
    logger = setup_logging()
    logger.info(
        f"Starting date-range scrape for {COUNTRY} | "
        f"{START_DATE} to {END_DATE} | batch: {BATCH_ID}"
    )
    logger.info(f"Target URL: {URL}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        logger.info("Navigating to URL...")
        page.goto(URL, wait_until="networkidle", timeout=60_000)

        # Check for CAPTCHA or unexpected page
        title = page.title()
        logger.info(f"Page title: {title}")
        if "captcha" in title.lower() or "sorry" in title.lower():
            logger.error(
                "Google returned a CAPTCHA or error page. "
                "Resolve the CAPTCHA in the browser window, then re-run."
            )
            browser.close()
            sys.exit(1)

        scroll_to_bottom(page, logger)
        all_articles = extract_articles_from_html(page.content())
        logger.info(f"Extracted {len(all_articles)} articles from fully-loaded page.")
        browser.close()

    if not all_articles:
        logger.error(
            "No articles collected. Possible CSS selector mismatch or empty page. "
            f"Verified selectors on 2026-04-09: {HEADLINE_SELECTORS}. "
            "Re-inspect the page if Google has updated its layout."
        )
        sys.exit(1)

    # Filter to target date window
    articles_in_window = [
        a for a in all_articles if START_DATE <= a["article_date"] <= END_DATE
    ]

    logger.info(
        f"Total articles collected: {len(all_articles)}. "
        f"In [{START_DATE}, {END_DATE}]: {len(articles_in_window)}"
    )

    if not articles_in_window:
        logger.error(
            f"No articles found within the date window {START_DATE} to {END_DATE}. "
            "Check that the page contains content for this period."
        )
        sys.exit(1)

    # Assign UUIDs and convert article_date to string for JSON serialization
    for article in articles_in_window:
        article["id"] = str(uuid.uuid4())
        article["article_date"] = str(article["article_date"])

    # Build output object matching batch_2 schema
    output = {
        "collection_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "articles": articles_in_window,
        "country": COUNTRY,
        "batch_id": BATCH_ID,
    }

    # Save to file
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    country_filename = COUNTRY.replace(" ", "_")
    file_number = get_next_file_number(OUTPUT_DIR, country_filename)
    today = date.today().strftime("%Y-%m-%d")
    filename = f"{today}_{country_filename}_scraped_{file_number:03d}.json"
    output_file = OUTPUT_DIR / filename

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved {len(articles_in_window)} articles to {output_file}")


if __name__ == "__main__":
    main()
