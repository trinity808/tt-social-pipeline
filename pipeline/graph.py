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
from pipeline.review import create_pending_review
from pipeline.state import PipelineState
from pipeline.rotation import record_topic_used, select_topic

CONTENT_PATH = "content/site_content.json"
MAX_RETRIES = 1  # 1 retry = 2 total writer attempts before giving up
GCP_PROJECT_ID = os.environ["GCP_PROJECT_ID"]

logger = get_logger(__name__)

# Attempted fix for LangGraph's "unregistered type" warning (there's an
# actual CVE, CVE-2026-28277, about unrestricted checkpoint deserialization
# -- this isn't just cosmetic). This accepts the `serde` keyword without
# erroring, but the warning still appears on real use -- meaning
# FirestoreSaver.from_conn_info() likely accepts the parameter but doesn't
# actually wire it into real reads/writes. Left in place since it's
# harmless and may start working if this community package is updated
# later, but treat this as NOT a confirmed fix. Known, accepted risk for
# now: exploiting this requires write access to Firestore itself, which is
# already tightly IAM-restricted to our own service account and the few of
# us with explicit grants.
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
        caption=draft.instagram.caption,
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
    """No interrupt() here -- this is a normal, fully-completed node once
    it runs. It never re-executes on a later resume, unlike await_approval.
    Email sending is stubbed -- that's Track B's piece, not built here."""
    thread_id = config["configurable"]["thread_id"]
    logger.info(f"sending draft for review (thread {thread_id})...")

    create_pending_review(thread_id, state["topic_key"])

    # TODO (Track B): real email sending goes here.
    logger.info("[STUB] email would be sent here")

    return {}


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


def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("load_topic", load_topic)
    graph.add_node("draft", draft)
    graph.add_node("critic", critic)
    graph.add_node("revise", revise)
    graph.add_node("generate_image", generate_image)
    graph.add_node("send_for_review", send_for_review)
    graph.add_node("await_approval", await_approval)

    graph.set_entry_point("load_topic")
    graph.add_edge("load_topic", "draft")
    graph.add_edge("draft", "critic")
    graph.add_conditional_edges("critic", route_after_critic, {"revise": "revise", "end": "generate_image"})
    graph.add_edge("revise", "critic")
    graph.add_edge("generate_image", "send_for_review")
    graph.add_edge("send_for_review", "await_approval")
    # Both branches currently go to END -- publish nodes aren't built yet.
    # "approved" should eventually route to real publish nodes instead.
    # Today's goal is proving the pause/resume/routing mechanics work.
    graph.add_conditional_edges("await_approval", route_after_approval, {"approved": END, "rejected": END})

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