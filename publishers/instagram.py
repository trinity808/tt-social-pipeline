"""
Instagram publisher: handles the pieces LinkedIn and Facebook don't need.

Instagram's publish flow requires a publicly reachable image_url in its
very first API call -- it cannot accept a direct file upload the way
Facebook's /photos or LinkedIn's three-step upload do. This module's first
job is bridging that gap: take a locally-saved generated image and produce
a public URL Instagram's servers can actually fetch.
"""

import mimetypes
import os
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import storage
import requests
import time

load_dotenv()

GCP_PROJECT_ID = os.environ["GCP_PROJECT_ID"]
GCS_BUCKET_NAME = "tt-social-pipeline-images"

GRAPH_API_VERSION = "v25.0"

storage_client = storage.Client(project=GCP_PROJECT_ID)


def upload_image_to_gcs(image_path: str | Path) -> str:
    """Uploads a local image to Cloud Storage and returns its public URL."""
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"Generated image was not found: {path}")

    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(path.name)

    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    blob.upload_from_filename(str(path), content_type=content_type)

    return blob.public_url

def create_media_container(ig_user_id: str, image_url: str, caption: str, access_token: str) -> str:
    """Stages an image + caption for publishing. Returns a container ID --
    nothing is actually live yet until publish_container() is called."""
    response = requests.post(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{ig_user_id}/media",
        data={
            "image_url": image_url,
            "caption": caption,
            "access_token": access_token,
        },
        timeout=30,
    )
    response.raise_for_status()

    container_id = response.json().get("id")
    if not container_id:
        raise RuntimeError(f"Instagram did not return a container ID. Response: {response.text}")

    return container_id


def wait_for_container_status(container_id: str, access_token: str) -> None:
    """Polls until the container is ready to publish. Same waiting pattern
    as LinkedIn's image upload check, just a different status field."""
    for attempt in range(1, 61):
        response = requests.get(
            f"https://graph.facebook.com/{GRAPH_API_VERSION}/{container_id}",
            params={"fields": "status_code", "access_token": access_token},
            timeout=30,
        )
        response.raise_for_status()

        status = response.json().get("status_code")

        if status == "FINISHED":
            return
        if status in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Instagram container processing failed with status: {status}")
        if status != "IN_PROGRESS":
            raise RuntimeError(f"Instagram returned an unexpected container status: {status}")

        time.sleep(2)

    raise TimeoutError("Instagram container did not become FINISHED within 120 seconds.")


def publish_container(ig_user_id: str, container_id: str, access_token: str) -> str:
    """Actually publishes a ready container. Returns the published media ID."""
    response = requests.post(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{ig_user_id}/media_publish",
        data={
            "creation_id": container_id,
            "access_token": access_token,
        },
        timeout=30,
    )
    response.raise_for_status()

    media_id = response.json().get("id")
    if not media_id:
        raise RuntimeError(f"Instagram did not return a published media ID. Response: {response.text}")

    return media_id