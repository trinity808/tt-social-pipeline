from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Sequence

import requests
from dotenv import load_dotenv
from pipeline.prompts import format_caption
from pipeline.secrets import _get_secret
from pipeline.meta_errors import MetaAuthenticationError, MetaPermissionError, MetaPublishError, MetaRateLimitError, MetaTemporaryError, parse_meta_response


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

GCP_PROJECT_ID = os.getenv(
    "GCP_PROJECT_ID",
    "",
).strip()

FACEBOOK_PAGE_ID = os.getenv(
    "FACEBOOK_PAGE_ID",
    "",
).strip()

GRAPH_API_VERSION = os.getenv(
    "META_GRAPH_VERSION",
    "v25.0",
).strip()

if GRAPH_API_VERSION and not GRAPH_API_VERSION.startswith("v"):
    GRAPH_API_VERSION = f"v{GRAPH_API_VERSION}"

REQUEST_TIMEOUT_SECONDS = 120


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------
class FacebookSecretError(RuntimeError):
    """Raised when the token cannot be read from Secret Manager."""


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------

def _validate_configuration() -> None:
    """Validate required Facebook publisher configuration values."""
    missing_values: list[str] = []

    if not GCP_PROJECT_ID:
        missing_values.append("GCP_PROJECT_ID")

    if not FACEBOOK_PAGE_ID:
        missing_values.append("FACEBOOK_PAGE_ID")

    if missing_values:
        raise MetaPublishError(
            "Missing required environment variable(s): "
            f"{', '.join(missing_values)}.\n"
            "Add them to the project's .env file or runtime environment."
        )

    if not GRAPH_API_VERSION:
        raise MetaPublishError(
            "META_GRAPH_VERSION cannot be empty."
        )

    if not GRAPH_API_VERSION.startswith("v"):
        raise MetaPublishError(
            "META_GRAPH_VERSION must begin with 'v'. "
            "For example: v25.0"
        )

# ---------------------------------------------------------------------------
# Facebook publishing
# ---------------------------------------------------------------------------

def post_to_facebook(
    caption: str,
    hashtags: Sequence[str],
    image_path: str | Path,
) -> dict:
    """
    Upload an image and publish it to the configured Facebook Page.

    The Page access token is read from GCP Secret Manager.
    """
    _validate_configuration()

    if not isinstance(caption, str) or not caption.strip():
        raise MetaPublishError(
            "The Facebook caption is empty."
        )

    try:
        resolved_image_path = (
            Path(image_path)
            .expanduser()
            .resolve()
        )

    except (TypeError, ValueError, OSError) as error:
        raise MetaPublishError(
            f"The image path is invalid: {image_path}"
        ) from error

    if not resolved_image_path.exists():
        raise FileNotFoundError(
            f"The Facebook image does not exist: "
            f"{resolved_image_path}"
        )

    if not resolved_image_path.is_file():
        raise MetaPublishError(
            "The image path does not point to a file: "
            f"{resolved_image_path}"
        )

    access_token = _get_secret("meta-access-token")

    message = format_caption(
        caption=caption,
        hashtags=hashtags,
    )

    photo_url = (
        f"https://graph.facebook.com/"
        f"{GRAPH_API_VERSION}/"
        f"{FACEBOOK_PAGE_ID}/photos"
    )

    content_type = (
        mimetypes.guess_type(
            resolved_image_path.name
        )[0]
        or "application/octet-stream"
    )

    print(
        f"\n[facebook] Uploading image: "
        f"{resolved_image_path}"
    )

    try:
        with resolved_image_path.open("rb") as image_file:
            response = requests.post(
                photo_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                },
                data={
                    "message": message,
                    "published": "true",
                },
                files={
                    "source": (
                        resolved_image_path.name,
                        image_file,
                        content_type,
                    ),
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

    except PermissionError as error:
        raise MetaPublishError(
            "Permission was denied while opening the image:\n"
            f"{resolved_image_path}"
        ) from error

    except requests.Timeout as error:
        raise MetaTemporaryError(
            "The Facebook upload timed out after "
            f"{REQUEST_TIMEOUT_SECONDS} seconds."
        ) from error

    except requests.ConnectionError as error:
        raise MetaTemporaryError(
            "Could not connect to the Meta Graph API. "
            "Check the internet connection."
        ) from error

    except requests.RequestException as error:
        raise MetaPublishError(
            f"The Facebook request failed: {error}"
        ) from error

    except OSError as error:
        raise MetaPublishError(
            "The image could not be opened or read.\n"
            f"Image: {resolved_image_path}\n"
            f"Error: {error}"
        ) from error

    response_body = parse_meta_response(
        response
    )

    print(
        "\n[facebook] Post published successfully."
    )

    if response_body.get("post_id"):
        print(
            f"[facebook] Post ID: "
            f"{response_body['post_id']}"
        )

    if response_body.get("id"):
        print(
            f"[facebook] Photo ID: "
            f"{response_body['id']}"
        )

    return response_body