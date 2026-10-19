#!/bin/bash
#
# Google News Scraper - Batch Runner
#
# Purpose:
#   Automatically runs the Google News scraper for all active batches.
#   A batch is active if the current date falls within its start_date and end_date.
#
# Behavior:
#   - Reads batch configuration from batches.csv
#   - Finds all active batches for today
#   - Runs scraper separately for each active batch with batch-specific countries
#   - Sends email notification after each batch completes (success or failure)
#     if SCRAPER_EMAIL is set (comma-separated recipients)
#   - Handles overlapping batch periods automatically
#   - Exits silently if no batches are active
#
# Requirements:
#   - batches.csv must exist in the same directory
#   - uv and Python environment must be set up
#   - Scraper script (scrape_google_news.py) must be in the same directory
#
# Usage:
#   Typically run via crontab 3x daily (9am, 3pm, 9pm)
#   Can also be run manually: bash run_scraper.sh
#   Use --dry-run to show active batches without running scraper
#   Override CURRENT_DATE (YYYY-MM-DD) to test with a specific date:
#     CURRENT_DATE=2026-01-24 bash run_scraper.sh --dry-run
#
# Output:
#   - Scraped data: ../data_headlines/google_news_scraped/{batch_id}/
#   - Logs: ../logs/{date}_{batch_id}_scraping.log
#   - Email notifications with batch summary and status
#

# Parse arguments
DRY_RUN=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            shift
            ;;
    esac
done

# Get the directory where this script is located (code_headlines/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/batches.csv"
CURRENT_DATE=${CURRENT_DATE:-$(date +%Y-%m-%d)}
EMAIL="${SCRAPER_EMAIL:-}"

# Stay in code_headlines directory
cd "$SCRIPT_DIR" || exit 1

# Function to find all active batches for current date
find_active_batches() {
    local active_batches=()

    # Read CSV file, skip header and comments
    while IFS=',' read -r batch_id start_date end_date countries; do
        # Skip header, comments, and empty lines
        [[ "$batch_id" =~ ^#.*$ ]] || [[ "$batch_id" == "batch_id" ]] || [[ -z "$batch_id" ]] && continue

        # Check if current date is within this batch's range (inclusive).
        # YYYY-MM-DD dates sort correctly as strings, so no date parsing is needed.
        if [[ ! "$CURRENT_DATE" < "$start_date" ]] && [[ ! "$CURRENT_DATE" > "$end_date" ]]; then
            active_batches+=("$batch_id|$start_date|$end_date|$countries")
        fi
    done < "$CONFIG_FILE"

    # Return active batches (one per line)
    if [ ${#active_batches[@]} -eq 0 ]; then
        return 1
    fi

    printf '%s\n' "${active_batches[@]}"
    return 0
}

# Find all active batches
ACTIVE_BATCHES=$(find_active_batches)
if [ $? -ne 0 ]; then
    # Not in any collection period - silent exit (unless dry-run)
    if [ "$DRY_RUN" = true ]; then
        echo "No active batches found for $CURRENT_DATE"
    fi
    exit 0
fi

# Dry run: show active batches and exit
if [ "$DRY_RUN" = true ]; then
    echo "Active batches for $CURRENT_DATE:"
    echo "$ACTIVE_BATCHES" | while IFS='|' read -r batch_id start_date end_date countries; do
        echo "  - $batch_id ($start_date to $end_date): $countries"
    done
    exit 0
fi

# Process each active batch
# Feed the loop with a here-string (not a pipe) so it runs in this shell and
# OVERALL_EXIT_CODE set inside it survives to the final exit
OVERALL_EXIT_CODE=0
while IFS='|' read -r batch_id start_date end_date countries; do
    # Remove quotes from countries if present
    countries=$(echo "$countries" | sed 's/^"//; s/"$//')

    # Create a temporary file for this batch's output
    TEMP_OUTPUT=$(mktemp)

    {
        echo "==================================="
        echo "Google News Scraper Run"
        echo "Batch: $batch_id"
        echo "Collection Period: $start_date to $end_date"
        echo "Countries: $countries"
        echo "Run Date: $(date +%Y-%m-%d)"
        echo "Run Time: $(date +%H:%M:%S)"
        echo "==================================="
        echo ""

        # Run scraper for this batch (stdin from /dev/null so it can't consume the loop's input)
        uv run python scrape_google_news.py --batch-id "$batch_id" --countries "$countries" < /dev/null 2>&1
        SCRAPER_EXIT_CODE=$?

        echo ""
        echo "==================================="
        echo "Scraper completed at $(date +%H:%M:%S)"
        echo "Exit code: $SCRAPER_EXIT_CODE"
        echo "==================================="

        # Exit non-zero if the scraper failed
        [ $SCRAPER_EXIT_CODE -ne 0 ] && exit 1
        exit 0

    } | tee "$TEMP_OUTPUT"

    # Capture the exit code from the pipeline (use PIPESTATUS[0] to get the exit code of the command before tee)
    SCRAPER_EXIT_CODE=${PIPESTATUS[0]}

    # Email after this batch run (skipped if SCRAPER_EMAIL is unset)
    if [ $SCRAPER_EXIT_CODE -eq 0 ]; then
        SUBJECT="Scraper Success: $batch_id"
    else
        SUBJECT="ERROR: Scraper Failed: $batch_id"
        OVERALL_EXIT_CODE=1
    fi
    if [ -n "$EMAIL" ]; then
        mail -s "$SUBJECT" "$EMAIL" < "$TEMP_OUTPUT"
    fi

    rm "$TEMP_OUTPUT"

    # Small delay between batches to avoid rate limiting
    sleep 2
done <<< "$ACTIVE_BATCHES"

exit $OVERALL_EXIT_CODE