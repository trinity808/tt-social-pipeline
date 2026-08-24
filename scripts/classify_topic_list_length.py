"""
One-time classification tool: determines which topics describe a long list
of distinct items (services, conditions, categories), used to decide
whether image generation should avoid grid-style layouts for that topic.

Not part of the runtime pipeline -- run once, then hardcode the printed
result into TOPICS_WITH_LONG_LISTS in pipeline/prompts.py. Sanity-check
the result against your own knowledge of these topics before trusting it
outright, same as any other LLM output in this project.

Run from the repo root: python -m scripts.classify_topic_list_length
"""

import json
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

CONTENT_PATH = "content/site_content.json"

CLASSIFICATION_PROMPT = """You will be given website content for several topic pages from a psychology practice's website, each identified by a topic key.

For each topic, determine whether it describes a LONG LIST of more than roughly 5 distinct, separately-nameable items -- such as separate services, conditions treated, specialties, or categories -- where a reader would reasonably expect to see each one named individually.

Do NOT count generic prose, mission statements, or narrative descriptions as a "list" even if they're long. Only count genuine enumerable items.

Topics:
{topics_block}

Return ONLY valid JSON in this exact shape, no text before or after it:
{{
  "topic_key_1": true,
  "topic_key_2": false
}}
"""


def main():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing from the environment.")

    with open(CONTENT_PATH, "r", encoding="utf-8") as f:
        content = json.load(f)

    topics_block = "\n\n".join(
        f"--- {topic_key} ---\n{topic_content}"
        for topic_key, topic_content in content.items()
    )

    prompt = CLASSIFICATION_PROMPT.format(topics_block=topics_block)

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-5.5",
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    result = json.loads(raw)

    print("Classification result:")
    print(json.dumps(result, indent=2))

    long_list_topics = sorted(key for key, is_long in result.items() if is_long)
    print("\nSuggested TOPICS_WITH_LONG_LISTS set:")
    print("TOPICS_WITH_LONG_LISTS = {")
    for key in long_list_topics:
        print(f'    "{key}",')
    print("}")


if __name__ == "__main__":
    main()