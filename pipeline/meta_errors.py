"""
Shared Meta Graph API error classification, used by both the Facebook and
Instagram publishers -- they're the same underlying API (graph.facebook.com)
with the same error response shape, unlike LinkedIn's genuinely different
API. Originally written for the Facebook publisher, consolidated here once
Instagram needed identical error handling rather than a fourth custom
version.
"""

import requests


class MetaPublishError(RuntimeError):
    """Raised when Meta rejects or cannot complete a Facebook or Instagram post."""


class MetaAuthenticationError(MetaPublishError):
    """Raised when the Meta access token is invalid or expired."""


class MetaPermissionError(MetaPublishError):
    """Raised when the token lacks permission to publish."""


class MetaRateLimitError(MetaPublishError):
    """Raised when Meta rate-limits the request."""


class MetaTemporaryError(MetaPublishError):
    """Raised when Meta or the network has a temporary failure."""


def parse_meta_response(response: requests.Response) -> dict:
    """Parse a Meta Graph API response and classify common failures."""
    try:
        response_body = response.json()
    except ValueError:
        response_body = {"raw_response": response.text}

    error_details: dict = {}
    if isinstance(response_body, dict):
        possible_error = response_body.get("error", {})
        if isinstance(possible_error, dict):
            error_details = possible_error

    error_code = error_details.get("code")
    error_subcode = error_details.get("error_subcode")
    error_type = error_details.get("type")
    error_message = error_details.get("message", "Meta rejected the request.")

    try:
        normalized_error_code = int(error_code) if error_code is not None else None
    except (TypeError, ValueError):
        normalized_error_code = None

    authentication_failed = response.status_code == 401 or normalized_error_code in {102, 190}

    if authentication_failed:
        raise MetaAuthenticationError(
            "Meta authentication failed. The access token stored as "
            "'meta-access-token' in Secret Manager may be invalid or expired.\n"
            f"HTTP status: {response.status_code}\n"
            f"Error type: {error_type}\n"
            f"Error code: {error_code}\n"
            f"Error subcode: {error_subcode}\n"
            f"Meta message: {error_message}"
        )

    if response.status_code == 403:
        raise MetaPermissionError(
            "Meta denied permission to publish.\n"
            "Confirm the access token has posting permission for this asset.\n"
            f"Error code: {error_code}\n"
            f"Error subcode: {error_subcode}\n"
            f"Meta message: {error_message}"
        )

    if response.status_code == 429:
        raise MetaRateLimitError(f"Meta rate-limited the request.\nMeta message: {error_message}")

    if 500 <= response.status_code < 600:
        raise MetaTemporaryError(
            f"Meta returned a temporary server error.\n"
            f"HTTP status: {response.status_code}\n"
            f"Meta message: {error_message}"
        )

    if not response.ok:
        raise MetaPublishError(
            f"Meta publishing failed.\n"
            f"HTTP status: {response.status_code}\n"
            f"Error type: {error_type}\n"
            f"Error code: {error_code}\n"
            f"Error subcode: {error_subcode}\n"
            f"Meta message: {error_message}\n"
            f"Full response: {response_body}"
        )

    if not isinstance(response_body, dict):
        return {"response": response_body}

    return response_body