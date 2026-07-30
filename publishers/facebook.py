from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Sequence

import requests
from dotenv import load_dotenv
from google.api_core.exceptions import (
    DeadlineExceeded,
    FailedPrecondition,
    GoogleAPIError,
    NotFound,
    PermissionDenied,
    ServiceUnavailable,
)
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import secretmanager
from pipeline.prompts import format_caption


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

# Secret Manager secret name, not the long Meta access token.
META_ACCESS_TOKEN_SECRET_ID = "META_ACCESS_TOKEN"

REQUEST_TIMEOUT_SECONDS = 120


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class FacebookPublishError(RuntimeError):
    """Raised when Facebook rejects or cannot complete a post."""


class FacebookAuthenticationError(FacebookPublishError):
    """Raised when the Facebook access token is invalid or expired."""


class FacebookPermissionError(FacebookPublishError):
    """Raised when the token lacks permission to publish."""


class FacebookRateLimitError(FacebookPublishError):
    """Raised when Meta rate-limits the request."""


class FacebookTemporaryError(FacebookPublishError):
    """Raised when Meta or the network has a temporary failure."""


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
        raise FacebookPublishError(
            "Missing required environment variable(s): "
            f"{', '.join(missing_values)}.\n"
            "Add them to the project's .env file or runtime environment."
        )

    if not GRAPH_API_VERSION:
        raise FacebookPublishError(
            "META_GRAPH_VERSION cannot be empty."
        )

    if not GRAPH_API_VERSION.startswith("v"):
        raise FacebookPublishError(
            "META_GRAPH_VERSION must begin with 'v'. "
            "For example: v25.0"
        )


# ---------------------------------------------------------------------------
# Google Secret Manager
# ---------------------------------------------------------------------------

def _get_secret(secret_id: str) -> str:
    """
    Read the latest enabled value from Google Secret Manager.

    This function only reads the secret. It does not update,
    rotate, or create secret versions.
    """
    if not GCP_PROJECT_ID:
        raise FacebookSecretError(
            "GCP_PROJECT_ID is missing from the environment."
        )

    secret_name = (
        f"projects/{GCP_PROJECT_ID}/secrets/"
        f"{secret_id}/versions/latest"
    )

    try:
        client = secretmanager.SecretManagerServiceClient()

        response = client.access_secret_version(
            request={"name": secret_name}
        )

    except DefaultCredentialsError as error:
        raise FacebookSecretError(
            "Google Cloud application-default credentials were "
            "not found.\n"
            "For local testing, run:\n"
            "gcloud auth application-default login"
        ) from error

    except NotFound as error:
        raise FacebookSecretError(
            f"Secret Manager could not find '{secret_id}' in "
            f"GCP project '{GCP_PROJECT_ID}'.\n"
            "Confirm the project ID, secret name, and enabled "
            "secret version."
        ) from error

    except PermissionDenied as error:
        raise FacebookSecretError(
            f"Permission was denied while reading '{secret_id}'.\n"
            "The active Google account needs the Secret Manager "
            "Secret Accessor role."
        ) from error

    except FailedPrecondition as error:
        raise FacebookSecretError(
            f"The secret '{secret_id}' exists, but its latest "
            "version may be disabled or unavailable."
        ) from error

    except (DeadlineExceeded, ServiceUnavailable) as error:
        raise FacebookSecretError(
            "Google Secret Manager is temporarily unavailable "
            "or the request timed out."
        ) from error

    except GoogleAPIError as error:
        raise FacebookSecretError(
            "An unexpected Google Cloud error occurred while "
            f"reading '{secret_id}': {error}"
        ) from error

    try:
        secret_value = (
            response.payload.data
            .decode("UTF-8")
            .strip()
        )

    except UnicodeDecodeError as error:
        raise FacebookSecretError(
            f"The secret '{secret_id}' could not be decoded."
        ) from error

    if not secret_value:
        raise FacebookSecretError(
            f"The Secret Manager secret '{secret_id}' is empty."
        )

    return secret_value

# ---------------------------------------------------------------------------
# Meta API response handling
# ---------------------------------------------------------------------------

def _parse_facebook_response(
    response: requests.Response,
) -> dict:
    """Parse Meta's response and classify common failures."""
    try:
        response_body = response.json()

    except ValueError:
        response_body = {
            "raw_response": response.text,
        }

    error_details: dict = {}

    if isinstance(response_body, dict):
        possible_error = response_body.get(
            "error",
            {},
        )

        if isinstance(possible_error, dict):
            error_details = possible_error

    error_code = error_details.get("code")
    error_subcode = error_details.get("error_subcode")
    error_type = error_details.get("type")
    error_message = error_details.get(
        "message",
        "Facebook rejected the publishing request.",
    )

    try:
        normalized_error_code = (
            int(error_code)
            if error_code is not None
            else None
        )

    except (TypeError, ValueError):
        normalized_error_code = None

    authentication_failed = (
        response.status_code == 401
        or normalized_error_code in {102, 190}
    )

    if authentication_failed:
        raise FacebookAuthenticationError(
            "Facebook authentication failed. The access token "
            f"stored as '{META_ACCESS_TOKEN_SECRET_ID}' may be "
            "invalid or expired.\n"
            f"HTTP status: {response.status_code}\n"
            f"Error type: {error_type}\n"
            f"Error code: {error_code}\n"
            f"Error subcode: {error_subcode}\n"
            f"Meta message: {error_message}"
        )

    if response.status_code == 403:
        raise FacebookPermissionError(
            "Facebook denied permission to publish.\n"
            "Confirm that the Page access token belongs to the "
            "correct Page and has posting permission.\n"
            f"Error code: {error_code}\n"
            f"Error subcode: {error_subcode}\n"
            f"Meta message: {error_message}"
        )

    if response.status_code == 429:
        raise FacebookRateLimitError(
            "Meta rate-limited the Facebook request.\n"
            f"Meta message: {error_message}"
        )

    if 500 <= response.status_code < 600:
        raise FacebookTemporaryError(
            "Meta returned a temporary server error.\n"
            f"HTTP status: {response.status_code}\n"
            f"Meta message: {error_message}"
        )

    if not response.ok:
        raise FacebookPublishError(
            "Facebook publishing failed.\n"
            f"HTTP status: {response.status_code}\n"
            f"Error type: {error_type}\n"
            f"Error code: {error_code}\n"
            f"Error subcode: {error_subcode}\n"
            f"Meta message: {error_message}\n"
            f"Full response: {response_body}"
        )

    if not isinstance(response_body, dict):
        return {
            "response": response_body,
        }

    return response_body


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
        raise FacebookPublishError(
            "The Facebook caption is empty."
        )

    try:
        resolved_image_path = (
            Path(image_path)
            .expanduser()
            .resolve()
        )

    except (TypeError, ValueError, OSError) as error:
        raise FacebookPublishError(
            f"The image path is invalid: {image_path}"
        ) from error

    if not resolved_image_path.exists():
        raise FileNotFoundError(
            f"The Facebook image does not exist: "
            f"{resolved_image_path}"
        )

    if not resolved_image_path.is_file():
        raise FacebookPublishError(
            "The image path does not point to a file: "
            f"{resolved_image_path}"
        )

    access_token = os.getenv(
        "META_ACCESS_TOKEN",
        "",
    ).strip()

    if not access_token:
        raise FacebookAuthenticationError(
            "META_ACCESS_TOKEN is missing from the .env file."
        )

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
        raise FacebookPublishError(
            "Permission was denied while opening the image:\n"
            f"{resolved_image_path}"
        ) from error

    except requests.Timeout as error:
        raise FacebookTemporaryError(
            "The Facebook upload timed out after "
            f"{REQUEST_TIMEOUT_SECONDS} seconds."
        ) from error

    except requests.ConnectionError as error:
        raise FacebookTemporaryError(
            "Could not connect to the Meta Graph API. "
            "Check the internet connection."
        ) from error

    except requests.RequestException as error:
        raise FacebookPublishError(
            f"The Facebook request failed: {error}"
        ) from error

    except OSError as error:
        raise FacebookPublishError(
            "The image could not be opened or read.\n"
            f"Image: {resolved_image_path}\n"
            f"Error: {error}"
        ) from error

    response_body = _parse_facebook_response(
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