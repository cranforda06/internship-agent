"""Small helpers for downloading data and cleaning up HTML."""

import html
import re

import requests

# A plain, generic name for our program when it talks to websites.
HEADERS = {"User-Agent": "internship-agent/0.1"}


def get_json(url, timeout=20):
    """Download a URL and return its JSON data. Raises an error if it fails."""
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()  # turns "404 Not Found" etc. into an error
    return response.json()


def html_to_text(raw):
    """Turn a job description's HTML into readable plain text."""
    if not raw:
        return ""
    text = html.unescape(raw)  # Greenhouse sends "&lt;p&gt;" instead of "<p>"
    # Line breaks where the HTML had paragraphs, list items, and breaks.
    text = re.sub(r"(?i)<\s*(br|/p|/li|/h\d|/div)\s*/?>", "\n", text)
    text = re.sub(r"(?i)<\s*li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", "", text)          # remove all remaining tags
    text = html.unescape(text)                    # decode &amp; etc. left over
    text = re.sub(r"[ \t\xa0]+", " ", text)       # squash extra spaces
    text = re.sub(r"\n\s*\n+", "\n\n", text)      # squash extra blank lines
    return text.strip()
