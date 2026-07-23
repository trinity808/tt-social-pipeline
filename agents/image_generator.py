"""Generate a social-media image from approved website content."""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

OUTPUT_DIRECTORY = Path("generated_images")


def build_image_prompt(
    topic_key: str,
    topic_content: str,
    caption: str,
) -> str:
    """Build a controlled visual prompt grounded in the source content."""

    source_excerpt = " ".join(topic_content.split())[:3500]
    caption_excerpt = " ".join(caption.split())[:1000]

    return f"""
Create one professional square social-media image for
Trinity Tree Psychological Services, a clinical psychology practice
in Glendale, Arizona.

Topic:
{topic_key}

Approved website information:
{source_excerpt}

Related social-media caption:
{caption_excerpt}

Visual requirements:
- Clean, warm, calm, modern, and trustworthy.
- Suitable for a professional mental-health practice.
- Use an abstract or gently illustrated visual concept related to the topic.
- Use diverse, inclusive visual symbolism when people are relevant.
- Do not show identifiable real people.
- Do not depict distress, medical emergencies, medications, restraints,
  diagnoses, or treatment outcomes.
- Do not invent services or claims not supported by the supplied content.
- Do not include paragraphs, phone numbers, URLs, hashtags, or logos.
- Do not place text in the image.
- Avoid a generic therapy-room scene.
- Use balanced composition with sufficient negative space.
""".strip()


def generate_post_image(
    topic_key: str,
    topic_content: str,
    caption: str,
) -> str:
    """Generate one image, save it locally, and return its path."""

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing from the environment."
        )

    model = os.getenv(
        "OPENAI_IMAGE_MODEL",
        "gpt-image-2",
    )

    client = OpenAI(api_key=api_key)

    prompt = build_image_prompt(
        topic_key=topic_key,
        topic_content=topic_content,
        caption=caption,
    )

    response = client.images.generate(
        model=model,
        prompt=prompt,
        size="1024x1024",
        quality="medium",
    )

    image_base64 = response.data[0].b64_json

    if not image_base64:
        raise RuntimeError(
            "The image API returned no image data."
        )

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    safe_topic = re.sub(
        r"[^a-zA-Z0-9_-]+",
        "_",
        topic_key,
    ).strip("_")

    image_path = (
        OUTPUT_DIRECTORY
        / f"{safe_topic}_{uuid4().hex[:8]}.png"
    )

    image_path.write_bytes(
        base64.b64decode(image_base64)
    )

    return str(image_path)