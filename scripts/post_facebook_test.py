"""
One-time manual test: runs the Phase 1 graph, shows the generated Facebook
caption for human review, and only posts to Facebook if explicitly confirmed.

This is NOT the Phase 4 publisher module -- no retry logic, no token
refresh, no image attachment. Just enough to prove the auth + post call
chain actually works end to end, once, on a real caption, with a human
watching before it goes live.

Run from the repo root: python -m scripts.post_facebook_test
"""

import os

import requests
from dotenv import load_dotenv

from pipeline.graph import build_graph

load_dotenv()

ACCESS_TOKEN = os.environ["META_ACCESS_TOKEN"]  # this must be a Page access token, not a User access token
PAGE_ID = os.environ["FACEBOOK_PAGE_ID"]

GRAPH_API_VERSION = "v25.0"  # if this ever errors, check Meta's changelog for the current supported version
POST_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PAGE_ID}/feed"


def post_to_facebook(caption: str):
    payload = {
        "message": caption,
        "access_token": ACCESS_TOKEN,
    }

    response = requests.post(POST_URL, data=payload)

    if response.status_code == 200:
        post_id = response.json().get("id")
        print(f"\nPosted successfully. Post ID: {post_id}")
    else:
        print(f"\nFAILED -- status {response.status_code}")
        print(response.text)


if __name__ == "__main__":
    app = build_graph()

    topic_key = input("Which topic_key should this post be about? ").strip()
    print("\nRunning graph...\n")
    result = app.invoke({"topic_key": topic_key})

    caption = result["draft"].facebook.caption

    print("--- Generated Facebook caption ---")
    print(caption)
    print("-----------------------------------\n")

    confirm = input("Post this to TT's real Facebook page? Type 'yes' to confirm: ").strip().lower()

    if confirm == "yes":
        post_to_facebook(caption)
    else:
        print("Not posted.")