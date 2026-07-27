"""
Production LinkedIn publisher: posts an approved caption + image, handling
token refresh automatically so this can run unattended on a schedule.
"""

import mimetypes
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv
from google.cloud import firestore, secretmanager

load_dotenv()

GCP_PROJECT_ID = os.environ["GCP_PROJECT_ID"]
ORG_URN_VALUE = os.environ["LINKEDIN_ORG_URN"].strip()

POST_URL = "https://api.linkedin.com/rest/posts"
IMAGE_URL = "https://api.linkedin.com/rest/images"
LINKEDIN_VERSION = os.getenv("LINKEDIN_VERSION", "202606").strip()

REFRESH_MARGIN_DAYS = 7  # proactively refresh if within this many days of expiry

SECRET_ACCESS_TOKEN_ID = "linkedin-access-token"
SECRET_REFRESH_TOKEN_ID = "linkedin-refresh-token"

secret_client = secretmanager.SecretManagerServiceClient()
db = firestore.Client(project=GCP_PROJECT_ID)
TOKEN_META_DOC = db.collection("linkedin_auth").document("token_meta")


# --- Secret Manager helpers ---

def _get_secret(secret_id: str) -> str:
    name = f"projects/{GCP_PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = secret_client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


def _set_secret(secret_id: str, value: str) -> None:
    parent = f"projects/{GCP_PROJECT_ID}/secrets/{secret_id}"
    secret_client.add_secret_version(
        request={
            "parent": parent,
            "payload": {"data": value.encode("UTF-8")},
        }
    )


# --- Ported from Sukanya's manual test script, unchanged in logic ---

def get_organization_urn() -> str:
    """Accepts either a bare numeric ID or a full urn:li:organization:... value."""
    if ORG_URN_VALUE.startswith("urn:li:organization:"):
        return ORG_URN_VALUE
    if ORG_URN_VALUE.isdigit():
        return f"urn:li:organization:{ORG_URN_VALUE}"
    raise ValueError(
        "LINKEDIN_ORG_URN must be a numeric organization ID "
        "or a complete urn:li:organization:... value."
    )


ORG_URN = get_organization_urn()


def format_caption(caption: str, hashtags: list[str]) -> str:
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

    return f"{caption.strip()}\n\n{' '.join(formatted_hashtags)}"


def _get_api_headers(access_token: str, include_content_type: bool = False) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }
    if include_content_type:
        headers["Content-Type"] = "application/json"
    return headers


def upload_image_to_linkedin(access_token: str, image_path: str | Path) -> str:
    """Uploads an image to LinkedIn and returns the resulting image URN.

    NOTE: access_token is now a parameter, not a module-level constant like
    in the manual test script -- this function may run after a refresh, and
    must never hold onto a stale token value.
    """
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"Generated image was not found: {path}")

    init_response = requests.post(
        f"{IMAGE_URL}?action=initializeUpload",
        headers=_get_api_headers(access_token, include_content_type=True),
        json={"initializeUploadRequest": {"owner": ORG_URN}},
        timeout=30,
    )
    init_response.raise_for_status()

    init_body = init_response.json()
    upload_data = init_body.get("value", {})
    upload_url = upload_data.get("uploadUrl")
    image_urn = upload_data.get("image")

    if not upload_url or not image_urn:
        raise RuntimeError(f"LinkedIn did not return an upload URL and image URN. Response: {init_body}")

    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with path.open("rb") as image_file:
        upload_response = requests.put(
            upload_url,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": content_type},
            data=image_file,
            timeout=120,
        )
    upload_response.raise_for_status()

    encoded_image_urn = quote(image_urn, safe="")
    status_url = f"{IMAGE_URL}/{encoded_image_urn}"

    for attempt in range(1, 61):
        status_response = requests.get(status_url, headers=_get_api_headers(access_token), timeout=30)
        status_response.raise_for_status()
        status_body = status_response.json()
        status = status_body.get("status")

        if status == "AVAILABLE":
            return image_urn
        if status == "PROCESSING_FAILED":
            raise RuntimeError(f"LinkedIn failed to process the image. Response: {status_body}")
        if status not in {"WAITING_UPLOAD", "PROCESSING"}:
            raise RuntimeError(f"LinkedIn returned an unexpected image status. Response: {status_body}")

        time.sleep(2)

    raise TimeoutError("LinkedIn image did not become AVAILABLE within 120 seconds.")


# --- New: token refresh and lifecycle management ---
 
REFRESH_URL = "https://www.linkedin.com/oauth/v2/accessToken"
 
 
def _handle_refresh_failure(reason: str) -> None:
    """Called when the refresh call itself fails, for any reason -- a bad
    status code or a network-level exception. Soft-fails (logs and returns)
    if the current access token is still within its known expiry; hard-fails
    only if there's truly no valid token left to fall back on."""
    doc = TOKEN_META_DOC.get()
    access_expires_at = doc.to_dict().get("access_token_expires_at") if doc.exists else None
 
    if access_expires_at and access_expires_at > datetime.now(timezone.utc):
        print(
            f"[linkedin] WARNING: token refresh failed ({reason}), "
            f"but current access token is still valid until {access_expires_at}. Continuing."
        )
        return
 
    raise RuntimeError(
        f"LinkedIn token refresh failed ({reason}) and no valid access token remains."
    )
 
 
def refresh_access_token() -> None:
    """Calls LinkedIn's refresh grant endpoint, writes the new access token
    (and new refresh token, if issued) to Secret Manager, and updates both
    expiry timestamps in Firestore."""
    current_refresh_token = _get_secret(SECRET_REFRESH_TOKEN_ID)
    client_id = os.environ["LINKEDIN_CLIENT_ID"]
    client_secret = _get_secret("linkedin-client-secret")
 
    try:
        response = requests.post(
            REFRESH_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": current_refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=30,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        _handle_refresh_failure(reason=str(e))
        return
 
    body = response.json()
    now = datetime.now(timezone.utc)
 
    new_access_token = body["access_token"]
    access_expires_at = now + timedelta(seconds=body["expires_in"])
    _set_secret(SECRET_ACCESS_TOKEN_ID, new_access_token)
 
    update_fields = {"access_token_expires_at": access_expires_at}
 
    # LinkedIn only returns a new refresh token if the app has programmatic
    # refresh access -- if it's absent here, the existing refresh token (and
    # its own expiry) is still current and shouldn't be touched.
    new_refresh_token = body.get("refresh_token")
    if new_refresh_token:
        _set_secret(SECRET_REFRESH_TOKEN_ID, new_refresh_token)
        refresh_expires_in = body.get("refresh_token_expires_in")
        if refresh_expires_in is not None:
            update_fields["refresh_token_expires_at"] = now + timedelta(seconds=refresh_expires_in)
 
    TOKEN_META_DOC.set(update_fields, merge=True)
    print("[linkedin] access token refreshed successfully.")
 
 
def get_valid_access_token() -> str:
    """Entry point every post should call first. Returns a token guaranteed
    to be usable, refreshing proactively if within REFRESH_MARGIN_DAYS of
    expiry -- or if no expiry is tracked yet at all."""
    doc = TOKEN_META_DOC.get()
    access_expires_at = doc.to_dict().get("access_token_expires_at") if doc.exists else None

    refresh_cutoff = datetime.now(timezone.utc) + timedelta(days=REFRESH_MARGIN_DAYS)

    if access_expires_at is None or access_expires_at < refresh_cutoff:
        print(
            "[linkedin] access token missing tracked expiry or within "
            f"{REFRESH_MARGIN_DAYS}-day refresh margin -- refreshing now."
        )
        refresh_access_token()

    return _get_secret(SECRET_ACCESS_TOKEN_ID)


# --- New: the actual module entry point ---

def post_to_linkedin(caption: str, hashtags: list[str], image_path: str | Path) -> str:
    """Posts an approved caption + image to LinkedIn. Returns the post URN."""
    access_token = get_valid_access_token()
    formatted_caption = format_caption(caption, hashtags)
    image_urn = upload_image_to_linkedin(access_token, image_path)

    payload = {
        "author": ORG_URN,
        "commentary": formatted_caption,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "content": {
            "media": {
                "id": image_urn,
                "altText": "Trinity Tree Psychological Services social media graphic",
            }
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    response = requests.post(
        POST_URL,
        headers=_get_api_headers(access_token, include_content_type=True),
        json=payload,
        timeout=30,
    )

    if response.status_code != 201:
        raise RuntimeError(f"LinkedIn post failed -- status {response.status_code}: {response.text}")

    post_urn = response.headers.get("x-restli-id")
    print(f"[linkedin] posted successfully. Post URN: {post_urn}")
    return post_urn