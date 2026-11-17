"""Small helpers for downloading data and cleaning up HTML."""

import html
import re
import time

import requests

# A plain, generic name for our program when it talks to websites.
HEADERS = {"User-Agent": "internship-agent/0.1"}


def request(method, url, tries=4, **kwargs):
    """Make a web request, waiting and trying again if the site says we're
    asking too often ("429 Too Many Requests"). Raises an error if it fails."""
    kwargs.setdefault("timeout", 20)
    kwargs["headers"] = {**HEADERS, **kwargs.get("headers", {})}
    for attempt in range(tries):
        response = requests.request(method, url, **kwargs)
        if response.status_code != 429 or attempt == tries - 1:
            break
        wait = response.headers.get("Retry-After", "")
        time.sleep(min(int(wait), 30) if wait.isdigit() else 2 * 2 ** attempt)  # 2, 4, 8 seconds
    response.raise_for_status()  # turns "404 Not Found" etc. into an error
    return response


def get_json(url, timeout=20):
    """Download a URL and return its JSON data. Raises an error if it fails."""
    return request("GET", url, timeout=timeout).json()


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
