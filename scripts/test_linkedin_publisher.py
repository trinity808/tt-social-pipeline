"""
One-time manual test: confirms the new publishers.linkedin module can
actually post for real, using genuine tokens from Secret Manager (not .env).

Uses a hardcoded caption and the first image found in generated_images/ --
no LLM calls, no graph. Isolates the publisher module itself, including its
internal get_valid_access_token() call (which will check the real expiry
just written to Firestore, and should NOT trigger another refresh since one
just happened).

Run from the repo root: python -m scripts.test_linkedin_publisher
"""

from pathlib import Path

from publishers.linkedin import post_to_linkedin

IMAGE_DIR = Path("generated_images")

HARDCODED_CAPTION = "This is a test post from Trinity Tree's new pipeline. Please ignore."


def find_test_image() -> Path:
    images = sorted(
        p for p in IMAGE_DIR.iterdir()
        if p.suffix.lower() in {".png", ".jpg", ".jpeg"}
    )
    if not images:
        raise FileNotFoundError(f"No image files found in '{IMAGE_DIR}'.")
    return images[0]


if __name__ == "__main__":
    image_path = find_test_image()

    print("--- Caption to post ---")
    print(HARDCODED_CAPTION)
    print(f"--- Image: {image_path} ---\n")

    confirm = input(
        "Post this to TT's real LinkedIn page via the new publisher module? "
        "Type 'yes' to confirm: "
    ).strip().lower()

    if confirm == "yes":
        post_urn = post_to_linkedin(
            caption=HARDCODED_CAPTION,
            hashtags=[],
            image_path=image_path,
        )
        print(f"\nDone. Post URN: {post_urn}")
    else:
        print("Not posted.")