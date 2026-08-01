"""
Manual Instagram publisher test.

Skips the LangGraph pipeline, LLM calls, critic calls, and image
generation. Selects the newest existing image from generated_images/,
displays a preview, and only publishes after explicit confirmation.

Run from the repository root: python -m scripts.test_instagram_publisher
"""

from pathlib import Path

from pipeline.meta_errors import (
    MetaAuthenticationError,
    MetaPermissionError,
    MetaPublishError,
    MetaRateLimitError,
    MetaTemporaryError,
)
from pipeline.secrets import SecretAccessError
from publishers.instagram import publish_to_instagram

IMAGE_DIR = Path("generated_images")
SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

TEST_CAPTION = "This is a test post from Trinity Tree's new pipeline. Please ignore."
TEST_HASHTAGS = ["TrinityTreePsychServices", "MentalHealth", "GlendaleAZ"]


def find_test_image() -> Path:
    """Return the newest supported image in generated_images/."""
    if not IMAGE_DIR.is_dir():
        raise FileNotFoundError(f"'{IMAGE_DIR}' directory not found -- run from the repo root.")

    images = [
        p for p in IMAGE_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    ]

    if not images:
        raise FileNotFoundError(f"No supported images found in '{IMAGE_DIR}'.")

    return max(images, key=lambda p: p.stat().st_mtime).resolve()


def main() -> None:
    try:
        image_path = find_test_image()
    except FileNotFoundError as error:
        print(f"\nInstagram test setup failed:\n{error}")
        return

    print("\n" + "=" * 60)
    print("INSTAGRAM TEST POST PREVIEW")
    print("=" * 60)
    print(TEST_CAPTION)
    print(f"Hashtags: {TEST_HASHTAGS}")
    print(f"\nExisting image: {image_path}")
    print("=" * 60)

    confirmation = input(
        "\nPost this to TT's real Instagram account? Type 'yes' to confirm: "
    ).strip().lower()

    if confirmation != "yes":
        print("\nInstagram post cancelled.")
        return

    try:
        media_id = publish_to_instagram(
            caption=TEST_CAPTION,
            hashtags=TEST_HASHTAGS,
            image_path=image_path,
        )
    except SecretAccessError as error:
        print(f"\nSecret Manager error:\n{error}")
        return
    except MetaAuthenticationError as error:
        print(f"\nInstagram authentication error:\n{error}")
        return
    except MetaPermissionError as error:
        print(f"\nInstagram permission error:\n{error}")
        return
    except MetaRateLimitError as error:
        print(f"\nInstagram rate-limit error:\n{error}")
        return
    except MetaTemporaryError as error:
        print(f"\nTemporary Instagram error:\n{error}")
        return
    except MetaPublishError as error:
        print(f"\nInstagram publishing error:\n{error}")
        return
    except Exception as error:
        print(f"\nUnexpected Instagram test error.\nError type: {type(error).__name__}\nError: {error}")
        return

    print("\nInstagram publishing test completed.")
    print(f"Media ID: {media_id}")


if __name__ == "__main__":
    main()