"""
Manual test for the review-gate + publish flow, using hardcoded content
and an already-existing local image -- zero LLM or image-generation cost.

Reuses the REAL send_for_review/await_approval functions (imported, not
reimplemented) wired into a minimal graph that skips load_topic/draft/
critic/generate_image entirely.

After this pauses and prints a thread_id, resume it with the EXISTING
harness -- it already includes the real publish_post node:
    python -m scripts.test_resume_review <thread_id> approved

Run from the repo root: python -m scripts.test_review_gate
"""

from pathlib import Path
import uuid

from langgraph.graph import StateGraph, END

from pipeline.graph import send_for_review, await_approval, checkpointer
from pipeline.state import (
    CriticVerdict,
    FacebookDraft,
    InstagramDraft,
    LinkedInDraft,
    PipelineState,
    PlatformVerdict,
    SocialPostDraft,
)

IMAGE_DIR = Path("generated_images")
TEST_CAPTION = "This is a test post from Trinity Tree's new pipeline. Please ignore."


def find_existing_image() -> str:
    images = sorted(
        p for p in IMAGE_DIR.iterdir()
        if p.suffix.lower() in {".png", ".jpg", ".jpeg"}
    )
    if not images:
        raise FileNotFoundError(f"No existing images found in '{IMAGE_DIR}' -- run the real pipeline at least once first.")
    return str(images[0])


def build_pause_only_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("send_for_review", send_for_review)
    graph.add_node("await_approval", await_approval)
    graph.set_entry_point("send_for_review")
    graph.add_edge("send_for_review", "await_approval")
    graph.add_edge("await_approval", END)
    return graph.compile(checkpointer=checkpointer)


if __name__ == "__main__":
    hardcoded_draft = SocialPostDraft(
        linkedin=LinkedInDraft(caption=TEST_CAPTION, hashtags=[]),
        instagram=InstagramDraft(caption=TEST_CAPTION, hashtags=["TestPost"]),
        facebook=FacebookDraft(caption=TEST_CAPTION, hashtags=["TestPost"]),
    )
    hardcoded_verdict = CriticVerdict(
        linkedin=PlatformVerdict(approved=True, reason="test"),
        instagram=PlatformVerdict(approved=True, reason="test"),
        facebook=PlatformVerdict(approved=True, reason="test"),
    )

    app = build_pause_only_graph()
    thread_id = str(uuid.uuid4())
    print(f"Using thread_id: {thread_id}")

    result = app.invoke(
        {
            "topic_key": "test_review_gate",
            "draft": hardcoded_draft,
            "verdict": hardcoded_verdict,
            "image_path": find_existing_image(),
        },
        config={"configurable": {"thread_id": thread_id}},
    )

    print("\nPaused. Resume with:")
    print(f"python -m scripts.test_resume_review {thread_id} approved")