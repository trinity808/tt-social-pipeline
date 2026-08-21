"""
Shared Cloud Storage helper. Originally lived in publishers/instagram.py --
Instagram was the first thing that needed a public image URL for a locally-
generated image. Relocated here once the review-gate email needed the same
capability, since this is a general "give me a public URL" utility, not
something specific to any one platform.
"""

import mimetypes
import os
import requests
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import storage

from pipeline.logging_config import get_logger

load_dotenv()

GCP_PROJECT_ID = os.environ["GCP_PROJECT_ID"]
GCS_BUCKET_NAME = "tt-social-pipeline-images"
LOCAL_IMAGE_DIR = Path("generated_images")

storage_client = storage.Client(project=GCP_PROJECT_ID)
logger = get_logger(__name__)


def upload_image_to_gcs(image_path: str | Path) -> str:
    """Uploads a local image to Cloud Storage and returns its public URL."""
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"Generated image was not found: {path}")

    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(path.name)

    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    blob.upload_from_filename(str(path), content_type=content_type)

    logger.info(f"image uploaded to Cloud Storage: {blob.public_url}")
    return blob.public_url

def download_image_for_publishing(image_url: str) -> Path:
    """Downloads the durable image back to a local file for publishing.
    The original local file from generate_image may no longer exist if
    the container was recycled during the review pause -- publisher
    functions all expect a local path, so this bridges that gap using the
    durable public URL rather than trusting the original file survived."""
    response = requests.get(image_url, timeout=30)
    response.raise_for_status()

    filename = image_url.rsplit("/", 1)[-1]
    LOCAL_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    local_path = LOCAL_IMAGE_DIR / filename

    local_path.write_bytes(response.content)
    logger.info(f"downloaded image for publishing: {local_path}")

    return local_path