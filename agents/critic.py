import os

from dotenv import load_dotenv
from langsmith import traceable
from google import genai

from pipeline.prompts import build_critic_prompt
from pipeline.state import CriticVerdict, parse_model, SocialPostDraft

load_dotenv()

gemini_client = genai.Client(
    enterprise=True,
    project=os.environ["GCP_PROJECT_ID"],
    location=os.environ.get("VERTEX_AI_LOCATION", "global"),
)


CRITIC_MODEL = os.getenv(
    "CRITIC_MODEL", 
    "gemini-3.5-flash",
).strip()


def process_critic_inputs(inputs: dict) -> dict:
    # Reconstructs the actual prompt sent to Gemini for LangSmith visibility.
    # Safe because build_critic_prompt is deterministic -- this produces
    # exactly what the real function call builds internally.
    return {
        "prompt": build_critic_prompt(inputs["topic_content"], inputs["draft"]),
        "model": inputs["model"],
    }


@traceable(run_type="llm", process_inputs=process_critic_inputs)
def critique_draft(topic_content: str, draft: SocialPostDraft, model: str = CRITIC_MODEL) -> CriticVerdict:
    prompt = build_critic_prompt(topic_content, draft)
    response = gemini_client.models.generate_content(
        model=model,
        contents=[prompt],
    )
    return parse_model(response.text, CriticVerdict)