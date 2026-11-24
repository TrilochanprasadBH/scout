"""Tests for the provider layer.

    python tests/test_providers.py

These run with no network and no key. The transport is injected, which is the whole reason
`RemoteModel` takes one: the fallback logic is the part that goes wrong in production, and it is
the part that can be tested offline.

What is checked:

  - the default provider is the scripted one, and it needs nothing
  - a hosted provider with no key fails loudly rather than silently using the stand-in
  - a chain skips providers with no key and moves on when one errors
  - both wire formats parse, including a fenced JSON reply
  - the same task and payload always render the same prompt
"""

from __future__ import annotations

import os
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scout.model import (  # noqa: E402
    PROVIDERS,
    FallbackChain,
    ProviderError,
    RemoteModel,
    ScriptedModel,
    build_model,
    render_prompt,
)

PLAN_JSON = '{"sub_questions": [{"question": "what is a safe method", "query": "safe method"}]}'


def openai_reply(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def gemini_reply(content: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": content}]}}]}


class Recorder:
    """A transport that records calls and returns a scripted response."""

    def __init__(self, response=None, error=None):
        self.calls = []
        self.response = response if response is not None else openai_reply(PLAN_JSON)
        self.error = error

    def __call__(self, url, headers, body):
        self.calls.append({"url": url, "headers": headers, "body": body})
        if self.error:
            raise self.error
        return self.response


class TestDefault(unittest.TestCase):
    def test_default_is_scripted_with_no_environment(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            model = build_model()
        self.assertIsInstance(model, ScriptedModel)
        self.assertEqual(model.name, "scripted")

    def test_scripted_needs_no_key_and_no_network(self):
        reply = ScriptedModel().complete("plan", {"question": "how do caches work", "max_parts": 2})
        self.assertEqual(reply.provider, "scripted")
        self.assertGreater(reply.tokens_out, 0)


class TestKeys(unittest.TestCase):
    def test_missing_key_fails_loudly(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ProviderError):
                build_model("openrouter")

    def test_never_falls_back_to_the_scripted_model(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ProviderError):
                build_model("openrouter,gemini")

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(ValueError):
            build_model("not-a-provider")


class TestRemote(unittest.TestCase):
    def test_openai_wire_format(self):
        recorder = Recorder()
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            model = RemoteModel(PROVIDERS["openrouter"], transport=recorder)
            reply = model.complete("plan", {"question": "q", "max_parts": 2})
        self.assertEqual(reply.provider, "openrouter")
        self.assertEqual(len(reply.data["sub_questions"]), 1)
        self.assertEqual(recorder.calls[0]["headers"]["authorization"], "Bearer test-key")

    def test_gemini_wire_format(self):
        recorder = Recorder(response=gemini_reply(PLAN_JSON))
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            model = RemoteModel(PROVIDERS["gemini"], transport=recorder)
            reply = model.complete("plan", {"question": "q", "max_parts": 2})
        self.assertEqual(reply.data["sub_questions"][0]["query"], "safe method")
        self.assertIn(":generateContent", recorder.calls[0]["url"])
        self.assertEqual(recorder.calls[0]["headers"]["x-goog-api-key"], "test-key")

    def test_fenced_json_is_accepted(self):
        recorder = Recorder(response=openai_reply("```json\n" + PLAN_JSON + "\n```"))
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            reply = RemoteModel(PROVIDERS["openai"], transport=recorder).complete(
                "plan", {"question": "q", "max_parts": 2}
            )
        self.assertIn("sub_questions", reply.data)

    def test_non_json_reply_is_a_provider_error(self):
        recorder = Recorder(response=openai_reply("I think the answer is 42"))
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            with self.assertRaises(ProviderError):
                RemoteModel(PROVIDERS["openai"], transport=recorder).complete(
                    "plan", {"question": "q", "max_parts": 2}
                )

    def test_max_tokens_is_forwarded(self):
        recorder = Recorder()
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            RemoteModel(PROVIDERS["openai"], transport=recorder).complete(
                "plan", {"question": "q", "max_parts": 2}, max_tokens=77
            )
        self.assertEqual(recorder.calls[0]["body"]["max_tokens"], 77)


class TestFallback(unittest.TestCase):
    def test_moves_on_when_the_first_provider_errors(self):
        failing = Recorder(error=ProviderError("boom"))
        working = Recorder()
        with mock.patch.dict(
            os.environ, {"OPENROUTER_API_KEY": "a", "OPENAI_API_KEY": "b"}
        ):
            chain = build_model(
                "openrouter,openai",
                transport=lambda url, headers, body: (
                    failing(url, headers, body) if "openrouter" in url else working(url, headers, body)
                ),
            )
            reply = chain.complete("plan", {"question": "q", "max_parts": 2})
        self.assertIsInstance(chain, FallbackChain)
        self.assertEqual(reply.provider, "openai")
        self.assertEqual(chain.attempts, ["openrouter: failed", "openai: ok"])

    def test_skips_a_provider_with_no_key(self):
        # Only the last provider has a key, so the chain collapses to that one model.
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "c"}, clear=True):
            model = build_model("openrouter,openai,gemini", transport=Recorder())
        self.assertEqual(model.name, "gemini")

    def test_a_two_provider_chain_keeps_its_order(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "b", "GEMINI_API_KEY": "c"}, clear=True):
            chain = build_model("gemini,openai", transport=Recorder())
        self.assertEqual([model.name for model in chain.models], ["gemini", "openai"])

    def test_single_available_provider_is_not_wrapped(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "b"}, clear=True):
            model = build_model("openrouter,openai", transport=Recorder())
        self.assertEqual(model.name, "openai")

    def test_chain_raises_when_every_provider_fails(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "b", "GEMINI_API_KEY": "c"}, clear=True):
            chain = build_model("openai,gemini", transport=Recorder(error=ProviderError("down")))
            with self.assertRaises(ProviderError):
                chain.complete("plan", {"question": "q", "max_parts": 2})


class TestPrompt(unittest.TestCase):
    def test_prompt_is_deterministic(self):
        payload = {"question": "how do caches work", "max_parts": 3}
        self.assertEqual(render_prompt("plan", payload), render_prompt("plan", payload))

    def test_prompt_names_the_contract(self):
        prompt = render_prompt("answer", {"question": "q", "passages": []})
        self.assertIn("answerable", prompt)
        self.assertIn("JSON", prompt)

    def test_every_task_has_a_schema(self):
        for task in ("plan", "answer", "merge"):
            self.assertIn("Return JSON", render_prompt(task, {}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
