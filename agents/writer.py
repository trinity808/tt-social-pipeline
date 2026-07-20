import os

from dotenv import load_dotenv
from openai import OpenAI

from pipeline.prompts import build_prompt
from pipeline.state import parse_draft, SocialPostDraft

load_dotenv()

openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def draft_post(topic_content: str, model: str = "gpt-5.5") -> SocialPostDraft:
    prompt = build_prompt(topic_content)
    response = openai_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return parse_draft(response.choices[0].message.content)