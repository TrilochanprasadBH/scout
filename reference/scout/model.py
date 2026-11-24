"""The model interface, given.

Everything `scout` asks a model to do is one of three *tasks*, and every task has a JSON
contract. A provider renders the task as a prompt and parses the reply; the pipeline only
ever sees the contract. That is what makes the project runnable without a key and switchable
to a real model without touching the stages.

    task="plan"    {"question", "max_parts"}            -> {"sub_questions": [...]}
    task="answer"  {"question", "passages"}             -> {"sentences": [...], "answerable"}
    task="merge"   {"question", "findings"}             -> {"sentences": [...]}

**The default provider is `scripted`.** It is a deterministic stand-in: an extractive
question-answerer over the passages it is given, plus a clause splitter for planning. It is
weak in specific, documented ways, and every stage number in this project measures the
orchestration built around it, not model quality.

**Real providers are opt-in.** `SCOUT_PROVIDER=openrouter` with `OPENROUTER_API_KEY`, or a
chain: `SCOUT_PROVIDER=openrouter,gemini,openai`. Keys are read from the environment and
never from a flag, never from a file in this repository. If the first provider fails, the
next one is tried. Nothing in the test path uses a provider that is not `scripted`.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .text import content_terms, count, sentences as split_sentences, shared

ProviderTransport = Callable[[str, dict[str, str], dict], dict]


class ProviderError(RuntimeError):
    """A provider could not answer. The chain moves to the next one."""


@dataclass(frozen=True)
class Reply:
    """One answer from one model, with the accounting a budget needs."""

    task: str
    data: dict
    tokens_in: int
    tokens_out: int
    provider: str

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    @property
    def truncated(self) -> bool:
        return bool(self.data.get("truncated"))


class Model(Protocol):
    name: str

    def complete(self, task: str, payload: dict, *, max_tokens: int = 512) -> Reply:
        ...


def _payload_tokens(payload: dict) -> int:
    if isinstance(payload, str):
        return count(payload)
    if isinstance(payload, dict):
        return sum(_payload_tokens(value) for value in payload.values()) + len(payload)
    if isinstance(payload, (list, tuple)):
        return sum(_payload_tokens(value) for value in payload) + len(payload)
    return count(str(payload))


def _trim(items: list, max_tokens: int, task: str) -> tuple[list, bool]:
    """Drop items from the end until the *reply* fits. Truncation is reported, never silent.

    `max_tokens` caps generation, not the prompt: a caller that sends 20 KB of passages and
    asks for a two-sentence answer is not over budget. Treating the input as part of the cap
    silently returns nothing, which is what happened the first time this was written.
    """
    key = "sub_questions" if task == "plan" else "sentences"
    trimmed = list(items)
    while trimmed:
        if _payload_tokens({key: trimmed}) <= max_tokens:
            return trimmed, False
        trimmed.pop()
    return trimmed, bool(items)


class ScriptedModel:
    """Deterministic stand-in for a language model.

    Planning: split the question on explicit coordination ("and", "versus", ";"). It does
    not notice implicit facets, and it keeps whatever scaffolding the question arrived in,
    which is why its raw plans need cleaning up.

    Answering: score every sentence in the supplied passages by how many distinct content
    terms it shares with the question, and return the best one.

      - two or more shared terms  -> an answer that is probably supported
      - exactly one shared term   -> an answer that is probably not supported
      - none                      -> a refusal

    That middle case is deliberate. A real model asked a question it cannot support will
    often answer from the nearest passage anyway, and stage 04 exists because of it.

    Merging: every sentence from every finding, ordered by relevance, with duplicates left
    in. Deduplication and conflict handling are the orchestrator's job, not the model's.
    """

    name = "scripted"

    def complete(self, task: str, payload: dict, *, max_tokens: int = 512) -> Reply:
        if task == "plan":
            data = self._plan(payload, max_tokens)
        elif task == "answer":
            data = self._answer(payload, max_tokens)
        elif task == "merge":
            data = self._merge(payload, max_tokens)
        else:
            raise ValueError(f"unknown task {task!r}")

        return Reply(
            task=task,
            data=data,
            tokens_in=_payload_tokens(payload),
            tokens_out=_payload_tokens(data),
            provider=self.name,
        )

    def _plan(self, payload: dict, max_tokens: int) -> dict:
        question = str(payload.get("question", ""))
        limit = int(payload.get("max_parts", 4))
        parts = [part.strip(" ?.") for part in _split_clauses(question)]
        parts = [part for part in parts if content_terms(part)] or [question.strip(" ?.")]
        parts = parts[:limit]
        items = [
            {"question": part, "query": " ".join(content_terms(part))}
            for part in parts
        ]
        items, truncated = _trim(items, max_tokens, "plan")
        return {"sub_questions": items, "truncated": truncated}

    def _answer(self, payload: dict, max_tokens: int) -> dict:
        question = str(payload.get("question", ""))
        passages = payload.get("passages", [])
        scored: list[tuple[int, str, str]] = []
        for passage in passages:
            for sentence in split_sentences(str(passage.get("text", ""))):
                score = shared(sentence, question)
                scored.append((score, str(passage.get("section", "")), sentence))
        scored.sort(key=lambda item: (-item[0], item[1], item[2]))

        if not scored:
            return {"sentences": [], "answerable": False, "truncated": False}

        best = scored[0][0]
        answerable = best >= 2
        limit = int(payload.get("max_sentences", 3))

        # One sentence per section, best first. A model with one output slot per section can
        # assert several things; returning two sentences from the same passage would look
        # like more evidence than it is.
        threshold = 2 if best >= 2 else 1
        chosen: list[tuple[int, str, str]] = []
        used: set[str] = set()
        for score, section, sentence in scored:
            if score < threshold or section in used:
                continue
            chosen.append((score, section, sentence))
            used.add(section)
            if len(chosen) >= limit:
                break
        items = [{"text": sentence, "section": section} for _, section, sentence in chosen]
        items, truncated = _trim(items, max_tokens, "answer")
        return {"sentences": items, "answerable": answerable, "truncated": truncated}

    def _merge(self, payload: dict, max_tokens: int) -> dict:
        question = str(payload.get("question", ""))
        rows: list[tuple[int, str, str]] = []
        for finding in payload.get("findings", []):
            for sentence in finding.get("sentences", []):
                text = str(sentence.get("text", ""))
                section = str(sentence.get("section", ""))
                rows.append((shared(text, question), section, text))
        rows.sort(key=lambda item: (-item[0], item[1], item[2]))
        items = [{"text": text, "section": section} for _, section, text in rows]
        items, truncated = _trim(items, max_tokens, "merge")
        return {"sentences": items, "truncated": truncated}


def _split_clauses(question: str) -> list[str]:
    import re

    parts = re.split(r"\s+(?:and|versus|vs\.?)\s+|;\s*", question)
    return [part for part in parts if part.strip()]


# --------------------------------------------------------------------------- remote providers


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    url: str
    model: str
    key_env: str
    style: str  # "openai" (chat completions) or "gemini" (generateContent)


PROVIDERS: dict[str, ProviderSpec] = {
    "openrouter": ProviderSpec(
        name="openrouter",
        url="https://openrouter.ai/api/v1/chat/completions",
        model="anthropic/claude-sonnet-4.5",
        key_env="OPENROUTER_API_KEY",
        style="openai",
    ),
    "openai": ProviderSpec(
        name="openai",
        url="https://api.openai.com/v1/chat/completions",
        model="gpt-4.1-mini",
        key_env="OPENAI_API_KEY",
        style="openai",
    ),
    "gemini": ProviderSpec(
        name="gemini",
        url="https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        model="gemini-2.5-flash",
        key_env="GEMINI_API_KEY",
        style="gemini",
    ),
}

TASK_SCHEMA = {
    "plan": 'Return JSON exactly as {"sub_questions": [{"question": str, "query": str}]}.',
    "answer": (
        'Return JSON exactly as {"sentences": [{"text": str, "section": str}], '
        '"answerable": bool}. Quote sentences from the passages. If no passage supports an '
        "answer, return an empty list and answerable false."
    ),
    "merge": 'Return JSON exactly as {"sentences": [{"text": str, "section": str}]}.',
}


def render_prompt(task: str, payload: dict) -> str:
    """Turn a task into one prompt. Kept boring on purpose: it is infrastructure, not a
    place to be clever, and a stable prompt is easier to price."""
    return (
        f"You are working on the task {task!r}.\n"
        f"{TASK_SCHEMA[task]}\n"
        "Answer with JSON only, no prose and no code fence.\n\n"
        f"INPUT\n{json.dumps(payload, sort_keys=True, indent=2)}\n"
    )


def urllib_transport(url: str, headers: dict[str, str], body: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
        raise ProviderError(f"{url}: {error}") from error


def _extract_text(spec: ProviderSpec, response: dict) -> str:
    if spec.style == "gemini":
        candidates = response.get("candidates") or []
        if not candidates:
            raise ProviderError(f"{spec.name}: no candidates in response")
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(str(part.get("text", "")) for part in parts)
    choices = response.get("choices") or []
    if not choices:
        raise ProviderError(f"{spec.name}: no choices in response")
    return str(choices[0].get("message", {}).get("content", ""))


def _parse_json(text: str) -> dict:
    """Accept a bare object or a fenced one. Anything else is a provider error."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("```")[1]
        if stripped.startswith("json"):
            stripped = stripped[4:]
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end == -1:
        raise ProviderError("reply contained no JSON object")
    try:
        return json.loads(stripped[start : end + 1])
    except json.JSONDecodeError as error:
        raise ProviderError(f"reply was not valid JSON: {error}") from error


class RemoteModel:
    """One hosted provider. Not used unless asked for by name."""

    def __init__(self, spec: ProviderSpec, transport: ProviderTransport | None = None) -> None:
        self.spec = spec
        self.name = spec.name
        self.transport = transport or urllib_transport

    def available(self) -> bool:
        return bool(os.environ.get(self.spec.key_env))

    def complete(self, task: str, payload: dict, *, max_tokens: int = 512) -> Reply:
        key = os.environ.get(self.spec.key_env)
        if not key:
            raise ProviderError(f"{self.spec.name}: {self.spec.key_env} is not set")

        prompt = render_prompt(task, payload)
        if self.spec.style == "gemini":
            url = self.spec.url.format(model=self.spec.model)
            body = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0},
            }
            headers = {"x-goog-api-key": key}
        else:
            url = self.spec.url
            body = {
                "model": self.spec.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0,
            }
            headers = {"authorization": f"Bearer {key}"}

        response = self.transport(url, headers, body)
        data = _parse_json(_extract_text(self.spec, response))
        return Reply(
            task=task,
            data=data,
            tokens_in=count(prompt),
            tokens_out=_payload_tokens(data),
            provider=self.name,
        )


class FallbackChain:
    """Try each provider in order. The first that answers wins, and says so."""

    name = "fallback"

    def __init__(self, models: list[Model]) -> None:
        if not models:
            raise ValueError("a fallback chain needs at least one model")
        self.models = list(models)
        self.attempts: list[str] = []

    def complete(self, task: str, payload: dict, *, max_tokens: int = 512) -> Reply:
        errors = []
        for model in self.models:
            try:
                reply = model.complete(task, payload, max_tokens=max_tokens)
            except ProviderError as error:
                errors.append(str(error))
                self.attempts.append(f"{model.name}: failed")
                continue
            self.attempts.append(f"{model.name}: ok")
            return reply
        raise ProviderError("every provider failed: " + " | ".join(errors))


def build_model(spec: str | None = None, *, transport: ProviderTransport | None = None) -> Model:
    """Build the model named by `spec`, or by `SCOUT_PROVIDER`, or the scripted default.

    A chain skips providers with no key, and raises if none is left. It never falls back
    *to* the scripted model: a silent fallback from a real model to a stand-in would change
    the meaning of every number a report prints.
    """
    spec = (spec or os.environ.get("SCOUT_PROVIDER") or "scripted").strip()
    if spec == "scripted":
        return ScriptedModel()

    names = [name.strip() for name in spec.split(",") if name.strip()]
    unknown = [name for name in names if name not in PROVIDERS]
    if unknown:
        raise ValueError(f"unknown provider(s): {', '.join(unknown)}. Known: {', '.join(PROVIDERS)}")

    models: list[Model] = []
    for name in names:
        model = RemoteModel(PROVIDERS[name], transport=transport)
        if model.available():
            models.append(model)

    if not models:
        wanted = ", ".join(PROVIDERS[name].key_env for name in names)
        raise ProviderError(f"no key set for {spec!r}; expected one of: {wanted}")
    if len(models) == 1:
        return models[0]
    return FallbackChain(models)
