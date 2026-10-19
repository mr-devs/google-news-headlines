"""
Purpose
    Build Google News scraping links for different regions and languages.
    Maps topic codes to regions and generates both topic and home page URLs.

Input
    JSON file with region topic codes (../data/gnews_region_topic_codes.json)
    CSV file with region-language pairs (../data/gnews_region_language_pairs.csv)

Output
    CSV file with URLs (../data/gnews_region_language_pairs_with_urls.csv)

Author
    Matthew DeVerna
"""

import sys
import os
import json
import logging

from pathlib import Path
from datetime import date

import pandas as pd

# Change working directory to script location
os.chdir(Path(__file__).resolve().parent)

# Constants
DATA_DIR = Path("../data")
LOG_DIR = Path("../logs")
TOPIC_CODES_FILE = DATA_DIR / "gnews_region_topic_codes.json"
INPUT_CSV_FILE = DATA_DIR / "gnews_region_language_pairs.csv"
OUTPUT_CSV_FILE = DATA_DIR / "gnews_region_language_pairs_with_urls.csv"


def setup_logging():
    """
    Set up logging to both stdout and a date-named file.

    Returns
    -------
    logging.Logger
        Configured logger instance.
    """
    # Create logs directory if it doesn't exist
    LOG_DIR.mkdir(exist_ok=True)

    # Create date-named log file
    today = date.today().strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"{today}_build_scraping_links.log"

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
    )

    return logging.getLogger(__name__)


def generate_google_url_topic(topic_code, language_code, region_code):
    """
    Generate Google News topic URL.

    Parameters
    ----------
    topic_code : str
        Google News topic code for the region.
    language_code : str
        Two-letter language code (e.g., 'en', 'es').
    region_code : str
        Two-letter region code (e.g., 'us', 'mx').

    Returns
    -------
    str
        Complete Google News topic URL.
    """
    return f"https://news.google.com/topics/{topic_code}?hl={language_code}&gl={region_code}"


def generate_google_url_home(language_code, region_code):
    """
    Generate Google News home page URL.

    Parameters
    ----------
    language_code : str
        Two-letter language code (e.g., 'en', 'es').
    region_code : str
        Two-letter region code (e.g., 'us', 'mx').

    Returns
    -------
    str
        Complete Google News home page URL.
    """
    return f"https://news.google.com/home?hl={language_code}&gl={region_code}"


def load_topic_codes(logger):
    """
    Load topic codes from JSON file.

    Parameters
    ----------
    logger : logging.Logger
        Logger instance.

    Returns
    -------
    dict
        Dictionary mapping region names to topic codes.

    Raises
    ------
    FileNotFoundError
        If topic codes file does not exist.
    """
    if not TOPIC_CODES_FILE.exists():
        raise FileNotFoundError(f"Topic codes file not found: {TOPIC_CODES_FILE}")

    with open(TOPIC_CODES_FILE, "r") as f:
        topic_codes = json.loads(f.read())

    logger.info(f"Loaded {len(topic_codes)} topic codes from {TOPIC_CODES_FILE.name}")
    return topic_codes


def load_region_language_pairs(logger):
    """
    Load region-language pairs from CSV file.

    Parameters
    ----------
    logger : logging.Logger
        Logger instance.

    Returns
    -------
    pandas.DataFrame
        DataFrame with region-language pairs.

    Raises
    ------
    FileNotFoundError
        If input CSV file does not exist.
    """
    if not INPUT_CSV_FILE.exists():
        raise FileNotFoundError(
            f"Region-language pairs file not found: {INPUT_CSV_FILE}"
        )

    df = pd.read_csv(INPUT_CSV_FILE)
    logger.info(f"Loaded {len(df)} region-language pairs from {INPUT_CSV_FILE.name}")
    return df


def build_urls(df, topic_codes, logger):
    """
    Build Google News URLs for all region-language pairs.

    Parameters
    ----------
    df : pandas.DataFrame
        DataFrame with region-language pairs.
    topic_codes : dict
        Dictionary mapping region names to topic codes.
    logger : logging.Logger
        Logger instance.

    Returns
    -------
    pandas.DataFrame
        DataFrame with added URL columns.
    """
    # Map topic codes to regions
    df["topic_code"] = df["region"].map(topic_codes)
    logger.info("Mapped topic codes to regions")

    # Generate topic URLs
    df["url_topic"] = df.apply(
        lambda row: generate_google_url_topic(
            row["topic_code"], row["language_code"], row["region_code"]
        ),
        axis=1,
    )
    logger.info("Generated topic URLs")

    # Generate home page URLs
    df["url_home"] = df.apply(
        lambda row: generate_google_url_home(row["language_code"], row["region_code"]),
        axis=1,
    )
    logger.info("Generated home page URLs")

    # Replace the url_home for "World" with the "World" url_topic
    # We have to do this because there is no other "home" page for World news
    world_mask = df["region"] == "World"
    if world_mask.any():
        df.loc[world_mask, "url_home"] = df.loc[world_mask, "url_topic"].values[0]
        logger.info("Updated 'World' region to use topic URL for home page")

    return df


def save_output(df, logger):
    """
    Save the DataFrame with URLs to CSV.

    Parameters
    ----------
    df : pandas.DataFrame
        DataFrame with region-language pairs and URLs.
    logger : logging.Logger
        Logger instance.
    """
    df.to_csv(OUTPUT_CSV_FILE, index=False)
    logger.info(f"Saved {len(df)} entries to {OUTPUT_CSV_FILE}")


def display_samples(df, logger):
    """
    Display sample URLs for verification.

    Parameters
    ----------
    df : pandas.DataFrame
        DataFrame with region-language pairs and URLs.
    logger : logging.Logger
        Logger instance.
    """
    logger.info("\nSample topic URLs:")
    for _, row in df.head(5).iterrows():
        logger.info(f"  {row['region']}: {row['url_topic']}")

    logger.info("\nSample home URLs:")
    for _, row in df.head(5).iterrows():
        logger.info(f"  {row['region']}: {row['url_home']}")


def main():
    """
    Main function to orchestrate the URL building process.
    """
    logger = setup_logging()
    logger.info("Starting Google News URL building process")

    try:
        # Load topic codes
        topic_codes = load_topic_codes(logger)

        # Load region-language pairs
        df = load_region_language_pairs(logger)

        # Build URLs
        df_with_urls = build_urls(df, topic_codes, logger)

        # Save output
        save_output(df_with_urls, logger)

        # Display samples
        display_samples(df_with_urls, logger)

        logger.info("URL building process completed successfully")

    except KeyboardInterrupt:
        logger.error("Process interrupted by user (KeyboardInterrupt)")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
