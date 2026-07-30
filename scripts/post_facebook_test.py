"""
Manual Facebook publisher test.

This script intentionally skips the LangGraph pipeline, LLM calls,
critic calls, and image generation. It selects the newest existing image
from generated_images/, displays a preview, and only publishes after an
explicit confirmation.

Run from the repository root:

    python -m scripts.post_facebook_test
"""

from __future__ import annotations

from pathlib import Path

from publishers.facebook import (
    FacebookAuthenticationError,
    FacebookPermissionError,
    FacebookPublishError,
    FacebookRateLimitError,
    FacebookSecretError,
    FacebookTemporaryError,
    format_caption,
    post_to_facebook,
)


# ---------------------------------------------------------------------------
# Test configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIR = PROJECT_ROOT / "generated_images"

SUPPORTED_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}

TEST_CAPTION = (
    "This is a test post from Trinity Tree's new social-media "
    "pipeline. Please ignore."
)

TEST_HASHTAGS = [
    "TrinityTreePsychServices",
    "MentalHealth",
    "GlendaleAZ",
]


# ---------------------------------------------------------------------------
# Test-image selection
# ---------------------------------------------------------------------------

def find_test_image() -> Path:
    """Return the newest supported image in generated_images/."""
    if not IMAGE_DIR.exists():
        raise FileNotFoundError(
            f"The image directory does not exist: {IMAGE_DIR}"
        )

    if not IMAGE_DIR.is_dir():
        raise FacebookPublishError(
            f"The image path is not a directory: {IMAGE_DIR}"
        )

    images = [
        image_path
        for image_path in IMAGE_DIR.iterdir()
        if (
            image_path.is_file()
            and image_path.suffix.lower()
            in SUPPORTED_IMAGE_EXTENSIONS
        )
    ]

    if not images:
        raise FileNotFoundError(
            "No supported images were found in:\n"
            f"{IMAGE_DIR}\n"
            "Supported formats: PNG, JPG, JPEG, and WEBP."
        )

    # Use the most recently modified image.
    return max(
        images,
        key=lambda path: path.stat().st_mtime,
    ).resolve()


# ---------------------------------------------------------------------------
# Manual test runner
# ---------------------------------------------------------------------------

def main() -> None:
    """Preview and manually approve one Facebook test post."""
    try:
        image_path = find_test_image()

    except (FileNotFoundError, FacebookPublishError) as error:
        print(
            f"\nFacebook test setup failed:\n{error}"
        )
        return

    except OSError as error:
        print(
            "\nFacebook test could not inspect generated_images/.\n"
            f"Error: {error}"
        )
        return

    preview = format_caption(
        caption=TEST_CAPTION,
        hashtags=TEST_HASHTAGS,
    )

    print("\n" + "=" * 60)
    print("FACEBOOK TEST POST PREVIEW")
    print("=" * 60)
    print(preview)
    print(f"\nExisting image: {image_path}")
    print("=" * 60)

    confirmation = input(
        "\nPost this to TT's real Facebook page? "
        "Type 'yes' to confirm: "
    ).strip().lower()

    if confirmation != "yes":
        print("\nFacebook post cancelled.")
        return

    try:
        response_body = post_to_facebook(
            caption=TEST_CAPTION,
            hashtags=TEST_HASHTAGS,
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
            f"\nImage error:\n{error}"
        )
        return

    except FacebookPublishError as error:
        print(
            f"\nFacebook publishing error:\n{error}"
        )
        return

    except Exception as error:
        print(
            "\nUnexpected Facebook test error.\n"
            f"Error type: {type(error).__name__}\n"
            f"Error: {error}"
        )
        return

    print(
        "\nFacebook publishing test completed."
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