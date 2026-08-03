"""
Shared Secret Manager access, used by all three publisher modules.
_get_secret originally written for the Facebook publisher, with real
exception handling for common failure modes -- consolidated here once
Instagram needed the identical logic rather than writing a third copy.
_set_secret was LinkedIn's, needed since it's the only publisher that
writes new token values back (during refresh).
"""

import os

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

load_dotenv()

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "").strip()

secret_client = secretmanager.SecretManagerServiceClient()


class SecretAccessError(RuntimeError):
    """Raised when a secret cannot be read from or written to Secret
    Manager. Named generically (not FacebookSecretError, its original
    name) now that LinkedIn and Instagram both depend on this too."""


def _get_secret(secret_id: str) -> str:
    """
    Read the latest enabled value from Google Secret Manager.

    This function only reads the secret. It does not create, rotate,
    update, or write secret versions.
    """
    if not GCP_PROJECT_ID:
        raise SecretAccessError(
            "GCP_PROJECT_ID is missing. Add it to the .env file."
        )

    secret_name = f"projects/{GCP_PROJECT_ID}/secrets/{secret_id}/versions/latest"

    try:
        response = secret_client.access_secret_version(request={"name": secret_name})

    except DefaultCredentialsError as error:
        raise SecretAccessError(
            "Google Cloud application-default credentials were not found.\n"
            "For local testing, run:\n"
            "gcloud auth application-default login"
        ) from error

    except NotFound as error:
        raise SecretAccessError(
            f"Secret Manager could not find '{secret_id}' in "
            f"GCP project '{GCP_PROJECT_ID}'.\n"
            "Confirm the project ID, secret name, and that the secret "
            "has at least one enabled version."
        ) from error

    except PermissionDenied as error:
        raise SecretAccessError(
            f"Permission was denied while reading '{secret_id}'.\n"
            "The active Google account or service account needs the "
            "Secret Manager Secret Accessor role."
        ) from error

    except FailedPrecondition as error:
        raise SecretAccessError(
            f"The secret '{secret_id}' exists, but its latest version "
            "may be disabled, destroyed, or otherwise unavailable."
        ) from error

    except (DeadlineExceeded, ServiceUnavailable) as error:
        raise SecretAccessError(
            "Google Secret Manager is temporarily unavailable or the "
            "request timed out. Try the request again."
        ) from error

    except GoogleAPIError as error:
        raise SecretAccessError(
            f"An unexpected Google Cloud error occurred while reading "
            f"'{secret_id}': {error}"
        ) from error

    try:
        secret_value = response.payload.data.decode("UTF-8").strip()
    except UnicodeDecodeError as error:
        raise SecretAccessError(f"The secret '{secret_id}' could not be decoded as UTF-8.") from error

    if not secret_value:
        raise SecretAccessError(f"The GCP Secret Manager secret '{secret_id}' is empty.")

    return secret_value


def _set_secret(secret_id: str, value: str) -> None:
    parent = f"projects/{GCP_PROJECT_ID}/secrets/{secret_id}"
    secret_client.add_secret_version(
        request={
            "parent": parent,
            "payload": {"data": value.encode("UTF-8")},
        }
    )