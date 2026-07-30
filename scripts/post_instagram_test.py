"""
One-time manual Instagram publishing test using a Google Drive image.

This script skips the LangGraph pipeline and AI/image generation calls.

Flow:
1. Read a Google Drive sharing link from .env.
2. Convert it to a direct-download URL.
3. Confirm that the image is publicly accessible.
4. Read the Meta access token from GCP Secret Manager.
5. Verify the Instagram account connected to the Facebook Page.
6. Create an Instagram media container.
7. Wait for the container to finish processing.
8. Publish after explicit user confirmation.

Run from the repository root:

    python -m scripts.post_instagram_test

The Google Drive file must be shared as:
    Anyone with the link -> Viewer
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

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


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

GCP_PROJECT_ID = os.getenv(
    "GCP_PROJECT_ID",
    "",
).strip()

FACEBOOK_PAGE_ID = os.getenv(
    "FACEBOOK_PAGE_ID",
    "",
).strip()

INSTAGRAM_ACCOUNT_ID = "17841476123372072"

GOOGLE_DRIVE_IMAGE_URL = "https://drive.google.com/file/d/1riWKpflj1xVZTe74Fs0xsN5rZ_E1Q-ic/view?usp=drive_link"

GRAPH_API_VERSION = os.getenv(
    "META_GRAPH_VERSION",
    "v25.0",
).strip()

if GRAPH_API_VERSION and not GRAPH_API_VERSION.startswith("v"):
    GRAPH_API_VERSION = f"v{GRAPH_API_VERSION}"

# The existing Secret Manager secret containing the Meta access token.
INSTAGRAM_ACCESS_TOKEN_SECRET_ID = os.getenv(
    "instagram_access_token_secret_id","",
).strip()

REQUEST_TIMEOUT_SECONDS = 120

# Poll every 20 seconds for up to five minutes.
CONTAINER_POLL_INTERVAL_SECONDS = 20
MAX_CONTAINER_POLL_ATTEMPTS = 15

HARDCODED_CAPTION = (
    "This is a test post from Trinity Tree's new Instagram "
    "publishing pipeline. Please ignore.\n\n"
    "#TrinityTreePsychServices #MentalHealth #GlendaleAZ"
)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class InstagramPublishError(RuntimeError):
    """Raised when Instagram publishing cannot be completed."""


class InstagramAuthenticationError(InstagramPublishError):
    """Raised when the Meta access token is invalid or expired."""


class InstagramPermissionError(InstagramPublishError):
    """Raised when the token lacks required Meta permissions."""


class InstagramSecretError(RuntimeError):
    """Raised when the access token cannot be read from GCP."""


class GoogleDriveImageError(RuntimeError):
    """Raised when the Google Drive image is not publicly accessible."""


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------

def validate_configuration() -> None:
    """Validate all required configuration values."""
    missing_values: list[str] = []

    if not GCP_PROJECT_ID:
        missing_values.append("GCP_PROJECT_ID")

    if not FACEBOOK_PAGE_ID:
        missing_values.append("FACEBOOK_PAGE_ID")

    if not INSTAGRAM_ACCOUNT_ID:
        missing_values.append("INSTAGRAM_ACCOUNT_ID")

    if not GOOGLE_DRIVE_IMAGE_URL:
        missing_values.append("GOOGLE_DRIVE_IMAGE_URL")

    if not INSTAGRAM_ACCESS_TOKEN_SECRET_ID:
        missing_values.append(
            "INSTAGRAM_ACCESS_TOKEN_SECRET_ID"
        )

    if missing_values:
        raise InstagramPublishError(
            "Missing required environment variable(s): "
            f"{', '.join(missing_values)}"
        )

    if not GRAPH_API_VERSION:
        raise InstagramPublishError(
            "META_GRAPH_VERSION cannot be empty."
        )


# ---------------------------------------------------------------------------
# Google Drive connection
# ---------------------------------------------------------------------------

def extract_google_drive_file_id(shared_url: str) -> str:
    """
    Extract a Google Drive file ID from common sharing-link formats.

    Supported examples:

    https://drive.google.com/file/d/FILE_ID/view
    https://drive.google.com/open?id=FILE_ID
    https://drive.google.com/uc?id=FILE_ID
    """
    patterns = [
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"[?&]id=([a-zA-Z0-9_-]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, shared_url)

        if match:
            return match.group(1)

    raise GoogleDriveImageError(
        "Could not extract a Google Drive file ID from "
        "GOOGLE_DRIVE_IMAGE_URL.\n"
        "Use a file-sharing link similar to:\n"
        "https://drive.google.com/file/d/FILE_ID/view"
    )


def build_google_drive_download_url(
    shared_url: str,
) -> str:
    """
    Convert a Google Drive sharing link to a direct-download URL.
    """
    file_id = extract_google_drive_file_id(shared_url)

    return (
        "https://drive.google.com/"
        f"uc?export=download&id={file_id}"
    )


def _looks_like_image(
    content_type: str,
    first_bytes: bytes,
) -> bool:
    """Determine whether the downloaded response looks like an image."""
    normalized_content_type = content_type.lower()

    if normalized_content_type.startswith("image/"):
        return True

    # JPEG magic bytes
    if first_bytes.startswith(b"\xff\xd8\xff"):
        return True

    # PNG magic bytes
    if first_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return True

    return False


def verify_public_google_drive_image(
    image_url: str,
) -> None:
    """
    Verify that Google Drive returns an image instead of an HTML page.

    This catches:
    - Private or restricted files
    - Invalid links
    - Google sign-in pages
    - Drive preview pages
    - Download warning pages
    """
    print(
        "\n[google-drive] Verifying that the image is public..."
    )

    try:
        response = requests.get(
            image_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 TrinityTreeInstagramPublisher/1.0"
                )
            },
            timeout=30,
            allow_redirects=True,
            stream=True,
        )

    except requests.Timeout as error:
        raise GoogleDriveImageError(
            "The Google Drive image request timed out."
        ) from error

    except requests.ConnectionError as error:
        raise GoogleDriveImageError(
            "Could not connect to Google Drive."
        ) from error

    except requests.RequestException as error:
        raise GoogleDriveImageError(
            f"Google Drive request failed: {error}"
        ) from error

    try:
        if not response.ok:
            raise GoogleDriveImageError(
                "Google Drive did not return the image successfully.\n"
                f"HTTP status: {response.status_code}"
            )

        content_type = response.headers.get(
            "Content-Type",
            "",
        )

        first_bytes = next(
            response.iter_content(chunk_size=64),
            b"",
        )

        normalized_bytes = first_bytes.lstrip().lower()

        if (
            "text/html" in content_type.lower()
            or normalized_bytes.startswith(b"<!doctype html")
            or normalized_bytes.startswith(b"<html")
        ):
            raise GoogleDriveImageError(
                "Google Drive returned an HTML page instead of an "
                "image.\n"
                "Confirm the file is shared as:\n"
                "Anyone with the link -> Viewer"
            )

        if not _looks_like_image(
            content_type=content_type,
            first_bytes=first_bytes,
        ):
            raise GoogleDriveImageError(
                "The Google Drive link did not return a recognized "
                "image.\n"
                f"Returned Content-Type: "
                f"{content_type or 'unknown'}"
            )

    finally:
        response.close()

    print(
        "[google-drive] The image is publicly accessible."
    )


# ---------------------------------------------------------------------------
# GCP Secret Manager
# ---------------------------------------------------------------------------

def _get_secret(secret_id: str) -> str:
    """
    Read the latest enabled version of a GCP Secret Manager secret.

    This function only reads the token. It does not rotate or update it.
    """
    secret_name = (
        f"projects/{GCP_PROJECT_ID}/secrets/"
        f"{secret_id}/versions/latest"
    )

    try:
        client = secretmanager.SecretManagerServiceClient()

        response = client.access_secret_version(
            request={
                "name": secret_name,
            }
        )

    except DefaultCredentialsError as error:
        raise InstagramSecretError(
            "Google Cloud application-default credentials were not "
            "found.\n"
            "For local testing, run:\n"
            "gcloud auth application-default login"
        ) from error

    except NotFound as error:
        raise InstagramSecretError(
            f"Secret '{secret_id}' was not found in GCP project "
            f"'{GCP_PROJECT_ID}'."
        ) from error

    except PermissionDenied as error:
        raise InstagramSecretError(
            f"Permission was denied while reading '{secret_id}'.\n"
            "Your active Google account needs the Secret Manager "
            "Secret Accessor role."
        ) from error

    except FailedPrecondition as error:
        raise InstagramSecretError(
            f"The latest version of '{secret_id}' may be disabled "
            "or unavailable."
        ) from error

    except (DeadlineExceeded, ServiceUnavailable) as error:
        raise InstagramSecretError(
            "Google Secret Manager is temporarily unavailable."
        ) from error

    except GoogleAPIError as error:
        raise InstagramSecretError(
            f"Unexpected GCP error while reading '{secret_id}': "
            f"{error}"
        ) from error

    try:
        access_token = (
            response.payload.data
            .decode("UTF-8")
            .strip()
        )
    except UnicodeDecodeError as error:
        raise InstagramSecretError(
            f"Secret '{secret_id}' could not be decoded."
        ) from error

    if not access_token:
        raise InstagramSecretError(
            f"Secret '{secret_id}' is empty."
        )

    return access_token


# ---------------------------------------------------------------------------
# Meta API request handling
# ---------------------------------------------------------------------------

def parse_meta_response(
    response: requests.Response,
    operation: str,
) -> dict[str, Any]:
    """Parse and validate a Meta Graph API response."""
    try:
        response_body = response.json()
    except ValueError:
        response_body = {
            "raw_response": response.text,
        }

    error_details: dict[str, Any] = {}

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
        "Meta rejected the request.",
    )

    try:
        normalized_error_code = (
            int(error_code)
            if error_code is not None
            else None
        )
    except (TypeError, ValueError):
        normalized_error_code = None

    if (
        response.status_code == 401
        or normalized_error_code in {102, 190}
    ):
        raise InstagramAuthenticationError(
            f"{operation} failed because the Meta access token is "
            "invalid or expired.\n"
            f"HTTP status: {response.status_code}\n"
            f"Error type: {error_type}\n"
            f"Error code: {error_code}\n"
            f"Error subcode: {error_subcode}\n"
            f"Meta message: {error_message}"
        )

    if (
        response.status_code == 403
        or normalized_error_code in {10, 200}
    ):
        raise InstagramPermissionError(
            f"{operation} was denied by Meta.\n"
            "Confirm that the access token has Instagram publishing "
            "permission and access to the connected Instagram "
            "professional account.\n"
            f"Error code: {error_code}\n"
            f"Error subcode: {error_subcode}\n"
            f"Meta message: {error_message}"
        )

    if response.status_code == 429:
        raise InstagramPublishError(
            f"{operation} was rate-limited by Meta.\n"
            f"Meta message: {error_message}"
        )

    if 500 <= response.status_code < 600:
        raise InstagramPublishError(
            f"{operation} failed because Meta returned a temporary "
            "server error.\n"
            f"HTTP status: {response.status_code}\n"
            f"Meta message: {error_message}"
        )

    if not response.ok:
        raise InstagramPublishError(
            f"{operation} failed.\n"
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


def send_meta_request(
    method: str,
    url: str,
    access_token: str,
    operation: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Send a Meta request with shared error handling."""
    headers = kwargs.pop(
        "headers",
        {},
    )

    headers["Authorization"] = (
        f"Bearer {access_token}"
    )

    try:
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
            **kwargs,
        )

    except requests.Timeout as error:
        raise InstagramPublishError(
            f"{operation} timed out after "
            f"{REQUEST_TIMEOUT_SECONDS} seconds."
        ) from error

    except requests.ConnectionError as error:
        raise InstagramPublishError(
            f"{operation} could not connect to Meta."
        ) from error

    except requests.RequestException as error:
        raise InstagramPublishError(
            f"{operation} request failed: {error}"
        ) from error

    return parse_meta_response(
        response=response,
        operation=operation,
    )


# ---------------------------------------------------------------------------
# Facebook Page and Instagram account verification
# ---------------------------------------------------------------------------

def verify_instagram_account_connection(
    access_token: str,
) -> None:
    """
    Verify that INSTAGRAM_ACCOUNT_ID is connected to FACEBOOK_PAGE_ID.
    """
    page_url = (
        f"https://graph.facebook.com/"
        f"{GRAPH_API_VERSION}/"
        f"{FACEBOOK_PAGE_ID}"
    )

    response_body = send_meta_request(
        method="GET",
        url=page_url,
        access_token=access_token,
        operation="Instagram account verification",
        params={
            "fields": "instagram_business_account",
        },
    )

    connected_account = response_body.get(
        "instagram_business_account",
        {},
    )

    if not isinstance(connected_account, dict):
        connected_account = {}

    connected_instagram_id = connected_account.get("id")

    if not connected_instagram_id:
        raise InstagramPublishError(
            "The configured Facebook Page did not return a connected "
            "Instagram professional account."
        )

    if str(connected_instagram_id) != INSTAGRAM_ACCOUNT_ID:
        raise InstagramPublishError(
            "The Instagram account ID does not match the account "
            "connected to the Facebook Page.\n"
            f"Configured Instagram ID: {INSTAGRAM_ACCOUNT_ID}\n"
            f"Connected Instagram ID: {connected_instagram_id}"
        )

    print(
        "[instagram] Facebook Page and Instagram account "
        "connection verified."
    )


# ---------------------------------------------------------------------------
# Instagram container creation
# ---------------------------------------------------------------------------

def create_media_container(
    caption: str,
    image_url: str,
    access_token: str,
) -> str:
    """Create an Instagram image-media container."""
    media_url = (
        f"https://graph.facebook.com/"
        f"{GRAPH_API_VERSION}/"
        f"{INSTAGRAM_ACCOUNT_ID}/media"
    )

    print(
        "\n[instagram] Creating the media container..."
    )

    response_body = send_meta_request(
        method="POST",
        url=media_url,
        access_token=access_token,
        operation="Instagram media-container creation",
        data={
            "image_url": image_url,
            "caption": caption,
        },
    )

    container_id = response_body.get("id")

    if not container_id:
        raise InstagramPublishError(
            "Meta did not return an Instagram media-container ID."
        )

    print(
        f"[instagram] Container ID: {container_id}"
    )

    return str(container_id)


def get_container_status(
    container_id: str,
    access_token: str,
) -> tuple[str, str]:
    """Return the status code and optional status message."""
    status_url = (
        f"https://graph.facebook.com/"
        f"{GRAPH_API_VERSION}/"
        f"{container_id}"
    )

    response_body = send_meta_request(
        method="GET",
        url=status_url,
        access_token=access_token,
        operation="Instagram container-status check",
        params={
            "fields": "status_code,status",
        },
    )

    status_code = str(
        response_body.get(
            "status_code",
            "UNKNOWN",
        )
    ).upper()

    status_message = str(
        response_body.get(
            "status",
            "",
        )
    )

    return status_code, status_message


def wait_for_container(
    container_id: str,
    access_token: str,
) -> None:
    """Wait until the Instagram media container is ready."""
    for attempt in range(
        1,
        MAX_CONTAINER_POLL_ATTEMPTS + 1,
    ):
        status_code, status_message = get_container_status(
            container_id=container_id,
            access_token=access_token,
        )

        print(
            f"[instagram] Container status "
            f"({attempt}/{MAX_CONTAINER_POLL_ATTEMPTS}): "
            f"{status_code}"
        )

        if status_message:
            print(
                f"[instagram] Status message: {status_message}"
            )

        if status_code in {
            "FINISHED",
            "PUBLISHED",
        }:
            return

        if status_code in {
            "ERROR",
            "EXPIRED",
        }:
            raise InstagramPublishError(
                "The Instagram media container could not be "
                "processed.\n"
                f"Status: {status_code}\n"
                f"Message: {status_message or 'No message returned.'}"
            )

        if attempt < MAX_CONTAINER_POLL_ATTEMPTS:
            print(
                "[instagram] Waiting "
                f"{CONTAINER_POLL_INTERVAL_SECONDS} seconds..."
            )

            time.sleep(
                CONTAINER_POLL_INTERVAL_SECONDS
            )

    raise InstagramPublishError(
        "The Instagram media container was not ready within "
        "five minutes."
    )


def publish_media_container(
    container_id: str,
    access_token: str,
) -> dict[str, Any]:
    """Publish a completed Instagram media container."""
    publish_url = (
        f"https://graph.facebook.com/"
        f"{GRAPH_API_VERSION}/"
        f"{INSTAGRAM_ACCOUNT_ID}/media_publish"
    )

    print(
        "\n[instagram] Publishing the media container..."
    )

    return send_meta_request(
        method="POST",
        url=publish_url,
        access_token=access_token,
        operation="Instagram media publishing",
        data={
            "creation_id": container_id,
        },
    )


# ---------------------------------------------------------------------------
# Complete Instagram publishing flow
# ---------------------------------------------------------------------------

def post_to_instagram(
    caption: str,
    google_drive_share_url: str,
) -> dict[str, Any]:
    """Publish one Google Drive image to Instagram."""
    validate_configuration()

    direct_image_url = build_google_drive_download_url(
        google_drive_share_url
    )

    verify_public_google_drive_image(
        direct_image_url
    )

    access_token = _get_secret(
        INSTAGRAM_ACCESS_TOKEN_SECRET_ID
    )

    verify_instagram_account_connection(
        access_token=access_token
    )

    container_id = create_media_container(
        caption=caption,
        image_url=direct_image_url,
        access_token=access_token,
    )

    wait_for_container(
        container_id=container_id,
        access_token=access_token,
    )

    return publish_media_container(
        container_id=container_id,
        access_token=access_token,
    )


# ---------------------------------------------------------------------------
# Manual test
# ---------------------------------------------------------------------------

def main() -> None:
    """Preview and manually approve the Instagram test post."""
    try:
        validate_configuration()

        direct_image_url = build_google_drive_download_url(
            GOOGLE_DRIVE_IMAGE_URL
        )

    except (
        InstagramPublishError,
        GoogleDriveImageError,
    ) as error:
        print(
            f"\nInstagram test configuration error:\n{error}"
        )
        return

    print("\n" + "=" * 60)
    print("INSTAGRAM TEST POST")
    print("=" * 60)
    print(HARDCODED_CAPTION)
    print("\nGoogle Drive sharing link:")
    print(GOOGLE_DRIVE_IMAGE_URL)
    print("\nConverted image URL:")
    print(direct_image_url)
    print("=" * 60)

    confirmation = input(
        "\nPost this to TT's real Instagram account? "
        "Type 'yes' to confirm: "
    ).strip().lower()

    if confirmation != "yes":
        print("\nInstagram post cancelled.")
        return

    try:
        response_body = post_to_instagram(
            caption=HARDCODED_CAPTION,
            google_drive_share_url=GOOGLE_DRIVE_IMAGE_URL,
        )

    except GoogleDriveImageError as error:
        print(
            f"\nGoogle Drive image error:\n{error}"
        )
        return

    except InstagramSecretError as error:
        print(
            f"\nSecret Manager error:\n{error}"
        )
        return

    except InstagramAuthenticationError as error:
        print(
            f"\nInstagram authentication error:\n{error}"
        )
        return

    except InstagramPermissionError as error:
        print(
            f"\nInstagram permission error:\n{error}"
        )
        return

    except InstagramPublishError as error:
        print(
            f"\nInstagram publishing error:\n{error}"
        )
        return

    except Exception as error:
        print(
            "\nUnexpected Instagram test error.\n"
            f"Error type: {type(error).__name__}\n"
            f"Error: {error}"
        )
        return

    media_id = response_body.get("id")

    print(
        "\nInstagram post published successfully."
    )

    if media_id:
        print(
            f"Instagram media ID: {media_id}"
        )


if __name__ == "__main__":
    main()