import json

from typing import Optional, TypedDict,NotRequired,TypeVar
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


class PlatformVerdict(BaseModel):
    approved: bool
    reason: str


class CriticVerdict(BaseModel):
    linkedin: PlatformVerdict
    instagram: PlatformVerdict
    facebook: PlatformVerdict


ModelT = TypeVar("ModelT", bound=BaseModel)


def parse_model(raw: str, model_cls: type[ModelT]) -> ModelT:
    """Generic over SocialPostDraft, CriticVerdict, or any future schema --
    both the writer and critic need identical JSON-extraction handling, so
    this replaces what used to be a SocialPostDraft-only parse_draft()."""
    raw = raw.strip()

    # Defensive: strip markdown code fences in case a model wraps JSON
    # in ```json ... ``` despite being told not to add anything else.
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    parsed = json.loads(raw)  # let this raise on malformed JSON, don't hide it
    return model_cls(**parsed)  # let this raise on schema mismatch, don't hide it


class PipelineState(TypedDict):
    """Shared state passed between LangGraph nodes. Each node returns only
    the keys it's updating -- LangGraph merges them into the running state,
    it's not a full-object replacement the way SocialPostDraft is."""
    topic_key: str
    topic_content: str
    draft: Optional[SocialPostDraft]
    verdict: Optional[CriticVerdict]
    retry_count: int
    image_prompt: NotRequired[str]
    image_path: NotRequired[str]

