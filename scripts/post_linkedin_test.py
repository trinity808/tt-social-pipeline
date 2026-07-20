"""
One-time manual test: runs the Phase 1 graph, shows the generated LinkedIn
caption for human review, and only posts to LinkedIn if explicitly confirmed.

This is NOT the Phase 4 publisher module -- no retry logic, no token
refresh, no Facebook/Instagram. Just enough to prove the auth + post call
chain actually works end to end, once, on a real caption, with a human
watching before it goes live.

Run from the repo root: python -m scripts.post_linkedin_test
"""

import os

import requests
from dotenv import load_dotenv

from pipeline.graph import build_graph

load_dotenv()

ACCESS_TOKEN = os.environ["LINKEDIN_ACCESS_TOKEN"]
ORG_URN = os.environ["LINKEDIN_ORG_URN"]

POST_URL = "https://api.linkedin.com/rest/posts"
LINKEDIN_VERSION = "202605"  # if this ever errors, check LinkedIn's docs for the current supported version


def post_to_linkedin(caption: str):
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": LINKEDIN_VERSION,
    }
    payload = {
        "author": ORG_URN,
        "commentary": caption,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    response = requests.post(POST_URL, headers=headers, json=payload)

    if response.status_code == 201:
        post_urn = response.headers.get("x-restli-id")
        print(f"\nPosted successfully. Post URN: {post_urn}")
    else:
        print(f"\nFAILED -- status {response.status_code}")
        print(response.text)


if __name__ == "__main__":
    app = build_graph()

    topic_key = input("Which topic_key should this post be about? ").strip()
    print("\nRunning graph...\n")
    result = app.invoke({"topic_key": topic_key})

    caption = result["draft"].linkedin.caption

    print("--- Generated LinkedIn caption ---")
    print(caption)
    print("-----------------------------------\n")

    confirm = input("Post this to TT's real LinkedIn page? Type 'yes' to confirm: ").strip().lower()

    if confirm == "yes":
        post_to_linkedin(caption)
    else:
        print("Not posted.")