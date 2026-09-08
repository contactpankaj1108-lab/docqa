"""Answer generation on top of the Claude Messages API.

The model gets numbered excerpts and must answer from those alone, citing the
numbers it used. Without credentials configured we fall back to an extractive
answer built from the same passages rather than failing the request.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .textutils import STOPWORDS, tokenize

logger = logging.getLogger(__name__)

# Opus 5 supports server-side refusal fallbacks; the request is retried without
# them if the installed SDK or endpoint does not recognise the parameter.
SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """You answer questions about an organisation's internal documents.

You will be given numbered excerpts retrieved from those documents, then a question.

Rules:
- Answer using the excerpts only. Never use outside knowledge, and never guess.
- Cite the excerpt numbers you actually used, in square brackets, immediately after the
  statement they support: "Interns report to a mentor [2]."
- If the excerpts do not contain the answer, say plainly that the documents do not cover
  it, and name the closest topic they do cover. Do not pad this with speculation.
- If the excerpts disagree, say so and cite both.
- Be concise and direct. Lead with the answer. Use a short bulleted list when the answer
  is genuinely a list (responsibilities, steps, requirements); otherwise use prose.
- Match the question's language and terminology to the documents' own wording.
- Do not describe the retrieval process or refer to "excerpts", "chunks" or "context" in
  your answer - just answer, with citations."""

CONDENSE_PROMPT = """Rewrite the user's latest question as a standalone search query.

Resolve pronouns and elliptical references using the conversation, keep every specific
noun and constraint, and add nothing that was not asked. Reply with the rewritten
question only - no preamble, no quotes."""


@dataclass
class AnswerResult:
    text: str
    mode: str  # "generated" | "extractive"
    model: str | None = None
    cited: list[int] = field(default_factory=list)
    usage: dict | None = None
    warning: str | None = None


class GenerationError(RuntimeError):
    """A model call failed in a way the caller should surface to the user."""


def format_context(blocks: list[dict]) -> str:
    """Render retrieved passages as numbered, attributed excerpts."""
    rendered = []
    for index, block in enumerate(blocks, start=1):
        location = block["filename"]
        if block.get("page"):
            location += ", page {}".format(block["page"])
        body = block["text"]
        rendered.append(f"[{index}] ({location})\n{body}")
    return "\n\n".join(rendered)


def parse_citations(text: str, limit: int) -> list[int]:
    """Pull the excerpt numbers the answer actually cited."""
    found: list[int] = []
    for match in re.finditer(r"\[(\d+(?:\s*,\s*\d+)*)\]", text):
        for part in match.group(1).split(","):
            try:
                number = int(part.strip())
            except ValueError:
                continue
            if 1 <= number <= limit and number not in found:
                found.append(number)
    return found


class AnswerGenerator:
    """Wraps the Anthropic client, with an extractive fallback when absent."""

    def __init__(self, *, model: str, max_tokens: int, effort: str, server_fallback: bool) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        self._server_fallback = server_fallback
        self._client = None
        self._unavailable_reason: str | None = None

        try:
            import anthropic
        except ImportError:
            self._unavailable_reason = "The 'anthropic' package is not installed."
            return

        self._anthropic = anthropic
        try:
            # Resolves ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an `ant auth
            # login` profile.
            client = anthropic.Anthropic(max_retries=2, timeout=120.0)
        except Exception as exc:
            self._unavailable_reason = (
                f"Could not create the Anthropic client ({type(exc).__name__})."
            )
            logger.info("Running without generative answers: %s", self._unavailable_reason)
            return

        # The client constructs happily with no credentials and only fails at
        # request time, so probe for one now - otherwise /api/stats would claim
        # generated answers that every question then fails to produce.
        if _has_credentials(client):
            self._client = client
        else:
            self._unavailable_reason = (
                "No Anthropic credentials found. Set ANTHROPIC_API_KEY (or run `ant auth login`) "
                "for generated answers; retrieval still works without it."
            )
            logger.info("Running without generative answers: %s", self._unavailable_reason)

    @property
    def available(self) -> bool:
        return self._client is not None

    @property
    def unavailable_reason(self) -> str | None:
        return self._unavailable_reason

    # -- request plumbing -------------------------------------------------

    def _request_kwargs(
        self, *, system: str, messages: list[dict], max_tokens: int, effort: str
    ) -> dict:
        return {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "output_config": {"effort": effort},
        }

    def _create(self, **kwargs):
        """Send a message, preferring the beta endpoint with refusal fallbacks."""
        if self._server_fallback:
            try:
                return self._client.beta.messages.create(
                    betas=[SERVER_FALLBACK_BETA], fallbacks="default", **kwargs
                )
            except (
                TypeError,
                self._anthropic.BadRequestError,
                self._anthropic.NotFoundError,
            ) as exc:
                logger.warning("Server-side fallbacks unavailable (%s); retrying without.", exc)
                self._server_fallback = False
        return self._client.messages.create(**kwargs)

    def _stream(self, **kwargs):
        if self._server_fallback:
            try:
                return self._client.beta.messages.stream(
                    betas=[SERVER_FALLBACK_BETA], fallbacks="default", **kwargs
                )
            except (
                TypeError,
                self._anthropic.BadRequestError,
                self._anthropic.NotFoundError,
            ) as exc:
                logger.warning("Server-side fallbacks unavailable (%s); retrying without.", exc)
                self._server_fallback = False
        return self._client.messages.stream(**kwargs)

    def _describe_error(self, exc: Exception) -> str:
        anthropic = self._anthropic
        if isinstance(exc, anthropic.AuthenticationError):
            return "The Anthropic API rejected the credentials. Check ANTHROPIC_API_KEY."
        if isinstance(exc, anthropic.PermissionDeniedError):
            return "The API key lacks permission for this model."
        if isinstance(exc, anthropic.NotFoundError):
            return f"Model '{self.model}' was not found for this account."
        if isinstance(exc, anthropic.RateLimitError):
            retry_after = "60"
            response = getattr(exc, "response", None)
            if response is not None:
                retry_after = response.headers.get("retry-after", "60")
            return f"Rate limited by the Anthropic API. Retry in {retry_after}s."
        if isinstance(exc, anthropic.APIStatusError):
            if exc.status_code >= 500:
                return (
                    f"The Anthropic API returned a server error ({exc.status_code}). Retry shortly."
                )
            return f"The Anthropic API rejected the request: {exc.message}"
        if isinstance(exc, anthropic.APIConnectionError):
            return "Could not reach the Anthropic API. Check network connectivity."
        return f"Answer generation failed: {exc}"

    # -- public API -------------------------------------------------------

    def condense(self, question: str, history: list[dict]) -> str:
        """Turn a follow-up into a standalone query. Best-effort only."""
        if not history or not self.available:
            return question
        transcript = "\n".join(
            "{}: {}".format(turn.get("role", "user").upper(), turn.get("content", ""))
            for turn in history[-6:]
        )
        try:
            response = self._create(
                **self._request_kwargs(
                    system=CONDENSE_PROMPT,
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                f"Conversation so far:\n{transcript}\n\nLatest question: {question}"
                            ),
                        }
                    ],
                    max_tokens=300,
                    effort="low",
                )
            )
        except Exception as exc:
            logger.warning("Question condensation failed, using the raw question: %s", exc)
            return question

        rewritten = _first_text(response).strip()
        # A rewrite that collapses or explodes is worse than the original.
        if not rewritten or len(rewritten) > 400:
            return question
        return rewritten

    def answer(
        self, question: str, blocks: list[dict], history: list[dict] | None = None
    ) -> AnswerResult:
        if not self.available:
            return extractive_answer(question, blocks, reason=self._unavailable_reason)

        messages = _build_messages(question, blocks, history)
        try:
            response = self._create(
                **self._request_kwargs(
                    system=SYSTEM_PROMPT,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    effort=self.effort,
                )
            )
        except TypeError as exc:
            # The SDK raises TypeError when it cannot resolve any credential.
            # Degrade rather than failing the request.
            self._client = None
            self._unavailable_reason = f"Anthropic credentials could not be resolved ({exc})."
            logger.warning("Falling back to extractive answers: %s", exc)
            return extractive_answer(question, blocks, reason=self._unavailable_reason)
        except Exception as exc:
            raise GenerationError(self._describe_error(exc)) from exc

        if getattr(response, "stop_reason", None) == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) or "unspecified"
            raise GenerationError(f"The model declined to answer this request ({category}).")

        text = _first_text(response).strip()
        if not text:
            return extractive_answer(
                question, blocks, reason="The model returned an empty response."
            )

        usage = getattr(response, "usage", None)
        return AnswerResult(
            text=text,
            mode="generated",
            model=self.model,
            cited=parse_citations(text, len(blocks)),
            usage={
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
            }
            if usage
            else None,
        )

    def answer_stream(
        self, question: str, blocks: list[dict], history: list[dict] | None = None
    ) -> Iterator[str]:
        """Yield answer text incrementally, for the streaming endpoint."""
        if not self.available:
            yield extractive_answer(question, blocks, reason=self._unavailable_reason).text
            return

        messages = _build_messages(question, blocks, history)
        try:
            with self._stream(
                **self._request_kwargs(
                    system=SYSTEM_PROMPT,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    effort=self.effort,
                )
            ) as stream:
                yield from stream.text_stream
                final = stream.get_final_message()
                if getattr(final, "stop_reason", None) == "refusal":
                    raise GenerationError("The model declined to answer this request.")
        except GenerationError:
            raise
        except Exception as exc:
            raise GenerationError(self._describe_error(exc)) from exc


def _has_credentials(client) -> bool:
    """Best-effort check that *some* credential source is configured."""
    if getattr(client, "api_key", None) or getattr(client, "auth_token", None):
        return True
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return True
    if os.getenv("ANTHROPIC_FEDERATION_RULE_ID") and os.getenv("ANTHROPIC_SERVICE_ACCOUNT_ID"):
        return True
    # An `ant auth login` profile, which the SDK resolves internally.
    return (Path.home() / ".config" / "anthropic").exists()


def _build_messages(question: str, blocks: list[dict], history: list[dict] | None) -> list[dict]:
    messages: list[dict] = []
    for turn in (history or [])[-6:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    # Conversations must start with a user turn.
    while messages and messages[0]["role"] != "user":
        messages.pop(0)

    messages.append(
        {
            "role": "user",
            "content": f"Excerpts:\n\n{format_context(blocks)}\n\nQuestion: {question}",
        }
    )
    return messages


def _first_text(response) -> str:
    parts = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts)


def extractive_answer(
    question: str, blocks: list[dict], *, reason: str | None = None
) -> AnswerResult:
    """Answer without a model by quoting the best-matching sentences."""
    if not blocks:
        return AnswerResult(
            text="No relevant passage was found in the uploaded documents.",
            mode="extractive",
            warning=reason,
        )

    query_terms = {term for term in tokenize(question) if term not in STOPWORDS}
    # One shared term is only evidence when the question is very short;
    # otherwise it matches headings and boilerplate.
    min_overlap = 2 if len(query_terms) >= 3 else 1

    scored: list[tuple[float, int, str]] = []
    for index, block in enumerate(blocks[:4], start=1):
        for sentence in re.split(r"(?<=[.!?])\s+", block["text"]):
            sentence = sentence.strip()
            if len(sentence.split()) < 8:
                continue
            terms = set(tokenize(sentence))
            overlap = len(query_terms & terms)
            if overlap < min_overlap:
                continue
            # Favour sentences dense in query terms, from better-ranked blocks.
            density = overlap / (1 + len(terms) ** 0.5)
            scored.append((density / index**0.5, index, sentence))

    scored.sort(reverse=True, key=lambda item: item[0])
    picked = scored[:3]
    if not picked:
        picked = [(0.0, 1, blocks[0]["text"][:400])]

    lines = [f"{sentence.rstrip()} [{index}]" for _, index, sentence in picked]
    warning = reason or "Generated answers are disabled; showing the closest passages instead."
    return AnswerResult(
        text="\n\n".join(lines),
        mode="extractive",
        cited=sorted({index for _, index, _ in picked}),
        warning=warning,
    )
