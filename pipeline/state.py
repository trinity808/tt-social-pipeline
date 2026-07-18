import json

from pydantic import BaseModel, Field


class LinkedInDraft(BaseModel):
    caption: str = Field(..., max_length=3000)
    hashtags: list[str]


class InstagramDraft(BaseModel):
    caption: str = Field(..., max_length=2200)
    hashtags: list[str]


class FacebookDraft(BaseModel):
    caption: str = Field(..., max_length=5000)
    hashtags: list[str]


class SocialPostDraft(BaseModel):
    linkedin: LinkedInDraft
    instagram: InstagramDraft
    facebook: FacebookDraft


def parse_draft(raw: str) -> SocialPostDraft:
    raw = raw.strip()

    # Defensive: strip markdown code fences in case a model wraps JSON
    # in ```json ... ``` despite being told not to add anything else.
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    parsed = json.loads(raw)  # let this raise on malformed JSON, don't hide it
    return SocialPostDraft(**parsed)  # let this raise on schema mismatch, don't hide it