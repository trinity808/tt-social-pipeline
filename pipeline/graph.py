import json

from langgraph.graph import END, StateGraph

from agents.writer import draft_post
from pipeline.state import PipelineState
from agents.image_generator import generate_post_image

CONTENT_PATH = "content/site_content.json"


def load_topic(state: PipelineState) -> dict:
    with open(CONTENT_PATH, "r", encoding="utf-8") as f:
        content = json.load(f)
    return {"topic_content": content[state["topic_key"]]}

def generate_image(state: PipelineState) -> dict:
    draft = state.get("draft")

    if draft is None:
        raise ValueError(
            "A completed social-media draft is required "
            "before generating an image."
        )

    image_path = generate_post_image(
        topic_key=state["topic_key"],
        topic_content=state["topic_content"],
        # The Instagram caption is concise and works well as visual context.
        caption=draft.instagram.caption,
    )

    return {
        "image_path": image_path,
    }


def draft(state: PipelineState) -> dict:
    result = draft_post(state["topic_content"])
    return {"draft": result}


def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("load_topic", load_topic)
    graph.add_node("draft", draft)
    graph.add_node("generate_image", generate_image)

    graph.set_entry_point("load_topic")

    graph.add_edge("load_topic", "draft")
    graph.add_edge("draft", "generate_image")
    graph.add_edge("draft", END)
    return graph.compile()


if __name__ == "__main__":
    app = build_graph()
    result = app.invoke({"topic_key": "psychiatry_medication"})
    print(result["draft"].model_dump_json(indent=2))
    print(f"\nImage saved to: {result['image_path']}")