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

from pipeline.graph import build_graph


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

# Non-secret configuration values are loaded from .env.
# Using os.getenv() prevents the module from crashing with KeyError
# before main() can provide a readable error message.
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "").strip()
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID", "").strip()

# Keep the Graph API version currently used by the project.
GRAPH_API_VERSION = "v25.0"

# Existing GCP Secret Manager secret containing the Page access token.
META_ACCESS_TOKEN_SECRET_ID = "meta-access-token"

REQUEST_TIMEOUT_SECONDS = 120


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class FacebookPublishError(RuntimeError):
    """Raised when Facebook rejects or cannot complete a post."""


class FacebookAuthenticationError(FacebookPublishError):
    """Raised when the Facebook access token is invalid or expired."""


class FacebookPermissionError(FacebookPublishError):
    """Raised when the token lacks permission to publish to the Page."""


class FacebookRateLimitError(FacebookPublishError):
    """Raised when Meta rate-limits the publishing request."""


class FacebookTemporaryError(FacebookPublishError):
    """Raised when Meta has a temporary server-side failure."""


class FacebookSecretError(RuntimeError):
    """Raised when the token cannot be read from Secret Manager."""


class PipelineExecutionError(RuntimeError):
    """Raised when the social-media graph cannot complete."""


class PipelineOutputError(RuntimeError):
    """Raised when the graph returns incomplete or invalid output."""


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------

def _validate_configuration() -> None:
    """Validate required non-secret configuration values."""
    missing_values: list[str] = []

    if not GCP_PROJECT_ID:
        missing_values.append("GCP_PROJECT_ID")

    if not FACEBOOK_PAGE_ID:
        missing_values.append("FACEBOOK_PAGE_ID")

    if missing_values:
        missing_text = ", ".join(missing_values)

        raise FacebookPublishError(
            "Missing required configuration value(s): "
            f"{missing_text}.\n"
            "Add them to the project .env file."
        )

    if not GRAPH_API_VERSION.startswith("v"):
        raise FacebookPublishError(
            "GRAPH_API_VERSION must begin with 'v', "
            f"for example 'v25.0'. Current value: "
            f"'{GRAPH_API_VERSION}'."
        )


# ---------------------------------------------------------------------------
# 1. Google Secret Manager error handling
# ---------------------------------------------------------------------------

def _get_secret(secret_id: str) -> str:
    """
    Read the latest enabled value from Google Secret Manager.

    This function only reads the secret. It does not create, rotate,
    update, or write secret versions.
    """
    if not GCP_PROJECT_ID:
        raise FacebookSecretError(
            "GCP_PROJECT_ID is missing. Add it to the .env file."
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
            "Google Cloud application-default credentials were not "
            "found.\n"
            "For local testing, run:\n"
            "gcloud auth application-default login"
        ) from error

    except NotFound as error:
        raise FacebookSecretError(
            f"Secret Manager could not find '{secret_id}' in "
            f"GCP project '{GCP_PROJECT_ID}'.\n"
            "Confirm the project ID, secret name, and that the secret "
            "has at least one enabled version."
        ) from error

    except PermissionDenied as error:
        raise FacebookSecretError(
            f"Permission was denied while reading '{secret_id}'.\n"
            "The active Google account or service account needs the "
            "Secret Manager Secret Accessor role."
        ) from error

    except FailedPrecondition as error:
        raise FacebookSecretError(
            f"The secret '{secret_id}' exists, but its latest version "
            "may be disabled, destroyed, or otherwise unavailable."
        ) from error

    except (DeadlineExceeded, ServiceUnavailable) as error:
        raise FacebookSecretError(
            "Google Secret Manager is temporarily unavailable or the "
            "request timed out. Try the request again."
        ) from error

    except GoogleAPIError as error:
        raise FacebookSecretError(
            f"An unexpected Google Cloud error occurred while reading "
            f"'{secret_id}': {error}"
        ) from error

    try:
        secret_value = response.payload.data.decode("UTF-8").strip()
    except UnicodeDecodeError as error:
        raise FacebookSecretError(
            f"The secret '{secret_id}' could not be decoded as UTF-8."
        ) from error

    if not secret_value:
        raise FacebookSecretError(
            f"The GCP Secret Manager secret '{secret_id}' is empty."
        )

    return secret_value


# ---------------------------------------------------------------------------
# Facebook caption formatting
# ---------------------------------------------------------------------------

def format_caption(
    caption: str,
    hashtags: Sequence[str] | None = None,
) -> str:
    """
    Combine the Facebook caption and hashtags.

    Hashtags are normalized to begin with # and contain no spaces.
    """
    clean_caption = caption.strip()
    formatted_hashtags: list[str] = []

    for raw_hashtag in hashtags or []:
        hashtag = str(raw_hashtag).strip()

        if not hashtag:
            continue

        hashtag = hashtag.replace(" ", "")

        if not hashtag.startswith("#"):
            hashtag = f"#{hashtag}"

        formatted_hashtags.append(hashtag)

    hashtag_text = " ".join(formatted_hashtags)

    if clean_caption and hashtag_text:
        return f"{clean_caption}\n\n{hashtag_text}"

    return clean_caption or hashtag_text


# ---------------------------------------------------------------------------
# 2. Meta API response and authentication error handling
# ---------------------------------------------------------------------------

def _parse_facebook_response(
    response: requests.Response,
) -> dict:
    """
    Parse Meta's response and classify common publishing failures.
    """
    try:
        response_body = response.json()
    except ValueError:
        response_body = {
            "raw_response": response.text,
        }

    error_details: dict = {}

    if isinstance(response_body, dict):
        possible_error = response_body.get("error", {})

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

    # Meta commonly uses code 190 for invalid or expired tokens.
    # Code 102 can indicate an invalid or expired session.
    authentication_failed = (
        response.status_code == 401
        or normalized_error_code in {102, 190}
    )

    if authentication_failed:
        raise FacebookAuthenticationError(
            "Facebook authentication failed. The access token stored "
            f"in Secret Manager as '{META_ACCESS_TOKEN_SECRET_ID}' "
            "may be invalid or expired.\n"
            f"HTTP status: {response.status_code}\n"
            f"Error type: {error_type}\n"
            f"Error code: {error_code}\n"
            f"Error subcode: {error_subcode}\n"
            f"Meta message: {error_message}"
        )

    if response.status_code == 403:
        raise FacebookPermissionError(
            "Facebook denied permission to publish to the Page.\n"
            "Confirm that the Page access token belongs to the correct "
            "Page and includes the required Page-posting permissions.\n"
            f"Error code: {error_code}\n"
            f"Error subcode: {error_subcode}\n"
            f"Meta message: {error_message}"
        )

    if response.status_code == 429:
        raise FacebookRateLimitError(
            "Meta rate-limited the Facebook publishing request.\n"
            "Do not immediately repeat the request many times.\n"
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
# 3. Image validation and 4. Network error handling
# ---------------------------------------------------------------------------

def post_to_facebook(
    caption: str,
    hashtags: Sequence[str],
    image_path: str | Path,
) -> dict:
    """
    Upload the generated image and publish it to Facebook.

    The Page access token is retrieved from Google Secret Manager.
    """
    _validate_configuration()

    if not caption.strip():
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
            f"The generated image path is invalid: {image_path}"
        ) from error

    if not resolved_image_path.exists():
        raise FileNotFoundError(
            f"Generated Facebook image does not exist: "
            f"{resolved_image_path}"
        )

    if not resolved_image_path.is_file():
        raise FacebookPublishError(
            "The generated image path does not point to a file: "
            f"{resolved_image_path}"
        )

    access_token = _get_secret(
        META_ACCESS_TOKEN_SECRET_ID
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
        f"\n[facebook] Uploading generated image: "
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
                    )
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

    except PermissionError as error:
        raise FacebookPublishError(
            "Permission was denied while opening the generated image: "
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
            "Check the internet connection and try again."
        ) from error

    except requests.RequestException as error:
        raise FacebookPublishError(
            f"The Facebook HTTP request failed: {error}"
        ) from error

    except OSError as error:
        raise FacebookPublishError(
            "The generated image could not be opened or read.\n"
            f"Image: {resolved_image_path}\n"
            f"Error: {error}"
        ) from error

    response_body = _parse_facebook_response(response)

    print("\n[facebook] Post published successfully.")

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


# ---------------------------------------------------------------------------
# 5. Full pipeline execution and final error handling
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Run the social pipeline, automatically use the generated image,
    preview the Facebook post, and publish after confirmation.
    """
    print(
        "\nStarting Trinity Tree social-media pipeline...\n"
    )

    # ---------------------------------------------------------------
    # Graph execution error handling
    # ---------------------------------------------------------------

    try:
        _validate_configuration()
        app = build_graph()
        result = app.invoke({})

    except FacebookPublishError as error:
        print(
            f"\nConfiguration error:\n{error}"
        )
        return

    except Exception as error:
        print(
            "\nThe social-media pipeline failed before Facebook "
            "publishing.\n"
            f"Error type: {type(error).__name__}\n"
            f"Error: {error}"
        )
        return

    # ---------------------------------------------------------------
    # Graph-output validation
    # ---------------------------------------------------------------

    if not isinstance(result, dict):
        print(
            "\nFacebook publishing stopped: the graph returned an "
            f"unexpected result type: {type(result).__name__}."
        )
        return

    final_draft = result.get("draft")

    if final_draft is None:
        print(
            "\nFacebook publishing stopped: the graph did not "
            "return a draft."
        )
        return

    facebook_draft = getattr(
        final_draft,
        "facebook",
        None,
    )

    if facebook_draft is None:
        print(
            "\nFacebook publishing stopped: the graph did not "
            "return a Facebook draft."
        )
        return

    caption = getattr(
        facebook_draft,
        "caption",
        "",
    )

    hashtags = getattr(
        facebook_draft,
        "hashtags",
        [],
    )

    if not isinstance(caption, str) or not caption.strip():
        print(
            "\nFacebook publishing stopped: the Facebook draft "
            "does not contain a valid caption."
        )
        return

    if hashtags is None:
        hashtags = []

    raw_image_path = result.get("image_path")

    if not raw_image_path:
        print(
            "\nFacebook publishing stopped: the graph did not "
            "return an image_path."
        )
        return

    try:
        image_path = Path(
            raw_image_path
        ).expanduser().resolve()
    except (TypeError, ValueError, OSError) as error:
        print(
            "\nFacebook publishing stopped: the graph returned an "
            "invalid image path.\n"
            f"Image path: {raw_image_path}\n"
            f"Error: {error}"
        )
        return

    if not image_path.exists():
        print(
            "\nFacebook publishing stopped: the generated image "
            "does not exist.\n"
            f"Image path: {image_path}"
        )
        return

    if not image_path.is_file():
        print(
            "\nFacebook publishing stopped: the generated image "
            "path is not a file.\n"
            f"Image path: {image_path}"
        )
        return

    message = format_caption(
        caption=caption,
        hashtags=hashtags,
    )

    print("\n" + "=" * 60)
    print("FACEBOOK POST PREVIEW")
    print("=" * 60)
    print(message)
    print(f"\nGenerated image: {image_path}")

    verdict = result.get("verdict")

    if verdict is not None:
        facebook_verdict = getattr(
            verdict,
            "facebook",
            None,
        )

        if facebook_verdict is not None:
            approved = getattr(
                facebook_verdict,
                "approved",
                "Unknown",
            )

            reason = getattr(
                facebook_verdict,
                "reason",
                "No feedback returned.",
            )

            print(
                f"\nCritic approved: {approved}"
            )
            print(
                f"Critic feedback: {reason}"
            )

    print(
        f"Retries used: "
        f"{result.get('retry_count', 0)}"
    )
    print("=" * 60)

    confirmation = input(
        "\nPost this to TT's real Facebook page? "
        "Type 'yes' to confirm: "
    ).strip().lower()

    if confirmation != "yes":
        print("\nFacebook post cancelled.")
        return

    # ---------------------------------------------------------------
    # Specific final exception handling
    # ---------------------------------------------------------------

    try:
        response_body = post_to_facebook(
            caption=caption,
            hashtags=hashtags,
            image_path=image_path,
        )

    except FacebookSecretError as error:
        print(
            f"\nSecret Manager error:\n{error}"
        )
        return

    except FacebookAuthenticationError as error:
        print(
            f"\nFacebook authentication error:\n{error}"
        )
        return

    except FacebookPermissionError as error:
        print(
            f"\nFacebook permission error:\n{error}"
        )
        return

    except FacebookRateLimitError as error:
        print(
            f"\nFacebook rate-limit error:\n{error}"
        )
        return

    except FacebookTemporaryError as error:
        print(
            f"\nTemporary Facebook error:\n{error}"
        )
        return

    except FileNotFoundError as error:
        print(
            f"\nGenerated-image error:\n{error}"
        )
        return

    except FacebookPublishError as error:
        print(
            f"\nFacebook publishing error:\n{error}"
        )
        return

    except Exception as error:
        print(
            "\nAn unexpected Facebook publishing error occurred.\n"
            f"Error type: {type(error).__name__}\n"
            f"Error: {error}"
        )
        return

    print(
        "\nFacebook publishing process completed."
    )

    if response_body.get("post_id"):
        print(
            f"Post ID: {response_body['post_id']}"
        )

    if response_body.get("id"):
        print(
            f"Facebook ID: {response_body['id']}"
        )


if __name__ == "__main__":
    main()