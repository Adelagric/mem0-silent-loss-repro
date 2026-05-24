# mem0-silent-loss-repro

Minimal standalone reproduction of the silent memory loss path in
[`mem0`](https://github.com/mem0ai/mem0) `mem0/memory/main.py:770-783`
(audited on commit `6b9707f`, current `main`).

## TL;DR

When the embedding batch endpoint fails AND individual `embed()` calls fail
in the fallback path, the corresponding memory texts are **dropped silently**
from `embed_map`. The only signal is a `logger.warning(...)` that is filtered
out at default production log levels. No exception is raised to the caller of
`Memory.add()`.

Tracking issue: [mem0ai/mem0#TBD](https://github.com/mem0ai/mem0/issues/TBD)

## How to run

```bash
python -m venv .venv
source .venv/bin/activate
pip install mem0ai
python repro.py
```

## Expected output

```
Extracted 9 facts from LLM.
Log level set to ERROR (simulating production filtering).

Facts that would be inserted into vector store: 6
Facts silently dropped: 3

  [OK ] User's name is Alice.
  [OK ] User lives in Paris.
  [LOST] User works at Acme.
  [OK ] User has a dog named Rex.
  [OK ] User likes espresso.
  [LOST] User dislikes meetings.
  [OK ] User speaks French and English.
  [OK ] User's birthday is in March.
  [LOST] User runs every morning.

BUG CONFIRMED: 3 facts were dropped without any exception escaping the function.
In production, the caller of Memory.add() receives no signal that these memories
will never be retrievable.
```

## Why this matters

- The LLM extraction step (the expensive part of the pipeline) silently
  loses output downstream.
- Default production logging usually filters `WARNING`, so operators do not
  see the loss.
- No counter, no metric, no callback — only `mem0/memory/telemetry.py:202-206`
  ships static config attributes (`vector_size`, `embedding_model`) via
  PostHog, which does not surface this per-item failure.

The same swallow-and-log pattern exists at:

- `main.py:885-893` (`_resolve_entity_embeddings`)
- `main.py:452-454` (`_upsert_entity`)
- `main.py:1466` (boost path)
- `main.py:485-503` (`_remove_memory_from_entity_store`, at `debug` level —
  invisible in production)

## Related historical bugs in mem0 changelog

- PR #4362 — *Prevented embedding corruption in Valkey and Redis when vector
  is None* — patched in the store, not upstream in the embedder.
- PR #4481 — *Fixed OpenAI embedding dimensions*.
- PR #4224 — *Normalized malformed LLM fact output before embedding*.
- PR #4058 — *Pass `encoding_format='float'` in OpenAI embeddings for proxy
  compatibility*.

## License

CC0 — this reproduction is intentionally trivial and meant to be reused
freely by anyone investigating the same issue.
