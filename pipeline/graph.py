import json

from langgraph.graph import END, StateGraph

from agents.writer import draft_post
from pipeline.state import PipelineState

CONTENT_PATH = "content/site_content.json"


def load_topic(state: PipelineState) -> dict:
    with open(CONTENT_PATH, "r", encoding="utf-8") as f:
        content = json.load(f)
    return {"topic_content": content[state["topic_key"]]}


def draft(state: PipelineState) -> dict:
    result = draft_post(state["topic_content"])
    return {"draft": result}


def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("load_topic", load_topic)
    graph.add_node("draft", draft)
    graph.set_entry_point("load_topic")
    graph.add_edge("load_topic", "draft")
    graph.add_edge("draft", END)
    return graph.compile()


if __name__ == "__main__":
    app = build_graph()
    result = app.invoke({"topic_key": "psychiatry_medication"})
    print(result["draft"].model_dump_json(indent=2))