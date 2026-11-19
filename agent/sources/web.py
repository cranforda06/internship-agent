import html
import re
import time

import requests

HEADERS = {"User-Agent": "internship-agent/0.1"}


def request(method, url, tries=4, **kwargs):
    kwargs.setdefault("timeout", 20)
    kwargs["headers"] = {**HEADERS, **kwargs.get("headers", {})}
    for attempt in range(tries):
        response = requests.request(method, url, **kwargs)
        if response.status_code != 429 or attempt == tries - 1:
            break
        wait = response.headers.get("Retry-After", "")
        time.sleep(min(int(wait), 30) if wait.isdigit() else 2 * 2 ** attempt)
    response.raise_for_status()
    return response


def get_json(url, timeout=20):
    return request("GET", url, timeout=timeout).json()


def html_to_text(raw):
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"(?i)<\s*(br|/p|/li|/h\d|/div)\s*/?>", "\n", text)
    text = re.sub(r"(?i)<\s*li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()
