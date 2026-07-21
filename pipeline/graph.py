import json

from langgraph.graph import END, StateGraph

from agents.critic import critique_draft
from agents.writer import draft_post, revise_post
from pipeline.state import PipelineState
from pipeline.rotation import record_topic_used, select_topic

CONTENT_PATH = "content/site_content.json"
MAX_RETRIES = 1  # 1 retry = 2 total writer attempts before giving up


def load_topic(state: PipelineState) -> dict:
    topic_key = state.get("topic_key")
    auto_selected = topic_key is None

    if auto_selected:
        topic_key = select_topic()

    print(f"[load_topic] loading '{topic_key}'{' (auto-selected)' if auto_selected else ''}...")

    with open(CONTENT_PATH, "r", encoding="utf-8") as f:
        content = json.load(f)

    if auto_selected:
        record_topic_used(topic_key)

    return {"topic_key": topic_key, "topic_content": content[topic_key]}


def draft(state: PipelineState) -> dict:
    print("[draft] generating initial draft...")
    result = draft_post(state["topic_content"])
    print(f"[draft] initial draft:\n{result.model_dump_json(indent=2)}\n")
    return {"draft": result}


def critic(state: PipelineState) -> dict:
    print("[critic] reviewing draft...")
    verdict = critique_draft(state["topic_content"], state["draft"])
    print(f"[critic] verdict:\n{verdict.model_dump_json(indent=2)}\n")
    return {"verdict": verdict}


def revise(state: PipelineState) -> dict:
    print("[revise] regenerating based on critic feedback...")
    new_draft = revise_post(state["topic_content"], state["draft"], state["verdict"])
    print(f"[revise] revised draft:\n{new_draft.model_dump_json(indent=2)}\n")
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
        # Phase 3's review gate needs to know this state exists and flag it
        # for a human, rather than silently treating it as approved.
        return "end"
    return "revise"


def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("load_topic", load_topic)
    graph.add_node("draft", draft)
    graph.add_node("critic", critic)
    graph.add_node("revise", revise)

    graph.set_entry_point("load_topic")
    graph.add_edge("load_topic", "draft")
    graph.add_edge("draft", "critic")
    graph.add_conditional_edges("critic", route_after_critic, {"revise": "revise", "end": END})
    graph.add_edge("revise", "critic")

    return graph.compile()


if __name__ == "__main__":
    app = build_graph()
    result = app.invoke({})

    print("Final verdict:")
    print(result["verdict"].model_dump_json(indent=2))
    print("\nFinal draft:")
    print(result["draft"].model_dump_json(indent=2))
    print(f"\nRetries used: {result.get('retry_count', 0)}")