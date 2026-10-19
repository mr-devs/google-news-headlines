"""
Purpose
    Deduplicate scraped Google News headlines and create a clean CSV file.
    Uses headline text as the deduplication key to ensure each unique headline
    appears only once per country.

Input
    JSON files with scraped headlines (../data_headlines/*_scraped_*.json)

Output
    CSV file with unique headlines (../data_headlines/deduplicated_headlines.csv)

Author
    Matthew DeVerna
"""

import sys
import os
import json
import logging
import re
import argparse

from pathlib import Path
from datetime import date

import pandas as pd

# Change working directory to script location
os.chdir(Path(__file__).resolve().parent)

# Constants
OUTPUT_DIR = Path("../data_headlines")
LOG_DIR = Path("../logs")
MAX_ARTICLES_PER_COUNTRY = (
    300  # Maximum articles to keep per country after deduplication
)
SAMPLING_SEED = 42  # Seed for deterministic sampling


def validate_article_data(data):
    """
    Validate that JSON data has all required fields.

    Parameters
    ----------
    data : dict
        Loaded JSON data from file.

    Returns
    -------
    tuple
        (is_valid: bool, missing_fields: list, articles_data: dict)
        - is_valid: True if all required root fields present
        - missing_fields: List of missing root-level field names
        - articles_data: Dict with validated articles and statistics
    """
    # Check required root-level fields
    required_root_fields = ["country", "collection_time", "articles"]
    missing_root = [field for field in required_root_fields if field not in data]

    if missing_root:
        return False, missing_root, None

    # Validate article-level fields
    required_article_fields = ["id", "headline", "link"]
    valid_articles = []
    skipped_articles = []

    for idx, article in enumerate(data["articles"]):
        missing_article_fields = [
            field for field in required_article_fields if field not in article
        ]

        if missing_article_fields:
            skipped_articles.append(
                {
                    "index": idx,
                    "missing_fields": missing_article_fields,
                    "partial_data": article,
                }
            )
        else:
            valid_articles.append(article)

    articles_data = {
        "valid": valid_articles,
        "skipped": skipped_articles,
        "total_found": len(data["articles"]),
    }

    return True, [], articles_data


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
    log_file = LOG_DIR / f"{today}_{batch_id}_deduplication.log"

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
    )

    return logging.getLogger(__name__)


def find_batch_scraped_files(batch_id):
    """
    Find all scraped JSON files for a specific batch.

    Parameters
    ----------
    batch_id : str
        Batch identifier.

    Returns
    -------
    list of Path
        List of paths to scraped JSON files for this batch.
    """
    batch_dir = OUTPUT_DIR / "google_news_scraped" / batch_id

    if not batch_dir.exists():
        return []

    # Find all files matching the pattern *_scraped*.json in batch directory
    scraped_files = list(batch_dir.glob("*_scraped*.json"))

    return sorted(scraped_files)


def load_all_articles(scraped_files, logger):
    """
    Load all articles from scraped JSON files with detailed error tracking.

    Parameters
    ----------
    scraped_files : list of Path
        List of paths to scraped JSON files.
    logger : logging.Logger
        Logger instance.

    Returns
    -------
    list of dict
        List of article dictionaries with metadata.
    """
    all_articles = []

    # Statistics tracking
    stats = {
        "files_found": len(scraped_files),
        "files_processed": 0,
        "files_failed": 0,
        "articles_found": 0,
        "articles_loaded": 0,
        "articles_skipped": 0,
    }

    for file_path in scraped_files:
        try:
            # Read and parse JSON
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

        except json.JSONDecodeError as e:
            logger.error(f"Malformed JSON in {file_path.name}: {str(e)}")
            stats["files_failed"] += 1
            continue

        except (FileNotFoundError, PermissionError) as e:
            logger.error(f"Cannot access {file_path.name}: {str(e)}")
            stats["files_failed"] += 1
            continue

        except Exception as e:
            logger.exception(f"Unexpected error reading {file_path.name}")
            stats["files_failed"] += 1
            continue

        # Validate data structure
        is_valid, missing_fields, articles_data = validate_article_data(data)

        if not is_valid:
            logger.error(
                f"File {file_path.name} missing required fields: {missing_fields}"
            )
            logger.error(
                "Skipping file due to `validate_article_data()` validation failure"
            )
            stats["files_failed"] += 1
            continue

        # Process validated articles
        stats["files_processed"] += 1
        stats["articles_found"] += articles_data["total_found"]

        try:
            country = data["country"]
            collection_time = data["collection_time"]
            # Extract just the date portion (YYYY-MM-DD)
            collection_date = collection_time.split()[0]

        except (KeyError, IndexError) as e:
            logger.exception(f"Error extracting metadata from {file_path.name}")
            stats["files_failed"] += 1
            stats["files_processed"] -= 1  # Adjust since we're failing this file
            continue

        # Load valid articles
        for article in articles_data["valid"]:
            article_record = {
                "uuid": article["id"],
                "date": collection_date,
                "country": country,
                "headline": article["headline"],
                "link": article["link"],
            }
            all_articles.append(article_record)
            stats["articles_loaded"] += 1

        # Log skipped articles
        for skipped in articles_data["skipped"]:
            stats["articles_skipped"] += 1
            logger.warning(
                f"Article {skipped['index']} in {file_path.name} "
                f"missing required fields: {skipped['missing_fields']}"
            )
            # Show partial data for debugging (truncate if needed)
            partial_str = str(skipped["partial_data"])[:100]
            logger.warning(f"Skipping article with partial data: {partial_str}...")

        logger.info(
            f"Loaded {len(articles_data['valid'])} articles from {file_path.name}"
        )

    # Log summary statistics
    logger.info("\nData loading summary:")
    logger.info(f"  Files found: {stats['files_found']}")
    logger.info(f"  Files processed successfully: {stats['files_processed']}")
    logger.info(f"  Files failed: {stats['files_failed']}")
    logger.info(f"  Total articles found: {stats['articles_found']}")
    logger.info(f"  Articles loaded successfully: {stats['articles_loaded']}")
    logger.info(f"  Articles skipped (missing fields): {stats['articles_skipped']}")

    return all_articles


def deduplicate_and_sample_articles(articles, logger):
    """
    Deduplicate articles by headline text within each country, then sample up to MAX_ARTICLES_PER_COUNTRY per country.

    Note: Uses headline text as deduplication key to ensure each unique headline appears only once.
    This prevents the same headline from appearing multiple times with different Google News links.

    Parameters
    ----------
    articles : list of dict
        List of article dictionaries with 'country' and 'headline' fields.
    logger : logging.Logger
        Logger instance.

    Returns
    -------
    pandas.DataFrame
        Deduplicated and sampled articles as a DataFrame.
    """
    df = pd.DataFrame(articles)
    initial_count = len(df)

    logger.info(f"\nTotal articles loaded: {initial_count}")
    logger.info("\nPer-country processing:")

    # Group by country and process each separately
    processed_groups = []

    for country, group in df.groupby("country"):
        initial_country_count = len(group)

        # Deduplicate within this country by headline text
        # Keep first occurrence to preserve earliest scraping timestamp
        deduped_group = group.drop_duplicates(subset=["headline"], keep="first")
        deduped_count = len(deduped_group)
        duplicates_removed = initial_country_count - deduped_count

        # Sample if needed
        if deduped_count > MAX_ARTICLES_PER_COUNTRY:
            sampled_group = deduped_group.sample(
                n=MAX_ARTICLES_PER_COUNTRY, random_state=SAMPLING_SEED
            )
            sampled_count = len(sampled_group)
            logger.info(
                f"  {country}: {initial_country_count} → "
                f"{deduped_count} (removed {duplicates_removed} duplicate headlines) → "
                f"{sampled_count} (sampled down)"
            )
            processed_groups.append(sampled_group)
        else:
            logger.info(
                f"  {country}: {initial_country_count} → "
                f"{deduped_count} (removed {duplicates_removed} duplicate headlines)"
            )
            processed_groups.append(deduped_group)

    # Combine all processed groups
    df_final = pd.concat(processed_groups, ignore_index=True)

    logger.info(f"\nTotal articles after processing: {len(df_final)}")

    # Display final counts per country
    logger.info("\nFinal article counts by country:")
    country_counts = df_final["country"].value_counts().sort_index()
    for country, count in country_counts.items():
        logger.info(f"  {country}: {count} articles")

    return df_final


def parse_arguments():
    """
    Parse command-line arguments.

    Returns
    -------
    argparse.Namespace
        Parsed arguments containing batch_id.
    """
    parser = argparse.ArgumentParser(
        description="Deduplicate scraped headlines for a specific batch."
    )
    parser.add_argument(
        "--batch-id",
        required=True,
        help="Batch identifier (e.g., 'batch_1')",
    )
    return parser.parse_args()


def main():
    """
    Main function to orchestrate the deduplication process.
    """
    # Parse command-line arguments
    args = parse_arguments()
    batch_id = args.batch_id

    logger = setup_logging(batch_id)
    logger.info(f"Starting headline deduplication process for {batch_id}")

    try:
        # Find all scraped files for this batch
        scraped_files = find_batch_scraped_files(batch_id)
        if not scraped_files:
            logger.error(
                f"No scraped files found for {batch_id} in google_news_scraped/{batch_id}/"
            )
            sys.exit(1)

        logger.info(f"Found {len(scraped_files)} scraped files to process")

        # Load all articles
        all_articles = load_all_articles(scraped_files, logger)
        if not all_articles:
            logger.error(
                f"No articles loaded from {len(scraped_files)} scraped files. Exiting."
            )
            sys.exit(1)

        # Deduplicate and sample articles
        df_deduplicated = deduplicate_and_sample_articles(all_articles, logger)

        # Save to CSV in deduplicated_headlines subdirectory with date and batch_id
        dedup_dir = OUTPUT_DIR / "deduplicated_headlines"
        dedup_dir.mkdir(parents=True, exist_ok=True)
        today = date.today().strftime("%Y-%m-%d")
        output_csv = dedup_dir / f"{today}_{batch_id}_deduplicated_headlines.csv"
        df_deduplicated.to_csv(output_csv, index=False, encoding="utf-8")
        logger.info(f"\nSuccessfully saved deduplicated headlines to {output_csv}")

    except KeyboardInterrupt:
        logger.error("Process interrupted by user (KeyboardInterrupt)")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
