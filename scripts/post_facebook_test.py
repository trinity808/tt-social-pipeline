"""
One-time manual test: shows a hardcoded caption and one existing image from
generated_images/ for human review, and only posts to Facebook if explicitly
confirmed.

TEMPORARY: skips the graph entirely (no OpenAI/Gemini calls) to avoid
burning tokens while debugging the Facebook API call itself. Swap back to
the full graph once posting is confirmed working.

Run from the repo root: python -m scripts.post_facebook_test
"""

import mimetypes
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

ACCESS_TOKEN = os.environ["META_ACCESS_TOKEN"].strip()
PAGE_ID = os.environ["FACEBOOK_PAGE_ID"].strip()

GRAPH_API_VERSION = os.getenv(
    "META_GRAPH_VERSION",
    "v25.0",  # v26.0 doesn't exist yet -- not expected until ~Sept 2026
).strip()

if not GRAPH_API_VERSION.startswith("v"):
    GRAPH_API_VERSION = f"v{GRAPH_API_VERSION}"

PHOTO_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PAGE_ID}/photos"

IMAGE_DIR = Path("generated_images")

# TEMPORARY hardcoded caption -- swap back to the graph once posting works
HARDCODED_CAPTION = "This is a test post from Trinity Tree's new pipeline. Please ignore."


def find_test_image() -> Path:
    if not IMAGE_DIR.is_dir():
        raise FileNotFoundError(f"'{IMAGE_DIR}' directory not found -- run from the repo root.")

    images = sorted(
        p for p in IMAGE_DIR.iterdir()
        if p.suffix.lower() in {".png", ".jpg", ".jpeg"}
    )

    if not images:
        raise FileNotFoundError(f"No image files found in '{IMAGE_DIR}'.")

    return images[0]


def post_to_facebook(caption: str, image_path: Path) -> None:
    content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"

    print(f"\nUploading {image_path.name} to Facebook...")

    with image_path.open("rb") as image_file:
        response = requests.post(
            PHOTO_URL,
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
            data={"message": caption, "published": "true"},
            files={"source": (image_path.name, image_file, content_type)},
            timeout=120,
        )

    try:
        response_body = response.json()
    except ValueError:
        response_body = {"response": response.text}

    print("Facebook response:", response.status_code, response_body)

    if response.status_code == 200:
        print(f"\nPosted successfully. Photo ID: {response_body.get('id')}")
        if response_body.get("post_id"):
            print(f"Post ID: {response_body.get('post_id')}")
    else:
        print(f"\nFAILED -- status {response.status_code}")


if __name__ == "__main__":
    image_path = find_test_image()

    print("--- Caption to post ---")
    print(HARDCODED_CAPTION)
    print(f"--- Image: {image_path} ---\n")

    confirm = input("Post this to TT's real Facebook page? Type 'yes' to confirm: ").strip().lower()

    if confirm == "yes":
        post_to_facebook(HARDCODED_CAPTION, image_path)
    else:
        print("Not posted.")