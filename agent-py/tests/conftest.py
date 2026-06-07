"""Test setup: provide dummy model creds so the agent constructs offline.

The LLM is built from QWEN_* env at construction time; the openai client is lazy
(no network until a call), so a placeholder key is enough for the unit tests,
which exercise the tool methods directly rather than the model.
"""

import os

os.environ.setdefault("QWEN_API_KEY", "test-key")
os.environ.setdefault("QWEN_BASE_URL", "https://example.invalid/v1")
