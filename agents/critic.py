import os

from dotenv import load_dotenv
from google import genai

from pipeline.prompts import build_critic_prompt
from pipeline.state import CriticVerdict, parse_model, SocialPostDraft

load_dotenv()

gemini_client = genai.Client(
    enterprise=True,
    project=os.environ["GCP_PROJECT_ID"],
    location=os.environ.get("VERTEX_AI_LOCATION", "global"),
)


def critique_draft(
    topic_content: str, draft: SocialPostDraft, model: str = "gemini-3.5-flash"
) -> CriticVerdict:
    prompt = build_critic_prompt(topic_content, draft)
    response = gemini_client.models.generate_content(
        model=model,
        contents=[prompt],
    )
    return parse_model(response.text, CriticVerdict)