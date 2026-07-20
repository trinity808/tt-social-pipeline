"""
Runs all 12 site content topics through both bake-off candidates
(Groq gpt-oss-120b and Gemini 3.5 Flash), saving every result to one
JSON file for manual grounding/tone review, rather than reading raw
terminal output for 72 individual captions one at a time.

Paced with a delay between every call as a precaution against Groq's
per-model TPM limit (8K tokens/minute on gpt-oss-120b) and against
Vertex AI's default per-project request quota, which isn't confirmed
for this project yet.

Run from the repo root: python -m scripts.run_bakeoff
"""

import json
import time

from agents.writer import draft_post_groq, draft_post_gemini

CONTENT_PATH = "content/site_content.json"
OUTPUT_PATH = "scripts/bakeoff_results.json"
DELAY_SECONDS = 15  # tune down later if this proves overly cautious


def run_bakeoff():
    with open(CONTENT_PATH, "r", encoding="utf-8") as f:
        content = json.load(f)

    results = []

    for topic, topic_content in content.items():
        print(f"\n--- {topic} ---")
        entry = {"topic": topic}

        print("  Calling Groq...")
        try:
            entry["groq"] = draft_post_groq(topic_content).model_dump()
        except Exception as e:
            entry["groq"] = {"error": str(e)}
            print(f"  Groq FAILED: {e}")
        time.sleep(DELAY_SECONDS)

        print("  Calling Gemini...")
        try:
            entry["gemini"] = draft_post_gemini(topic_content).model_dump()
        except Exception as e:
            entry["gemini"] = {"error": str(e)}
            print(f"  Gemini FAILED: {e}")
        time.sleep(DELAY_SECONDS)

        results.append(entry)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\nSaved {len(results)} topic results to {OUTPUT_PATH}")

    failures = [
        (r["topic"], model)
        for r in results
        for model in ("groq", "gemini")
        if "error" in r[model]
    ]
    if failures:
        print(f"Failures (topic, model): {failures}")
    else:
        print("No failures across either model.")


if __name__ == "__main__":
    run_bakeoff()