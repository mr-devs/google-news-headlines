# google-news-headlines

Collect Google News headlines for chosen countries on a schedule, then deduplicate them.

```
lib/news_scraper.py   collect_google_news(url): fetches the page and parses headlines with CSS selectors
scripts/              entry points, cron runner, batch config
data/                 region/language config and the generated URL list
data_headlines/       output (created on first run)
logs/                 run logs
```

Scripts `chdir` to `scripts/` themselves, so you can run them from anywhere.

## 1. Setup

```bash
uv sync
```

- Requires Python 3.12 and `uv`. Google News needs no API key.
- The cron runner (`run_scraper.sh`) needs GNU `date`. On macOS, `brew install coreutils` and put `gdate` on `PATH` as `date`.
- Email notifications need `mail` and `SCRAPER_EMAIL` to be set. Without them, no email is sent.

## 2. Choose countries

| File | Contents |
|---|---|
| `data/gnews_region_language_pairs.csv` | `region,language,region_code,language_code`. One row per country. |
| `data/gnews_region_topic_codes.json` | `{region: topic_code}`. Topic URLs are built for every region, but only "World" is scraped from its topic page. |
| `data/gnews_region_language_pairs_with_urls.csv` | Generated. This is the file the scraper reads. |

To add a country, add a row to the pairs CSV, then regenerate the URLs:

```bash
uv run python scripts/build_region_scraping_links.py
```

Each country is scraped from `https://news.google.com/home?hl={language_code}&gl={region_code}`.

## 3. One-off scrape

```bash
uv run python scripts/scrape_google_news.py --batch-id my_batch --countries "United States,Canada"
uv run python scripts/scrape_google_news.py --batch-id my_batch --countries "All"
```

- Country names must match the `region` column exactly ("United States", not "USA").
- "World" is always added.
- Requests are spaced 2–5 s apart.

## 4. Scheduled collection

1. Add a batch to `scripts/batches.csv`. The dates are inclusive, and batches may overlap.
   ```
   batch_id,start_date,end_date,countries
   batch_1,2026-11-02,2026-11-11,"United States,Canada"
   ```
2. Check which batches are active:
   ```bash
   bash scripts/run_scraper.sh --dry-run
   CURRENT_EPOCH=$(date -d "2026-11-05 09:00" +%s) bash scripts/run_scraper.sh --dry-run
   ```
3. Install cron from `scripts/crontab.txt` (`crontab -e`). Replace `/path/to/google-news-headlines` and fix `PATH` so it finds `uv`.
   - The scraper runs at 09:00, 15:00 and 21:00.
   - `git_backup.sh` runs 15 minutes after each scrape. It commits and pushes any changes, so it needs a git remote with push access.

## 5. Deduplicate

After the batch ends:

```bash
uv run python scripts/deduplicate_headlines.py --batch-id my_batch
```

This removes duplicate headlines within each country and randomly keeps up to 300 per country (`SAMPLING_SEED=42`).

## 6. Backfill a missed window (optional)

`scripts/emergency_scrape_google_news_topic.py` loads a Google News topic page in headless Chromium, scrolls to the bottom, and keeps articles dated within `[START_DATE, END_DATE]`.

1. Edit the constants at the top: `URL`, `START_DATE`, `END_DATE`, `COUNTRY`, `BATCH_ID`.
2. Install Chromium and run:
   ```bash
   uv run playwright install chromium
   uv run python scripts/emergency_scrape_google_news_topic.py
   ```

## 7. Output

| Step | Path |
|---|---|
| Scrape | `data_headlines/google_news_scraped/{batch_id}/{YYYY-MM-DD}_{Country_Name}_scraped_{NNN}.json` |
| Deduplicate | `data_headlines/deduplicated_headlines/{YYYY-MM-DD}_{batch_id}_deduplicated_headlines.csv` |
| Logs | `logs/{YYYY-MM-DD}_{batch_id}_scraping.log`, `..._deduplication.log` |

`NNN` counts up across the whole batch, not per day.

Scrape JSON:
```json
{"collection_time": "2026-08-31 09:00:25",
 "articles": [{"headline": "...", "link": "https://news.google.com/articles/...", "id": "<uuid4>"}],
 "country": "Malaysia",
 "batch_id": "batch_1"}
```
Backfill files also include `articles[].article_date`.

Deduplicated CSV columns: `uuid,date,country,headline,link`. `date` is the collection date, not the publication date.

## Gotchas

- `SKIP_BOSNIA = True` in `scrape_google_news.py` means Bosnia and Herzegovina is never scraped.
- `collect_google_news` sends no headers and doesn't retry. If Google changes its CSS class names (`gPFEn`, `JtKRv`, `iTin5e`, `WwrzSb`), it returns 0 headlines without raising an error. Check the logs.
- Home pages return few headlines (about 10–15 for the US). "World" returns about 200.
- Scrape errors that happen inside `run_scraper.sh` don't change its exit code, because the loop runs in a subshell. Read the email or the log instead.
