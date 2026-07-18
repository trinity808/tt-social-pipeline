import os

from dotenv import load_dotenv
from google import genai

from pipeline.prompts import build_prompt
from pipeline.state import parse_draft, SocialPostDraft

load_dotenv()

gemini_client = genai.Client(
    enterprise=True,
    project=os.environ["GCP_PROJECT_ID"],
    location=os.environ.get("VERTEX_AI_LOCATION", "global"),
)


# NOTE: this is a Phase 1 leftover, not real critic logic yet. It still just
# drafts a fresh post straight from topic content, the same behavior it had
# during the writer model bake-off. The actual Phase 2 critic needs to take
# an existing draft plus the source content and return approve/reject with
# specific feedback -- that's new work, not something this move produces.
def draft_post_gemini(topic_content: str, model: str = "gemini-3.5-flash") -> SocialPostDraft:
    prompt = build_prompt(topic_content)
    response = gemini_client.models.generate_content(
        model=model,
        contents=[prompt],
    )
    return parse_draft(response.text)