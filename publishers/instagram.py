"""
Instagram publisher: handles the pieces LinkedIn and Facebook don't need.

Instagram's publish flow requires a publicly reachable image_url in its
very first API call -- it cannot accept a direct file upload the way
Facebook's /photos or LinkedIn's three-step upload do. This module's first
job is bridging that gap: take a locally-saved generated image and produce
a public URL Instagram's servers can actually fetch.
"""

import os
import time
from pathlib import Path

import requests

from pipeline.logging_config import get_logger
from pipeline.meta_errors import parse_meta_response, MetaTemporaryError
from pipeline.prompts import format_caption
from pipeline.secrets import _get_secret
from pipeline.storage import upload_image_to_gcs

GRAPH_API_VERSION = os.getenv(
    "META_GRAPH_VERSION",
    "v25.0",
).strip()

INSTAGRAM_BUSINESS_ACCOUNT_ID = os.getenv(
    "INSTAGRAM_BUSINESS_ACCOUNT_ID", 
    "",
).strip()

logger = get_logger(__name__)


def create_media_container(ig_user_id: str, image_url: str, caption: str, access_token: str) -> str:
    """Stages an image + caption for publishing. Returns a container ID --
    nothing is actually live yet until publish_container() is called."""
    try:
        response = requests.post(
            f"https://graph.facebook.com/{GRAPH_API_VERSION}/{ig_user_id}/media",
            data={
                "image_url": image_url,
                "caption": caption,
                "access_token": access_token,
            },
            timeout=30,
        )
    except (requests.Timeout, requests.ConnectionError) as e:
        raise MetaTemporaryError(f"Network error while creating media container: {e}") from e

    response_body = parse_meta_response(response)

    container_id = response_body.get("id")
    if not container_id:
        raise RuntimeError(f"Instagram did not return a container ID. Response: {response_body}")

    logger.info(f"media container created: {container_id}")
    return container_id


def wait_for_container_status(container_id: str, access_token: str) -> None:
    """Polls until the container is ready to publish. Same waiting pattern
    as LinkedIn's image upload check, just a different status field."""
    logger.info(f"waiting for container {container_id} to finish processing...")

    for attempt in range(1, 61):
        try:
            response = requests.get(
                f"https://graph.facebook.com/{GRAPH_API_VERSION}/{container_id}",
                params={"fields": "status_code", "access_token": access_token},
                timeout=30,
            )
        except (requests.Timeout, requests.ConnectionError) as e:
            raise MetaTemporaryError(f"Network error while checking container status: {e}") from e

        response_body = parse_meta_response(response)

        status = response_body.get("status_code")

        if status == "FINISHED":
            logger.info(f"container {container_id} ready to publish")
            return
        if status in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Instagram container processing failed with status: {status}")
        if status != "IN_PROGRESS":
            raise RuntimeError(f"Instagram returned an unexpected container status: {status}")

        time.sleep(2)

    raise TimeoutError("Instagram container did not become FINISHED within 120 seconds.")


def publish_container(ig_user_id: str, container_id: str, access_token: str) -> str:
    """Actually publishes a ready container. Returns the published media ID."""
    try:
        response = requests.post(
            f"https://graph.facebook.com/{GRAPH_API_VERSION}/{ig_user_id}/media_publish",
            data={
                "creation_id": container_id,
                "access_token": access_token,
            },
            timeout=30,
        )
    except (requests.Timeout, requests.ConnectionError) as e:
        raise MetaTemporaryError(f"Network error while publishing container: {e}") from e

    response_body = parse_meta_response(response)

    media_id = response_body.get("id")
    if not media_id:
        raise RuntimeError(f"Instagram did not return a published media ID. Response: {response_body}")

    logger.info(f"posted successfully. Media ID: {media_id}")
    return media_id


def publish_to_instagram(caption: str, hashtags: list[str], image_path: str | Path) -> str:
    """Publishes an approved caption + image to Instagram. Returns the
    published media ID."""
    if not INSTAGRAM_BUSINESS_ACCOUNT_ID:
        raise RuntimeError("INSTAGRAM_BUSINESS_ACCOUNT_ID is missing from the .env file.")

    access_token = _get_secret("meta-access-token")
    formatted_caption = format_caption(caption, hashtags)

    image_url = upload_image_to_gcs(image_path)

    container_id = create_media_container(
        ig_user_id=INSTAGRAM_BUSINESS_ACCOUNT_ID,
        image_url=image_url,
        caption=formatted_caption,
        access_token=access_token,
    )

    wait_for_container_status(container_id, access_token)

    return publish_container(INSTAGRAM_BUSINESS_ACCOUNT_ID, container_id, access_token)