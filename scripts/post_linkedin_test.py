"""
One-time manual test: runs the current graph, shows the generated LinkedIn
caption and image for human review, and only posts to LinkedIn if explicitly
confirmed.

This is NOT the Phase 4 publisher module -- no production retry logic,
token refresh, Facebook, or Instagram publishing.

Run from the repo root:

    python3 -m scripts.post_linkedin_test
"""

import mimetypes
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from pipeline.graph import build_graph
from urllib.parse import quote

load_dotenv()

ACCESS_TOKEN = os.environ["LINKEDIN_ACCESS_TOKEN"].strip()
ORG_URN_VALUE = os.environ["LINKEDIN_ORG_URN"].strip()

POST_URL = "https://api.linkedin.com/rest/posts"
IMAGE_URL = "https://api.linkedin.com/rest/images"

# May also be placed in .env:
# LINKEDIN_VERSION=202606
LINKEDIN_VERSION = os.getenv(
    "LINKEDIN_VERSION",
    "202606",
).strip()


def get_organization_urn() -> str:
    """
    Accept either:

        109586965

    or:

        urn:li:organization:109586965
    """

    if ORG_URN_VALUE.startswith("urn:li:organization:"):
        return ORG_URN_VALUE

    if ORG_URN_VALUE.isdigit():
        return f"urn:li:organization:{ORG_URN_VALUE}"

    raise ValueError(
        "LINKEDIN_ORG_URN must be a numeric organization ID "
        "or a complete urn:li:organization:... value."
    )


ORG_URN = get_organization_urn()


def get_api_headers(
    include_content_type: bool = False,
) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "LinkedIn-Version": LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }

    if include_content_type:
        headers["Content-Type"] = "application/json"

    return headers


def upload_image_to_linkedin(
    image_path: str | Path,
) -> str:
    """
    Upload an image to LinkedIn and return the resulting image URN.
    """

    path = Path(image_path)

    if not path.is_file():
        raise FileNotFoundError(
            f"Generated image was not found: {path}"
        )

    # Step 1: initialize the image upload.
    init_response = requests.post(
        f"{IMAGE_URL}?action=initializeUpload",
        headers=get_api_headers(
            include_content_type=True,
        ),
        json={
            "initializeUploadRequest": {
                "owner": ORG_URN,
            }
        },
        timeout=30,
    )

    print(
        "Initialize response:",
        init_response.status_code,
        init_response.text,
    )

    init_response.raise_for_status()

    init_body = init_response.json()
    upload_data = init_body.get("value", {})

    upload_url = upload_data.get("uploadUrl")
    image_urn = upload_data.get("image")

    if not upload_url or not image_urn:
        raise RuntimeError(
            "LinkedIn did not return an upload URL and image URN. "
            f"Response: {init_body}"
        )

    print(f"Image URN: {image_urn}")

    # Step 2: upload the actual image file.
    content_type = (
        mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )

    with path.open("rb") as image_file:
        upload_response = requests.put(
            upload_url,
            headers={
                "Authorization": f"Bearer {ACCESS_TOKEN}",
                "Content-Type": content_type,
            },
            data=image_file,
            timeout=120,
        )

    print(
        "Upload response:",
        upload_response.status_code,
        upload_response.text,
    )

    upload_response.raise_for_status()

    # Step 3: wait for LinkedIn to finish processing.
    encoded_image_urn = quote(image_urn, safe="")
    status_url = f"{IMAGE_URL}/{encoded_image_urn}"

    for attempt in range(1, 61):
        status_response = requests.get(
            status_url,
            headers=get_api_headers(),
            timeout=30,
        )

        print(
            f"Status attempt {attempt}:",
            status_response.status_code,
            status_response.text,
        )

        status_response.raise_for_status()

        status_body = status_response.json()
        status = status_body.get("status")

        if status == "AVAILABLE":
            print("LinkedIn image is ready.")
            return image_urn

        if status == "PROCESSING_FAILED":
            raise RuntimeError(
                "LinkedIn failed to process the image. "
                f"Response: {status_body}"
            )

        if status not in {
            "WAITING_UPLOAD",
            "PROCESSING",
        }:
            raise RuntimeError(
                "LinkedIn returned an unexpected image status. "
                f"Response: {status_body}"
            )

        time.sleep(2)

    raise TimeoutError(
        "LinkedIn image did not become AVAILABLE "
        "within 120 seconds."
    )


def format_caption(
    caption: str,
    hashtags: list[str],
) -> str:
    formatted_hashtags: list[str] = []

    for hashtag in hashtags:
        hashtag = hashtag.strip().replace(" ", "")

        if not hashtag:
            continue

        if not hashtag.startswith("#"):
            hashtag = f"#{hashtag}"

        formatted_hashtags.append(hashtag)

    if not formatted_hashtags:
        return caption.strip()

    return (
        f"{caption.strip()}\n\n"
        f"{' '.join(formatted_hashtags)}"
    )


def post_to_linkedin(
    caption: str,
    image_path: str | Path,
) -> None:
    print("\nUploading image to LinkedIn...")

    image_urn = upload_image_to_linkedin(
        image_path=image_path,
    )

    payload = {
        "author": ORG_URN,
        "commentary": caption,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "content": {
            "media": {
                "id": image_urn,
                "altText": (
                    "Trinity Tree Psychological Services "
                    "social media graphic"
                ),
            }
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    response = requests.post(
        POST_URL,
        headers=get_api_headers(
            include_content_type=True,
        ),
        json=payload,
        timeout=30,
    )

    if response.status_code == 201:
        post_urn = response.headers.get(
            "x-restli-id"
        )

        print("\nPosted successfully.")
        print(f"Post URN: {post_urn}")
        return

    print(
        f"\nFAILED -- status "
        f"{response.status_code}"
    )
    print(response.text)

    response.raise_for_status()


if __name__ == "__main__":
    app = build_graph()

    topic_key = input(
        "Which topic_key should this post be about? "
    ).strip()

    if not topic_key:
        raise ValueError(
            "A topic_key is required."
        )

    print("\nRunning graph...\n")

    result = app.invoke(
        {
            "topic_key": topic_key,
        }
    )

    draft = result["draft"]
    image_path = result["image_path"]

    caption = format_caption(
        caption=draft.linkedin.caption,
        hashtags=draft.linkedin.hashtags,
    )

    print("--- Generated LinkedIn caption ---")
    print(caption)
    print("-----------------------------------")
    print(
        f"Generated image: "
        f"{Path(image_path).resolve()}\n"
    )

    confirm = input(
        "Post this caption and image to TT's real "
        "LinkedIn page? Type 'yes' to confirm: "
    ).strip().lower()

    if confirm == "yes":
        post_to_linkedin(
            caption=caption,
            image_path=image_path,
        )
    else:
        print("Not posted.")