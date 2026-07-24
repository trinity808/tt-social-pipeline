from pipeline.state import CriticVerdict, SocialPostDraft
import random

# Stable facts true on every post regardless of topic -- shared across all
# three prompts so the critic isn't missing context the writer always has.
COMPANY_CONTEXT = "Trinity Tree Psychological Services is a clinical psychology practice based in Glendale, Arizona, providing evidence-based care for children, teens, and adults."

# Shared between the writer and revision prompts so a future format change
# (like the word-count fix) only needs updating in one place.
PLATFORM_RULES = """LinkedIn: Professional and warm. STRICTLY under 150 words. No hashtags -- return an empty hashtags array. End with a call to action directing readers to visit trinitytreepsych.com.

Instagram: Short and punchy. STRICTLY under 80 words. Exactly 5 hashtags, with at least one referencing Arizona or Glendale. Do not include any hashtags inside the caption text itself -- hashtags only go in the hashtags field, never in the caption. End the caption with "Link in bio to learn more."

Facebook: Friendly and conversational. STRICTLY between 100 and 120 words. Exactly 2-3 hashtags, with at least one referencing Arizona or Glendale. Do not include any hashtags inside the caption text itself -- hashtags only go in the hashtags field, never in the caption. End with a call to action directing readers to visit trinitytreepsych.com."""

RESPONSE_SHAPE = """Return ONLY valid JSON in exactly this shape, with no text before or after it:

{
  "linkedin": {"caption": "<string>", "hashtags": []},
  "instagram": {"caption": "<string>", "hashtags": ["<string>", "..."]},
  "facebook": {"caption": "<string>", "hashtags": ["<string>", "..."]}
}"""

CRITIC_RESPONSE_SHAPE = """Return ONLY valid JSON in exactly this shape, with no text before or after it:

{
  "linkedin": {"approved": true, "reason": "<string>"},
  "instagram": {"approved": true, "reason": "<string>"},
  "facebook": {"approved": true, "reason": "<string>"}
}"""


SYSTEM_PROMPT_TEMPLATE = """You are a social media copywriter for Trinity Tree Psychological Services.

{company_context}

Write one post about the topic below, adapted for each of three platforms. Write like an actual social media post -- short sentences, conversational -- not a brochure, blog, or a copy-pasted excerpt from a website.

TOPIC CONTENT (this is the source for anything specific to this post -- do not invent services, insurance plans, credentials, ages served, or any other detail not present in this text; general facts about the practice itself, like its name and location above, are already established and don't need to come from this text):
---
{topic_content}
---

Do not closely mirror this source text's own sentence structure or phrasing. Rewrite it in your own words as a social caption -- reusing the source's exact wording is a failure, even if the fact itself is accurate.

Tone: professional and warm. Avoid sounding clinical or cold, and avoid sounding like a marketing ad.

Each platform must read as genuinely distinct from the others -- not the same post resized to different lengths. Follow these platform requirements exactly; treat any violation as a failure:

{platform_rules}

{response_shape}
"""


def build_prompt(topic_content: str) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        company_context=COMPANY_CONTEXT,
        topic_content=topic_content,
        platform_rules=PLATFORM_RULES,
        response_shape=RESPONSE_SHAPE,
    )


CRITIC_PROMPT_TEMPLATE = """You are reviewing a set of social media captions for Trinity Tree Psychological Services before they are approved for posting.

{company_context}

Do NOT check word count, hashtag count, or hashtag placement -- those are already enforced separately and are guaranteed correct. Only judge what's below.

TOPIC CONTENT (the source for anything specific to this post -- general facts about the practice itself, like its name and location above, are already established and are NOT ungrounded just because they aren't repeated in this text):
---
{topic_content}
---

For each platform's caption below, check:
1. Factual grounding -- does every specific claim about the topic (credentials, services, conditions treated, insurance, etc.) trace back to the topic content above? The topic content is the primary authority for anything specific to this post. General knowledge about mental health/psychiatric practice is acceptable ONLY where it doesn't contradict or go beyond what the source states. Treat any invented, upgraded, or unsupported specific claim as a failure -- for example, upgrading "licensed" to "board-certified" when the source only says "licensed" is a failure, even though it sounds plausible. Do NOT flag the practice's own name, location, or general mission as ungrounded -- those are established facts above, not topic-specific claims that need sourcing.
2. Hashtag relevance -- are the hashtags actually relevant to this caption's content, not generic filler?
3. Tone fit -- professional and warm, not clinical/cold, not marketing hype.
4. Does it read like an actual social media post, not a brochure or a copy-pasted excerpt from the website?

DRAFT TO REVIEW:

LinkedIn:
Caption: {linkedin_caption}
Hashtags: {linkedin_hashtags}

Instagram:
Caption: {instagram_caption}
Hashtags: {instagram_hashtags}

Facebook:
Caption: {facebook_caption}
Hashtags: {facebook_hashtags}

For each platform, decide approved (true/false) and give a specific reason -- if rejecting, state exactly what's wrong (e.g. "invents an unstated 'board-certified' credential", not just "factual issue"). If approving, a brief reason is still required, not just "looks good".

{critic_response_shape}
"""


def build_critic_prompt(topic_content: str, draft: SocialPostDraft) -> str:
    return CRITIC_PROMPT_TEMPLATE.format(
        company_context=COMPANY_CONTEXT,
        topic_content=topic_content,
        linkedin_caption=draft.linkedin.caption,
        linkedin_hashtags=draft.linkedin.hashtags,
        instagram_caption=draft.instagram.caption,
        instagram_hashtags=draft.instagram.hashtags,
        facebook_caption=draft.facebook.caption,
        facebook_hashtags=draft.facebook.hashtags,
        critic_response_shape=CRITIC_RESPONSE_SHAPE,
    )


REVISION_PROMPT_TEMPLATE = """You are revising a set of social media captions for Trinity Tree Psychological Services, based on specific feedback from a review step. The previous attempt was rejected.

{company_context}

TOPIC CONTENT (this is the source for anything specific to this post -- do not invent services, insurance plans, credentials, ages served, or any other detail not present in this text; general facts about the practice itself, like its name and location above, are already established and don't need to come from this text):
---
{topic_content}
---

PREVIOUS DRAFT (for reference -- do not just resubmit this, actually fix the issues noted below):

LinkedIn: {linkedin_caption}
Instagram: {instagram_caption}
Facebook: {facebook_caption}

REVIEW FEEDBACK:
LinkedIn -- approved: {linkedin_approved}, reason: {linkedin_reason}
Instagram -- approved: {instagram_approved}, reason: {instagram_reason}
Facebook -- approved: {facebook_approved}, reason: {facebook_reason}

Produce a new, complete set of captions for all three platforms. Directly address every issue named in the feedback above. For any platform marked approved, you may keep the same overall approach, but you must still return a valid caption for it.

Tone: professional and warm. Avoid sounding clinical or cold, and avoid sounding like a marketing ad. Do not closely mirror the source text's own sentence structure or phrasing.

Platform requirements, unchanged from before -- treat any violation as a failure:

{platform_rules}

{response_shape}
"""


def build_revision_prompt(topic_content: str, previous_draft: SocialPostDraft, verdict: CriticVerdict) -> str:
    return REVISION_PROMPT_TEMPLATE.format(
        company_context=COMPANY_CONTEXT,
        topic_content=topic_content,
        linkedin_caption=previous_draft.linkedin.caption,
        instagram_caption=previous_draft.instagram.caption,
        facebook_caption=previous_draft.facebook.caption,
        linkedin_approved=verdict.linkedin.approved,
        linkedin_reason=verdict.linkedin.reason,
        instagram_approved=verdict.instagram.approved,
        instagram_reason=verdict.instagram.reason,
        facebook_approved=verdict.facebook.approved,
        facebook_reason=verdict.facebook.reason,
        platform_rules=PLATFORM_RULES,
        response_shape=RESPONSE_SHAPE,
    )

import random

IMAGE_STYLES = [
    "bold infographic with simple icons and clean layout",
    "clean minimalist poster with abstract geometric shapes",
    "typographic design with decorative geometric elements",
    "gentle illustrated scene with soft abstract shapes",
]

IMAGE_COLOR_PALETTES = [
    "warm earthy tones -- terracotta, cream, olive",
    "cool professional -- navy, white, soft blue",
    "bold high contrast -- deep teal, bright white, coral accent",
    "dark professional -- charcoal, gold, white",
]

IMAGE_PROMPT_TEMPLATE = """Create one professional square social-media image for Trinity Tree Psychological Services, a clinical psychology practice in Glendale, Arizona.

Topic:
{topic_key}

Approved website information:
{source_excerpt}

Related social-media caption:
{caption_excerpt}

Style: {style}
Color palette: {color_palette}

Visual requirements:
- Clean, warm, calm, modern, and trustworthy.
- Suitable for a professional mental-health practice.
- Include the text "Trinity Tree Psychological Services" visibly but subtly integrated into the design -- not as a large headline, not overlapping the main visual.
- Use diverse, inclusive visual symbolism when people are relevant.
- Do not show identifiable real people.
- Do not depict distress, medical emergencies, medications, restraints, diagnoses, or treatment outcomes.
- Do not invent services or claims not supported by the supplied content.
- Do not include any text other than the practice name above -- no additional slogans, phone numbers, URLs, hashtags, or invented quotes.
- Do not include logos.
- Avoid a generic therapy-room scene.
- Use balanced composition with sufficient negative space.
"""


def build_image_prompt(topic_key: str, topic_content: str, caption: str) -> str:
    source_excerpt = " ".join(topic_content.split())[:3500]
    caption_excerpt = " ".join(caption.split())[:1000]
    return IMAGE_PROMPT_TEMPLATE.format(
        topic_key=topic_key,
        source_excerpt=source_excerpt,
        caption_excerpt=caption_excerpt,
        style=random.choice(IMAGE_STYLES),
        color_palette=random.choice(IMAGE_COLOR_PALETTES),
    ).strip()