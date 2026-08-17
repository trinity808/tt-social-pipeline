"""
Standalone checkpointer validation -- NOT part of the real pipeline.
Tests whether langgraph-checkpoint-firestore genuinely persists paused
graph state across separate process invocations, simulating Cloud Run
recycling a container between pause and resume.

Run as TWO separate invocations, not back to back in one script:
  python scripts/test_checkpointer.py pause
  python scripts/test_checkpointer.py resume
"""

import sys
from typing import TypedDict

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt, Command
from langgraph_checkpoint_firestore import FirestoreSaver


class TestState(TypedDict):
    value: str


def node_a(state: TestState) -> dict:
    print(f"[node_a] starting with value: {state['value']}")
    return {"value": state["value"] + " -> node_a"}


def node_b(state: TestState) -> dict:
    print("[node_b] about to interrupt...")
    approved = interrupt({"question": "approve this?", "current_value": state["value"]})
    print(f"[node_b] resumed with: {approved}")
    return {"value": state["value"] + f" -> node_b (resumed: {approved})"}


def build_test_graph(checkpointer):
    graph = StateGraph(TestState)
    graph.add_node("node_a", node_a)
    graph.add_node("node_b", node_b)
    graph.set_entry_point("node_a")
    graph.add_edge("node_a", "node_b")
    graph.add_edge("node_b", END)
    return graph.compile(checkpointer=checkpointer)


THREAD_ID = "test-thread-001"

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "pause"
    config = {"configurable": {"thread_id": THREAD_ID}}

    # Using the documented from_conn_info() context-manager pattern rather
    # than direct instantiation -- more likely to match actual expected
    # usage, but this whole call is genuinely unverified until this script
    # actually runs. If this errors on the exact parameter names, that's
    # expected -- treat it the same as any other first-attempt API call in
    # this project and we'll adjust from the real error message.
    with FirestoreSaver.from_conn_info(
        project_id="tt-social-pipeline",
        checkpoints_collection="test_checkpoints",
        writes_collection="test_checkpoint_writes",
    ) as checkpointer:
        app = build_test_graph(checkpointer)

        if mode == "pause":
            result = app.invoke({"value": "start"}, config=config)
            print("\nResult after first invoke (should show interrupt info):")
            print(result)
        elif mode == "resume":
            result = app.invoke(Command(resume="yes-approved"), config=config)
            print("\nResult after resume (should show full completion):")
            print(result)
        elif mode == "resume_again":
            # Simulates a stale second click on an already-resolved thread.
            # This is a defense-in-depth check, NOT the primary mechanism --
            # the real endpoint should check our own Firestore status field
            # first and never even reach this call if already resolved.
            # This just tells us what happens if that check is ever bypassed.
            print("Attempting to resume an already-completed thread...")
            result = app.invoke(Command(resume="second-click-attempt"), config=config)
            print("\nResult of second resume attempt:")
            print(result)
        elif mode == "resume_unknown":
            # Simulates a malformed/tampered link -- a thread_id that was
            # never actually paused at all.
            unknown_config = {"configurable": {"thread_id": "never-existed-thread"}}
            print("Attempting to resume a thread_id that was never paused...")
            result = app.invoke(Command(resume="doesnt-matter"), config=unknown_config)
            print("\nResult of resuming an unknown thread:")
            print(result)