"""
Manual test harness for resuming a real pipeline run's review pause.

NOT the real Approve/Reject endpoint -- that's later work, and needs to
check pipeline.review's pending-review status before ever calling resume
at all (per what test_checkpointer.py's resume_unknown test showed: an
invalid/stale thread_id fails messily here, not gracefully). This script
is purely for confirming today that the real graph's send_for_review and
await_approval nodes pause and resume correctly end to end.

Usage: python scripts/test_resume_review.py <thread_id> <approved|rejected>
"""

import sys

from langgraph.types import Command

from pipeline.graph import build_graph


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/test_resume_review.py <thread_id> <approved|rejected>")
        sys.exit(1)

    thread_id = sys.argv[1]
    decision = sys.argv[2]

    if decision not in ("approved", "rejected"):
        print(f"Decision must be 'approved' or 'rejected', got: {decision}")
        sys.exit(1)

    app = build_graph()
    config = {"configurable": {"thread_id": thread_id}}

    print(f"Resuming thread {thread_id} with decision: {decision}\n")
    result = app.invoke(Command(resume=decision), config=config)

    print("\nResult after resume:")
    print(result)