import json
import os
import uuid

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt
from langgraph_checkpoint_firestore import FirestoreSaver

from agents.critic import critique_draft
from agents.writer import draft_post, revise_post
from agents.image_generator import generate_post_image
from pipeline.logging_config import get_logger
from pipeline.review import create_pending_review, check_and_resolve_stale_review
from pipeline.state import PipelineState
from pipeline.storage import upload_image_to_gcs, download_image_for_publishing
from pipeline.rotation import record_topic_used, select_topic
from publishers.linkedin import post_to_linkedin
from publishers.facebook import post_to_facebook
from publishers.instagram import publish_to_instagram
from review.notifications import send_review_email

CONTENT_PATH = "content/site_content.json"
MAX_RETRIES = 1  # 1 retry = 2 total writer attempts before giving up
GCP_PROJECT_ID = os.environ["GCP_PROJECT_ID"]

logger = get_logger(__name__)

# Explicitly allowlisting our own types rather than relying on the default
# warn-and-allow behavior -- LangGraph is moving toward blocking
# unregistered types by default in a future version (there's an actual
# CVE, CVE-2026-28277, about unrestricted checkpoint deserialization).
#
# STATUS: attempted, appears NOT to actually work with this package.
# from_conn_info() accepts `serde=` without erroring, but the warning still
# fires on every resume regardless -- looks like this community package
# doesn't wire a custom serde into its actual read/write path, despite
# accepting the argument silently. Left in place since it's harmless and
# may start working if the package is ever updated, but do not assume this
# is a confirmed fix. Real exposure here requires write access to our
# Firestore checkpoint store, which is already tightly IAM-restricted --
# accepted as a known, understood limitation for now, not fixed.
serde = JsonPlusSerializer(
    allowed_msgpack_modules=[
        ("pipeline.state", "SocialPostDraft"),
        ("pipeline.state", "CriticVerdict"),
    ]
)

checkpointer = FirestoreSaver.from_conn_info(
    project_id=GCP_PROJECT_ID,
    checkpoints_collection="checkpoints",
    writes_collection="checkpoint_writes",
    serde=serde,
).__enter__()


def check_pending_review(state: PipelineState) -> dict:
    return {"pending_check_result": check_and_resolve_stale_review()}


def route_after_pending_check(state: PipelineState) -> str:
    return state["pending_check_result"]


def load_topic(state: PipelineState) -> dict:
    topic_key = state.get("topic_key")
    auto_selected = topic_key is None

    if auto_selected:
        topic_key = select_topic()

    logger.info(f"loading '{topic_key}'{' (auto-selected)' if auto_selected else ''}...")

    with open(CONTENT_PATH, "r", encoding="utf-8") as f:
        content = json.load(f)

    if auto_selected:
        record_topic_used(topic_key)

    return {"topic_key": topic_key, "topic_content": content[topic_key]}


def generate_image(state: PipelineState) -> dict:
    draft = state.get("draft")
    if draft is None:
        raise ValueError(
            "A completed social-media draft is required "
            "before generating an image."
        )
    logger.info("generating image...")
    image_path = generate_post_image(
        topic_key=state["topic_key"],
        topic_content=state["topic_content"],
        linkedin_caption=draft.linkedin.caption,
        instagram_caption=draft.instagram.caption,
        facebook_caption=draft.facebook.caption,
    )
    logger.info(f"image saved to: {image_path}")
    return {
        "image_path": image_path,
    }


def draft(state: PipelineState) -> dict:
    logger.info("generating initial draft...")
    result = draft_post(state["topic_content"])
    logger.info(f"initial draft:\n{result.model_dump_json(indent=2)}")
    return {"draft": result}


def critic(state: PipelineState) -> dict:
    logger.info("reviewing draft...")
    verdict = critique_draft(state["topic_content"], state["draft"])
    logger.info(f"verdict:\n{verdict.model_dump_json(indent=2)}")
    return {"verdict": verdict}


def revise(state: PipelineState) -> dict:
    logger.info("regenerating based on critic feedback...")
    new_draft = revise_post(state["topic_content"], state["draft"], state["verdict"])
    logger.info(f"revised draft:\n{new_draft.model_dump_json(indent=2)}")
    return {
        "draft": new_draft,
        "retry_count": state.get("retry_count", 0) + 1,
    }


def route_after_critic(state: PipelineState) -> str:
    verdict = state["verdict"]
    all_approved = (
        verdict.linkedin.approved
        and verdict.instagram.approved
        and verdict.facebook.approved
    )
    if all_approved:
        return "end"
    if state.get("retry_count", 0) >= MAX_RETRIES:
        # Retries exhausted -- still ends with the best-effort draft as-is.
        # Phase 5's review gate needs to know this state exists and flag it
        # for a human -- worth revisiting once send_for_review exists,
        # not solved by this node itself.
        return "end"
    return "revise"


def send_for_review(state: PipelineState, config: RunnableConfig) -> dict:
    thread_id = config["configurable"]["thread_id"]
    logger.info(f"sending draft for review (thread {thread_id})...")

    image_url = upload_image_to_gcs(state["image_path"])
    draft = state["draft"]
    pending_review = create_pending_review(thread_id, state["topic_key"], image_url, draft)

    send_review_email(
        thread_id=thread_id,
        topic_key=state["topic_key"],
        linkedin_caption=draft.linkedin.caption,
        instagram_caption=draft.instagram.caption,
        facebook_caption=draft.facebook.caption,
        image_url=image_url,
    )

    return {
        "cadence_eligibility": pending_review["cadence_eligibility"],
        "image_url": image_url,
    }


def await_approval(state: PipelineState) -> dict:
    """This node's only job is the interrupt() call -- no side effects
    before it, since this code re-runs in full every time someone resumes
    a paused thread."""
    decision = interrupt({
        "topic_key": state["topic_key"],
        "draft": state["draft"].model_dump(),
    })
    logger.info(f"review resumed with decision: {decision}")
    return {"review_decision": decision}


def route_after_approval(state: PipelineState) -> str:
    return "approved" if state.get("review_decision") == "approved" else "rejected"


def publish_post(state: PipelineState) -> dict:
    """Publishes the approved draft to each platform, gated by that
    platform's cadence eligibility locked in at draft time. One
    platform's failure shouldn't block the others -- each attempt is
    isolated in its own try/except."""
    draft = state["draft"]
    cadence_eligibility = state.get("cadence_eligibility", {})

    local_image_path = download_image_for_publishing(state["image_url"])

    results = {}

    if cadence_eligibility.get("linkedin"):
        try:
            post_urn = post_to_linkedin(
                caption=draft.linkedin.caption,
                hashtags=draft.linkedin.hashtags,
                image_path=local_image_path,
            )
            results["linkedin"] = {"status": "posted", "id": post_urn}
            logger.info(f"LinkedIn posted: {post_urn}")
        except Exception as e:
            results["linkedin"] = {"status": "failed", "error": str(e)}
            logger.exception(f"LinkedIn publish failed: {e}")
    else:
        results["linkedin"] = {"status": "skipped_cadence"}
        logger.info("LinkedIn skipped -- not a posting day")

    if cadence_eligibility.get("facebook"):
        try:
            response_body = post_to_facebook(
                caption=draft.facebook.caption,
                hashtags=draft.facebook.hashtags,
                image_path=local_image_path,
            )
            post_id = response_body.get("post_id") or response_body.get("id")
            results["facebook"] = {"status": "posted", "id": post_id}
            logger.info(f"Facebook posted: {post_id}")
        except Exception as e:
            results["facebook"] = {"status": "failed", "error": str(e)}
            logger.exception(f"Facebook publish failed: {e}")
    else:
        results["facebook"] = {"status": "skipped_cadence"}
        logger.info("Facebook skipped -- not a posting day")

    if cadence_eligibility.get("instagram"):
        try:
            media_id = publish_to_instagram(
                caption=draft.instagram.caption,
                hashtags=draft.instagram.hashtags,
                image_path=local_image_path,
            )
            results["instagram"] = {"status": "posted", "id": media_id}
            logger.info(f"Instagram posted: {media_id}")
        except Exception as e:
            results["instagram"] = {"status": "failed", "error": str(e)}
            logger.exception(f"Instagram publish failed: {e}")
    else:
        results["instagram"] = {"status": "skipped_cadence"}
        logger.info("Instagram skipped -- not a posting day")

    return {"publish_results": results}


def handle_rejection(state: PipelineState) -> dict:
    """The reject path -- doesn't post anything, just logs clearly why,
    rather than silently ending with no trace of what happened."""
    logger.info(f"draft for topic '{state['topic_key']}' was rejected -- not publishing")
    return {}


def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("load_topic", load_topic)
    graph.add_node("draft", draft)
    graph.add_node("critic", critic)
    graph.add_node("revise", revise)
    graph.add_node("generate_image", generate_image)
    graph.add_node("send_for_review", send_for_review)
    graph.add_node("await_approval", await_approval)
    graph.add_node("publish_post", publish_post)
    graph.add_node("handle_rejection", handle_rejection)

    graph.add_node("check_pending_review", check_pending_review)
    graph.set_entry_point("check_pending_review")
    graph.add_conditional_edges("check_pending_review", route_after_pending_check, {"skip": END, "proceed": "load_topic"})
    graph.add_edge("load_topic", "draft")
    graph.add_edge("draft", "critic")
    graph.add_conditional_edges("critic", route_after_critic, {"revise": "revise", "end": "generate_image"})
    graph.add_edge("revise", "critic")
    graph.add_edge("generate_image", "send_for_review")
    graph.add_edge("send_for_review", "await_approval")
    graph.add_conditional_edges("await_approval", route_after_approval, {"approved": "publish_post", "rejected": "handle_rejection"})
    graph.add_edge("publish_post", END)
    graph.add_edge("handle_rejection", END)
    return graph.compile(checkpointer=checkpointer)


if __name__ == "__main__":
    # Local-only debug tool -- never runs inside Cloud Run. Now requires a
    # thread_id since the graph has a checkpointer -- this run WILL pause
    # at await_approval and print an __interrupt__ key rather than fully
    # completing. Resuming it requires a separate script (not built yet).
    app = build_graph()
    thread_id = str(uuid.uuid4())
    print(f"Using thread_id: {thread_id}")

    result = app.invoke({}, config={"configurable": {"thread_id": thread_id}})

    print("\nResult (should show a pause at await_approval):")
    print(result)