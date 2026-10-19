# google-news-headlines

Collect Google News headlines for chosen countries on a schedule, then deduplicate them.

```
lib/news_scraper.py   collect_google_news(url): fetches the page and parses headlines with CSS selectors
scripts/              entry points, cron runner, batch config
data/                 countries.csv: the countries you can scrape and their URLs
data_headlines/       output (created on first run)
logs/                 run logs
```

Scripts `chdir` to `scripts/` themselves, so you can run them from anywhere.

## 1. Setup

```bash
uv sync
```

- Requires Python 3.12 and `uv`. Google News needs no API key.
- Email notifications need `mail` and `SCRAPER_EMAIL` to be set. Without them, no email is sent.

## 2. Choose countries

`data/countries.csv` lists every country the scraper knows about, one per line:

```
country,url
United States,https://news.google.com/home?hl=en&gl=us
```

To add a country, add a line. The URL is the country's Google News home page, `https://news.google.com/home?hl={language_code}&gl={region_code}`.

## 3. One-off scrape

```bash
uv run python scripts/scrape_google_news.py --batch-id my_batch --countries "United States,Canada"
uv run python scripts/scrape_google_news.py --batch-id my_batch --countries "All"
```

- Country names must match the `country` column exactly as it is in the `data/countries.csv` ("United States", not "USA").
- Include multiple countries with commas separating them ("United States") scrapes headlines only from the United States, ("United States,Canada") scrapes headlines from both the United States and Canada, and ("United States,Canada,Italy") will also include headlines from the Italy page.
- The "World" region is a different type of page. See the `data/countries.csv` file for the difference in the URLs. Visit different links to compare and see the difference. "World" is a "topic" page.
- Including "All" will scrape headlines from all countries in `data/countries.csv`.
- If any name doesn't match, the scraper logs an error and exits before scraping anything.
- Requests are spaced 2–5 s apart.

## 4. Scheduled collection

Scheduled collection uses cron, so it works on Linux and macOS. Cron calls `scripts/run_scraper.sh`, which reads `scripts/batches.csv` and runs `scrape_google_news.py` once for every batch that is active today. On days with no active batch it does nothing, so you can leave cron installed between batches.

### Define batches

Add a line to `scripts/batches.csv` for each collection period:

```
batch_id,start_date,end_date,countries
batch_1,2026-11-02,2026-11-11,"United States,Canada"
```

- Dates must be `YYYY-MM-DD`. Both ends are inclusive.
- `countries` uses the same rules as `--countries` in a one-off scrape (see section 3). Quote it if it contains commas.
- Batches may overlap. Each active batch runs separately and writes to its own folder.

### Check the setup before installing cron

```bash
bash scripts/run_scraper.sh --dry-run                           # batches active today
CURRENT_DATE=2026-11-05 bash scripts/run_scraper.sh --dry-run   # batches active on another date
```

`--dry-run` only lists batches. It doesn't check country names, so run a one-off scrape with each batch's `countries` to catch typos. Under cron, a bad name makes that batch fail on every run.

### Install the cron jobs

1. Copy the jobs from `scripts/crontab.txt` and edit them:
   - Replace every `/path/to/google-news-headlines` with the absolute path to this repository.
   - Set `PATH` so it includes the directory that holds `uv` (`dirname "$(which uv)"`). Cron starts with a minimal `PATH` and doesn't expand `~`.
   - Optionally uncomment `SCRAPER_EMAIL` to get an email after each batch run.
2. Run `crontab -e` and paste the edited lines. Avoid `crontab scripts/crontab.txt`: it replaces your whole crontab.
3. Run `crontab -l` to confirm the jobs are installed.

The jobs:

| Time (machine's local time zone) | Job | Log |
|---|---|---|
| 09:00, 15:00, 21:00 | `run_scraper.sh` | `logs/scraper_cron.log` |
| 09:15, 15:15, 21:15 | `git_backup.sh` | `logs/git_backup_cron.log` |

`git_backup.sh` commits and pushes everything that changed in the repository, not just new data. It needs a git remote with push access that works without a prompt (an SSH key or a credential helper). Leave out the backup job if you don't want automatic commits.

### Check that it ran

After the first scheduled time, look at `logs/scraper_cron.log` and the batch log `logs/{YYYY-MM-DD}_{batch_id}_scraping.log`, and check for new files in `data_headlines/google_news_scraped/{batch_id}/`.

### macOS notes

- The Mac must be awake at the scheduled times. Cron skips runs missed during sleep and doesn't make them up.
- If the repository is in `~/Documents`, `~/Desktop` or `~/Downloads`, give cron Full Disk Access (System Settings → Privacy & Security → Full Disk Access → add `/usr/sbin/cron`). Without it, the jobs fail with "Operation not permitted".
- Email needs a working `mail` setup, which macOS doesn't have by default.

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

- `collect_google_news` sends no headers and doesn't retry. If Google changes its CSS class names (`gPFEn`, `JtKRv`, `iTin5e`, `WwrzSb`), it returns 0 headlines without raising an error. Check the logs.
- Home pages return few headlines (about 10–15 for the US). "World" returns about 200.
- Scrape errors that happen inside `run_scraper.sh` don't change its exit code, because the loop runs in a subshell. Read the email or the log instead.
