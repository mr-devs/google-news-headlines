"""
News scraping utilities for Google News headline collection.

This module provides a function for scraping Google News headlines.
"""

import requests

from bs4 import BeautifulSoup
from datetime import datetime


def collect_google_news(url):
    """
    Scrape headlines and links from Google News.

    Parameters
    ----------
    url : str
        Google News URL to scrape.

    Returns
    -------
    dict
        Dictionary containing collection timestamp, headlines, and links.
        Keys: 'collection', 'headlines', 'links'
    """
    page = requests.get(url)
    if page.status_code != 200:
        raise ValueError(f"HTTP request failed with status code: {page.status_code}")

    soup = BeautifulSoup(page.content, "html.parser")
    # Test various selectors for headlines if earlier ones fail
    # Handles different Google News layouts (e.g., Botswana)
    elements = (
        soup.select("a.gPFEn")
        + soup.select("a.JtKRv")
        + soup.select("a.iTin5e")
        + soup.select("a.WwrzSb")
    )

    articles = []
    for element in elements:
        headline = element.text.strip()
        if headline == "":
            continue
        link = element["href"].replace("./read/", "https://news.google.com/articles/")
        articles.append({"headline": headline, "link": link})

    container = {
        "collection_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "articles": articles,
    }
    return container
