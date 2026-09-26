# Local DeepSeek task worker

The local Ollama installation currently contains `deepseek-r1:1.5b`. This runner
calls it directly on `127.0.0.1:11434`; no OpenAI API or Codex subagent is involved.
Ollama must already be running and the selected model must already be installed.

```sh
python3 automation/local_worker.py \
  --task 'Propose a test for restore rejecting an invalid cursor without mutation.' \
  --context speedrun/native_rng.py \
  --output /tmp/rng-review.json
```

Repeat `--context` to include explicit repository text files. Each request is
limited to 24,000 context characters, 1,500 output tokens and a 180-second HTTP
timeout by default. `--tokens`, `--timeout`, and `--model` override those defaults.
The timeout limits client waiting; server cancellation is not guaranteed.
No model is downloaded automatically and there is no paid-model fallback.

Pipeline: small task + selected files → local inference → JSON validation →
saved proposal → human/Codex review → apply useful changes → run actual tests.
Delegate independent, narrow test proposals, code explanations, and evidence
summaries. Use separate invocations/output files for a task queue; start with
sequential execution to avoid competing for local memory.

Reports preserve source hashes, raw responses, inference timing/token counts
returned by Ollama, and validation status. Valid JSON is marked `needs-review`,
not verified. Truncated/malformed responses fail; output paths must be new.
The model has no shell, filesystem editing, game control, or automatic patch
application. Supply only files relevant to the task. A small local model's
claims must be checked against the code and tests before integration.

API: [Ollama chat documentation](https://docs.ollama.com/api/chat).

Local smoke test (2026-09-26): `deepseek-r1:1.5b` returned schema-valid JSON in
about 47 seconds on CPU. Its first RNG test proposal incorrectly classified a
valid cursor boundary as invalid, and omitted the requested executable test.
Connectivity and formatting therefore passed; that proposal was rejected on
technical review. Prefer tasks with explicit acceptance criteria.
A second, tightly specified test-generation request exhausted a 600-token cap
without final content; the runner saved the response and rejected it as invalid.
These checks establish connectivity and failure handling, not coding reliability.

```sh
PYTHONPATH=automation python3 -m unittest automation/test_local_worker.py -q
```
