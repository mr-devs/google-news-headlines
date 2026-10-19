"""
Purpose
    Scrape Google News headlines and save with unique identifiers.

Input
    CSV file with one Google News URL per country (../data/countries.csv)

Output
    JSON files with headlines and unique IDs (../data_headlines/)

Author
    Matthew DeVerna
"""

import sys
import os
import json
import logging
import time
import uuid
import re
import random
import argparse

from pathlib import Path
from datetime import date

import pandas as pd

# Change working directory to script location
os.chdir(Path(__file__).resolve().parent)

# Import from installed package
from news_scraper import collect_google_news

# Constants
DATA_DIR = Path("../data")
OUTPUT_DIR = Path("../data_headlines")
COUNTRIES_FILE = DATA_DIR / "countries.csv"
LOG_DIR = Path("../logs")
WAIT_BETWEEN_REQUESTS = 2  # base seconds (random 0-3s added for total 2-5s)


def get_next_file_number(output_dir, country, file_type="scraped"):
    """
    Find the next available file number for a given country within a batch.

    Parameters
    ----------
    output_dir : Path
        Directory to search for existing files (batch-specific directory).
    country : str
        Country name.
    file_type : str
        Type of file ("scraped" or "placebos").

    Returns
    -------
    int
        Next available file number (starting from 1).
    """
    # Replace spaces with underscores for filename pattern matching
    country_filename = country.replace(" ", "_")
    # Pattern to match existing files: YYYY-MM-DD_Country_scraped_NNN.json
    pattern = f"*_{country_filename}_{file_type}_*.json"
    existing_files = list(output_dir.glob(pattern))

    if not existing_files:
        return 1

    # Extract numbers from filenames
    numbers = []
    for file in existing_files:
        # Match pattern: {date}_{country}_{type}_{number}.json
        match = re.search(rf"_{file_type}_(\d+)\.json$", file.name)
        if match:
            numbers.append(int(match.group(1)))

    if not numbers:
        return 1

    return max(numbers) + 1


def validate_articles(articles, country):
    """
    Validate articles list and individual article fields.

    Parameters
    ----------
    articles : list
        List of article dictionaries.
    country : str
        Country name for logging.

    Returns
    -------
    tuple
        (is_valid: bool, valid_articles: list, messages: list)
        - is_valid: True if at least one valid article exists
        - valid_articles: List of articles with all required fields
        - messages: List of warning messages
    """
    messages = []

    # Check for empty articles list
    if len(articles) == 0:
        messages.append(
            f"No articles found for {country}. Possible CSS selector mismatch or empty page."
        )
        return False, [], messages

    # Validate individual article fields
    required_fields = ["headline", "link"]
    valid_articles = []
    skipped_count = 0

    for idx, article in enumerate(articles):
        missing_fields = [field for field in required_fields if field not in article]

        if missing_fields:
            messages.append(
                f"Article {idx} in {country} missing required fields: {missing_fields}"
            )
            skipped_count += 1
        else:
            valid_articles.append(article)

    # Check if all articles were invalid
    if len(valid_articles) == 0:
        return False, [], messages

    # Log summary if some articles were skipped
    if skipped_count > 0:
        messages.append(
            f"Skipped {skipped_count} articles for {country} due to missing fields"
        )

    return True, valid_articles, messages


def setup_logging(batch_id):
    """
    Set up logging to both stdout and a batch-specific log file.

    Parameters
    ----------
    batch_id : str
        Batch identifier for log file naming.

    Returns
    -------
    logging.Logger
        Configured logger instance.
    """
    # Create logs directory if it doesn't exist
    LOG_DIR.mkdir(exist_ok=True)

    # Create batch and date-named log file
    today = date.today().strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"{today}_{batch_id}_scraping.log"

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
    )

    return logging.getLogger(__name__)


def process_country(row, batch_id, batch_dir, logger):
    """
    Process news scraping for a single country.

    Parameters
    ----------
    row : pandas.Series
        Row from the countries dataframe (country, url).
    batch_id : str
        Batch identifier for organizing outputs.
    batch_dir : Path
        Directory for this batch's data.
    logger : logging.Logger
        Logger instance.

    Returns
    -------
    bool
        True if processing succeeded, False otherwise.
    """
    country = row["country"]
    url = row["url"]

    logger.info(f"Processing {country}...")

    try:
        # Scrape Google News
        output = collect_google_news(url)
        output["country"] = country
        output["batch_id"] = batch_id

        logger.info(f"Collected {len(output['articles'])} headlines for {country}")

        # Validate articles
        is_valid, valid_articles, messages = validate_articles(
            output["articles"], country
        )

        # Log validation results
        for msg in messages:
            logger.warning(msg)

        if not is_valid:
            logger.warning(f"No valid articles for {country}. Skipping save.")
            return False

        # Update output with only valid articles
        output["articles"] = valid_articles

        # Add unique ID to each article
        for article in output["articles"]:
            article["id"] = str(uuid.uuid4())

        # Save in batch-specific directory
        batch_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with auto-incrementing number
        file_number = get_next_file_number(batch_dir, country, "scraped")
        today = date.today().strftime("%Y-%m-%d")
        # Replace spaces with underscores in country name for filename
        country_filename = country.replace(" ", "_")
        filename = f"{today}_{country_filename}_scraped_{file_number:03d}.json"

        # Save output
        output_file = batch_dir / filename
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        logger.info(f"Successfully saved {filename} in {batch_dir}")

        # Wait with random variation (2-5 seconds)
        random_addition = random.uniform(0, 3)
        wait_time = WAIT_BETWEEN_REQUESTS + random_addition
        logger.info(f"Waiting {wait_time:.1f} seconds before next request...")
        time.sleep(wait_time)
        return True

    except Exception as e:
        logger.error(f"Error processing {country}: {str(e)}")
        return False


def parse_arguments():
    """
    Parse command-line arguments.

    Returns
    -------
    argparse.Namespace
        Parsed arguments containing batch_id and countries.
    """
    parser = argparse.ArgumentParser(
        description="Scrape Google News headlines for a specific batch and countries."
    )
    parser.add_argument(
        "--batch-id",
        required=True,
        help="Batch identifier (e.g., 'batch_1')",
    )
    parser.add_argument(
        "--countries",
        required=True,
        help='Comma-separated list of countries (e.g., "United States,Australia") or "All" for every country in countries.csv',
    )
    return parser.parse_args()


def main():
    """
    Main function to orchestrate the news scraping process.
    """
    # Parse command-line arguments
    args = parse_arguments()
    batch_id = args.batch_id
    countries_input = args.countries.strip()

    logger = setup_logging(batch_id)
    logger.info(f"Starting Google News scraping for {batch_id}")

    try:
        # Load countries and their URLs
        if not COUNTRIES_FILE.exists():
            raise FileNotFoundError(f"Countries file not found: {COUNTRIES_FILE}")

        urls_df = pd.read_csv(COUNTRIES_FILE)

        # Handle "All" to include every country
        if countries_input.upper() == "ALL":
            logger.info("Target countries: All")
            # Use all countries from the CSV - no filtering needed
        else:
            # Parse specific countries list
            countries_list = [c.strip() for c in countries_input.split(",")]

            logger.info(f"Target countries: {', '.join(countries_list)}")

            # Fail on names that don't match a country in the CSV
            unknown = sorted(set(countries_list) - set(urls_df["country"]))
            if unknown:
                logger.error(
                    f"Unknown countries: {', '.join(unknown)}. "
                    f"Names must match the 'country' column in {COUNTRIES_FILE}"
                )
                sys.exit(1)

            # Filter to only include specified countries
            urls_df = urls_df[urls_df["country"].isin(countries_list)]

        urls_df.sort_values(by="country", inplace=True)
        logger.info(f"Filtered to {len(urls_df)} countries for this batch")

        if len(urls_df) == 0:
            logger.error("No countries to scrape")
            sys.exit(1)

        # Create batch-specific output directory
        batch_dir = OUTPUT_DIR / "google_news_scraped" / batch_id

        # Process each country: extract headlines
        success_count = 0
        for _, row in urls_df.iterrows():
            if process_country(row, batch_id, batch_dir, logger):
                success_count += 1

        logger.info(
            "Processing complete. "
            f"{success_count}/{len(urls_df)} countries processed successfully."
        )

        # Check for total failure
        if success_count == 0:
            logger.error(
                f"All {len(urls_df)} countries failed to scrape. "
                "Check network connection or Google News structure changes."
            )
            sys.exit(1)

    except KeyboardInterrupt:
        logger.error("Process interrupted by user (KeyboardInterrupt)")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
