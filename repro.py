"""
Minimal isolated reproduction of the silent memory loss path in
mem0/memory/main.py:770-783 (commit 6b9707f, current main as of audit).

Strategy:
- We do NOT spin up the full Memory pipeline (which would require LLM mocking,
  a vector store, etc.).
- Instead we reproduce verbatim the 13-line code block from
  mem0/memory/main.py:770-783 and feed it a flaky embedder.
- We observe that texts whose individual embed() call fails are silently
  dropped from embed_map, with only a logger.warning() that disappears in
  production-level log filters.

Run:
    python -m venv .venv && source .venv/bin/activate
    pip install mem0ai
    python repro.py
"""

import logging
import sys

from mem0.embeddings.mock import MockEmbeddings

# Keep logger silent to simulate prod log filtering (WARNING ignored).
# Flip this to logging.WARNING to see the warning the code emits — but
# nothing escapes as an exception either way.
LOG_LEVEL = logging.ERROR
logging.basicConfig(level=LOG_LEVEL, stream=sys.stderr,
                    format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mem0.memory.main")


class FlakyEmbedder(MockEmbeddings):
    """Embedder that fails every 3rd individual call to simulate a transient
    provider error (5xx, throttle, malformed response).

    Forces the per-item fallback path by always failing the batch endpoint."""

    def __init__(self):
        # mem0 0.1.x MockEmbeddings expects no required arg; in older
        # versions it accepts a config kwarg. Try both for compatibility.
        try:
            super().__init__()
        except TypeError:
            super().__init__(config=None)
        self.call_count = 0

    def embed(self, text, memory_action=None):
        self.call_count += 1
        if self.call_count % 3 == 0:
            raise RuntimeError("Simulated provider 503 on item")
        return super().embed(text, memory_action=memory_action)

    def embed_batch(self, texts, memory_action="add"):
        # Force fallback to per-item path. This is the trigger condition
        # for the silent-loss bug.
        raise RuntimeError("Simulated batch endpoint unavailable")


def reproduce_silent_loss(mem_texts):
    """Verbatim copy of mem0/memory/main.py:770-783, V3 add pipeline phase 3."""
    embedding_model = FlakyEmbedder()

    # ---------- begin verbatim from main.py:770-783 ----------
    try:
        mem_embeddings_list = embedding_model.embed_batch(mem_texts, "add")
        embed_map = dict(zip(mem_texts, mem_embeddings_list))
    except Exception:
        # Fallback: embed individually
        embed_map = {}
        for text in mem_texts:
            try:
                embed_map[text] = embedding_model.embed(text, "add")
            except Exception as e:
                logger.warning(f"Failed to embed memory text: {e}")
    # ---------- end verbatim from main.py:770-783 ----------

    return embed_map


def main():
    # Simulate facts extracted by the LLM in an Memory.add() call.
    extracted_facts = [
        "User's name is Alice.",
        "User lives in Paris.",
        "User works at Acme.",        # call #3 → will fail
        "User has a dog named Rex.",
        "User likes espresso.",
        "User dislikes meetings.",    # call #6 → will fail
        "User speaks French and English.",
        "User's birthday is in March.",
        "User runs every morning.",   # call #9 → will fail
    ]

    print(f"Extracted {len(extracted_facts)} facts from LLM.")
    print(f"Log level set to {logging.getLevelName(LOG_LEVEL)} "
          f"(simulating production filtering).\n")

    embed_map = reproduce_silent_loss(extracted_facts)

    stored = len(embed_map)
    lost = len(extracted_facts) - stored

    print(f"Facts that would be inserted into vector store: {stored}")
    print(f"Facts silently dropped: {lost}\n")

    for fact in extracted_facts:
        marker = "OK " if fact in embed_map else "LOST"
        print(f"  [{marker}] {fact}")

    print()
    if lost > 0:
        print(f"BUG CONFIRMED: {lost} facts were dropped without any exception "
              f"escaping the function.")
        print("In production, the caller of Memory.add() receives no signal "
              "that these memories will never be retrievable.")
        sys.exit(0)  # exit 0: bug demonstrated as expected
    else:
        print("No loss observed in this run.")
        sys.exit(1)


if __name__ == "__main__":
    main()
