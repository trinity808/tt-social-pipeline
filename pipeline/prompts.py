from pipeline.state import CriticVerdict, SocialPostDraft
import random
from typing import Sequence

# Stable facts true on every post regardless of topic -- shared across all
# three prompts so the critic isn't missing context the writer always has.
COMPANY_CONTEXT = "Trinity Tree Psychological Services is a clinical psychology practice based in Glendale, Arizona, providing evidence-based care for children, teens, and adults."

TIME_SENSITIVITY_RULE = "Do not make same-day-relative claims (e.g. \"today's hours are...\", \"we're open right now\") -- this content may be posted or reused on any day, and such claims can become false immediately. If stating hours or availability, always use explicit day labels (e.g. \"Monday-Friday, 9am-5pm; weekends by appointment\") instead."

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
{time_sensitivity_rule}

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
        time_sensitivity_rule=TIME_SENSITIVITY_RULE,
        topic_content=topic_content,
        platform_rules=PLATFORM_RULES,
        response_shape=RESPONSE_SHAPE,
    )


CRITIC_PROMPT_TEMPLATE = """You are reviewing a set of social media captions for Trinity Tree Psychological Services before they are approved for posting.

{company_context}
{time_sensitivity_rule}

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
5. Time-sensitivity — does the caption make any same-day-relative claim (e.g. 'today's hours') rather than using explicit day labels?

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
        time_sensitivity_rule=TIME_SENSITIVITY_RULE,
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
{time_sensitivity_rule}

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
        time_sensitivity_rule=TIME_SENSITIVITY_RULE,
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

# Determined via a one-time offline classification (scripts/classify_topic_
# list_length.py), not computed live per run -- topic content is static, so
# this only needs updating manually if a topic's content changes
# significantly or a new topic is added. Used below to exclude grid-style
# layouts for topics with many enumerable items, avoiding the silent
# partial-list problem found in testing.
TOPICS_WITH_LONG_LISTS = {
    "about",
    "faqs",
    "home",
    "insurance_payments",
    "psychiatry_medication",
    "psychological_evaluations",
    "softwave_trt",
    "speech_language",
    "students",
    "therapeutic_services",
}

IMAGE_STYLES = [
    "bold infographic with simple icons and clean layout",
    "clean minimalist poster with soft geometric shapes and gentle texture",
    "typographic editorial design with decorative geometric elements",
    "gentle illustrated infographic with structured content zones and abstract shapes",
]

# Status as of this commit, for PM visibility:
# - terracotta wellness, sage and sunrise: validated across multiple tests,
#   confirmed good.
# - soft botanical neutrals, earthy calm: carried over from an earlier,
#   flawed test (four palettes generated together in one ungrouped grid --
#   no reliable way to attribute which result came from which name).
#   Genuinely untested individually. Pending a proper isolated retest.
# - forest and gold: new, not yet tested at all. Proposed since Trinity
#   Tree's own branding (name, logo) is already tree/green-forward, and
#   none of the current options lean into that directly.
IMAGE_COLOR_PALETTES = [
    "terracotta wellness -- ivory, muted terracotta, dusty olive, clay beige, and soft moss",
    "sage and sunrise -- cream, eucalyptus green, warm apricot, soft golden yellow, and light stone",
    "soft botanical neutrals -- warm cream, muted sage, olive green, pale butter yellow, and light sand",
    "forest and gold -- deep forest green, sage green, warm gold accent, cream, and soft moss",
]

# Structural risk, confirmed in testing: this layout pushes toward fewer,
# heavier items rather than a long list shown lightly -- silently dropped
# 6 of 10 items on a long-list topic with no indication anything was
# omitted. Excluded from the pool specifically for topics in
# TOPICS_WITH_LONG_LISTS (see build_image_prompt below); still available
# for everything else.
GRID_LAYOUT = "structured grid layout with clear rows and columns for icon-based information"

IMAGE_LAYOUTS = [
    "radial infographic layout with a central focal circle and surrounding information blocks",
    GRID_LAYOUT,
    "arched poster layout with stacked sections and soft geometric framing",
    "organic landscape infographic layout with flowing bands, embedded icons, and one large focal area",
]

IMAGE_GRAPHIC_TREATMENTS = [
    "clean flat icons with soft circular badges",
    "thin line icons with editorial spacing and understated separators",
    "layered geometric panels with subtle texture and depth",
    "soft organic shape fields with icon callouts and minimal dividers",
]

IMAGE_PROMPT_TEMPLATE = """Create one professional square social-media image for Trinity Tree Psychological Services, a clinical psychology practice in Glendale, Arizona.

Topic:
{topic_key}

Approved website information:
{source_excerpt}

Related social-media captions (use these to inform which items to prioritize -- see CONTENT PRIORITY below):
LinkedIn: {linkedin_caption_excerpt}
Instagram: {instagram_caption_excerpt}
Facebook: {facebook_caption_excerpt}

Style: {style}
Color palette: {color_palette}
Layout direction: {layout}
Graphic treatment: {graphic_treatment}

CONTENT PRIORITY:
- Focus on ONE primary idea from the topic.
- Use the approved website information for factual grounding.
- If the topic naturally involves a list of related items (services, conditions, contact details, hours), you may include the full accurate list -- but each item must be represented with minimal weight: a short icon and a brief single-line label, never a multi-line description, heading-plus-subheading pair, or explanatory sentence per item.
- If the topic naturally involves a list of more than a few items, select approximately 6-7 for the image -- not the full list, but more than any single platform caption includes. Always include every item mentioned across the three captions above. Fill any remaining slots with other genuinely relevant items from the approved website information.
- Do not invent, embellish, or elaborate on any single item beyond what's needed to name it clearly.
- Prefer visual simplicity over completeness -- if a full list cannot be shown this lightly without crowding the canvas or losing legibility, select only the most relevant items instead.
- Leave elaboration and explanation for the accompanying social-media caption; the image should name things, not explain them.
- The image should be understandable within a few seconds of viewing.

VISUAL DIRECTION:
- Clean, warm, calm, modern, professional, and trustworthy.
- Maintain an infographic-inspired or geometric aesthetic.
- Use soft geometric elements such as rounded panels, arches, circles, curved lines, layered forms, simple iconography, and subtle dot patterns.
- Keep generous negative space.
- Avoid filling the entire canvas with information boxes or icons.
- Do not create a directory, service catalog, menu, or comprehensive list of Trinity Tree services.
- If icons are used, feature a moderate number rather than an overwhelming collection.
- One strong focal element should be visually dominant.

COLOR REQUIREMENTS:
- Make the selected palette clearly visible and dominant throughout the design.
- Favor warm cream and light neutral backgrounds.
- Avoid blue-dominant designs, navy, cobalt, and cool corporate blues.
- Avoid black-and-gold or luxury-brand styling.
- Keep colors warm, natural, and approachable -- not muted, dusty, or desaturated.

TEXT:
- Keep text minimal.
- Include "Trinity Tree Psychological Services" once as a small, understated brand signature.
- If additional informational text is appropriate for the selected style, use only a very short headline or a few brief labels.
- Do not reproduce long sentences or paragraphs from the website.
- Avoid more than approximately 15 to 25 words of informational text, excluding the practice name.

COMPOSITION:
- Create a clearly distinct composition based on the selected layout direction.
- Avoid repeatedly using a large centered panel surrounded by identical icon circles.
- Do not reuse the same arrangement of circles, arches, plants, and information cards across every image.
- Decorative botanical elements may be used sparingly but should not dominate every design.

SAFETY AND ACCURACY:
- Do not show identifiable real people.
- Do not invent services, credentials, diagnoses, claims, or treatment outcomes.
- Do not depict distress, medical emergencies, medications, or restraints.
- Do not include logos, URLs, phone numbers, hashtags, or invented quotes.

Overall goal:
Create a polished social-media graphic that communicates one clear idea rather than trying to explain everything Trinity Tree offers.
"""


def build_image_prompt(
    topic_key: str,
    topic_content: str,
    linkedin_caption: str,
    instagram_caption: str,
    facebook_caption: str,
) -> str:
    source_excerpt = " ".join(topic_content.split())[:3500]

    available_layouts = IMAGE_LAYOUTS
    if topic_key in TOPICS_WITH_LONG_LISTS:
        available_layouts = [layout for layout in IMAGE_LAYOUTS if layout != GRID_LAYOUT]

    chosen_layout = random.choice(available_layouts)

    return IMAGE_PROMPT_TEMPLATE.format(
        topic_key=topic_key,
        source_excerpt=source_excerpt,
        linkedin_caption_excerpt=" ".join(linkedin_caption.split()),
        instagram_caption_excerpt=" ".join(instagram_caption.split()),
        facebook_caption_excerpt=" ".join(facebook_caption.split()),
        style=random.choice(IMAGE_STYLES),
        color_palette=random.choice(IMAGE_COLOR_PALETTES),
        layout=chosen_layout,
        graphic_treatment=random.choice(IMAGE_GRAPHIC_TREATMENTS),
    ).strip()

def format_caption(caption: str, hashtags: Sequence[str] | None = None) -> str:
    """Flattens a caption + hashtag list into the single plain-text string
    each platform's API actually accepts -- none of LinkedIn's commentary,
    Facebook's message, or Instagram's caption fields have a distinct
    hashtag concept at the API level. This is purely formatting, not
    judgment -- relevance and count were already decided by the writer
    and critic before this ever runs."""
    clean_caption = caption.strip()
    formatted_hashtags: list[str] = []

    for raw_hashtag in hashtags or []:
        hashtag = str(raw_hashtag).strip().replace(" ", "")

        if not hashtag:
            continue

        if not hashtag.startswith("#"):
            hashtag = f"#{hashtag}"

        formatted_hashtags.append(hashtag)

    hashtag_text = " ".join(formatted_hashtags)

    if clean_caption and hashtag_text:
        return f"{clean_caption}\n\n{hashtag_text}"

    return clean_caption or hashtag_text