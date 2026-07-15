"""
Fetches TT site content once and stores it as structured JSON, keyed by topic.
Run this now, and only re-run later if someone notices the site has changed —
this is not meant to run on every pipeline execution.
"""

import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://trinitytreepsych.com"

PAGES = {
    "home": "/",
    "about": "/about",
    "therapeutic_services": "/therapeutic-services",
    "speech_language": "/speech-and-language",
    "psychiatry_medication": "/psychiatry-&-medication",
    "psychological_evaluations": "/psychological-evaluations",
    "neuropsychological_evals": "/neuropsychological-evals",
    "softwave_trt": "/softwave-trt",
    "insurance_payments": "/insurance-&-payments",
    "students": "/students",
    "faqs": "/faqs",
    "contact": "/contact",
}

OUTPUT_PATH = Path("content/site_content.json")


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_page(path: str) -> str:
    url = BASE_URL + path
    resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return extract_text(resp.text)


def main():
    content = {}
    for topic, path in PAGES.items():
        print(f"Fetching {topic} ({path})...")
        try:
            content[topic] = fetch_page(path)
        except requests.RequestException as e:
            print(f"  FAILED: {e}")
            content[topic] = None
        time.sleep(1)  # be polite, this is a small site with no rate-limit headroom to test

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(content, indent=2), encoding="utf-8")
    print(f"\nSaved {len(content)} pages to {OUTPUT_PATH}")

    failed = [k for k, v in content.items() if v is None]
    if failed:
        print(f"Failed to fetch: {failed} — check these URLs manually, site structure may differ from what's assumed here.")


if __name__ == "__main__":
    main()