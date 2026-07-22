import os

from dotenv import load_dotenv
from openai import OpenAI

from pipeline.prompts import build_prompt, build_revision_prompt
from pipeline.state import CriticVerdict, parse_model, SocialPostDraft

load_dotenv()

openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def draft_post(topic_content: str, model: str = "gpt-5.5") -> SocialPostDraft:
    prompt = build_prompt(topic_content)
    response = openai_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return parse_model(response.choices[0].message.content, SocialPostDraft)


def revise_post(
    topic_content: str,
    previous_draft: SocialPostDraft,
    verdict: CriticVerdict,
    model: str = "gpt-5.5",
) -> SocialPostDraft:
    prompt = build_revision_prompt(topic_content, previous_draft, verdict)
    response = openai_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return parse_model(response.choices[0].message.content, SocialPostDraft)