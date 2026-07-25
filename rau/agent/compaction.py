"""Context compaction — fold the oldest turns into a summary instead of losing them."""
from __future__ import annotations

import json
from typing import Callable, List, Sequence

from rau.providers.base import Message
from rau.providers.registry import chat_for_slot

#: Takes the transcript of a dropped span, returns a briefing.
Summarizer = Callable[[str], str]

#: Rau carries no tokenizer and is not going to grow one for this. Four
#: characters per token is the usual English/code ratio — an approximation,
#: never an exact count. It reads high on dense JSON, which is the safe
#: direction to be wrong in: over-counting compacts a little early,
#: under-counting overflows the window.
CHARS_PER_TOKEN = 4
#: Role framing and delimiters each message costs on the wire regardless of
#: how short its body is.
PER_MESSAGE_OVERHEAD = 4

#: Context assumed when a caller does not say.
DEFAULT_BUDGET = 100_000
#: Compact once the transcript passes this share of the budget, so there is
#: still room for the system prompt, the tool schemas and the reply.
COMPACT_AT = 0.6
#: Share of the budget the verbatim tail may hold. The gap between this and
#: COMPACT_AT is the headroom a run grows into before compacting again;
#: narrowing it means summarizing far more often.
KEEP_RECENT = 0.3
#: Per-message clamp when rendering a dropped span, so one enormous tool
#: payload cannot crowd fifty turns of reasoning out of the summarizer's view.
SPAN_LINE_LIMIT = 2000
#: Enough for a dense briefing; the slot's own max_tokens is tuned for its
#: normal job, which is not this.
SUMMARY_MAX_TOKENS = 1024

SUMMARY_SYSTEM = (
    "You are compacting the earlier part of a working transcript so it can be "
    "dropped from the context window. The worker will keep reading only what "
    "you write. Produce a dense briefing, no preamble, under these headings:\n"
    "GOAL — the original request, in the terms it was actually asked in.\n"
    "DECISIONS — what was settled, and why.\n"
    "TRIED — each approach attempted, and whether it worked or how it failed.\n"
    "FACTS — paths, names, values and results worth carrying forward.\n"
    "Keep specifics over prose. Never invent anything the transcript does not say."
)

SUMMARY_HEADER = "Summary of earlier conversation (the turns themselves are gone):\n"


def estimate_tokens(text: str) -> int:
    """Approximate token count. See CHARS_PER_TOKEN — this is a heuristic."""
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def message_tokens(m: Message) -> int:
    """Approximate cost of one message, tool plumbing included."""
    total = estimate_tokens(m.content or "") + PER_MESSAGE_OVERHEAD
    for tc in m.tool_calls or []:
        total += estimate_tokens(
            tc.name + json.dumps(tc.arguments, ensure_ascii=False)
        )
    return total


def conversation_tokens(messages: Sequence[Message]) -> int:
    return sum(message_tokens(m) for m in messages)


def should_compact(
    messages: Sequence[Message],
    budget: int = DEFAULT_BUDGET,
    threshold: float = COMPACT_AT,
) -> bool:
    """
    True once the transcript fills `threshold` of the model's window.

    Triggering on tokens rather than a turn count is the whole point: twenty
    turns of small talk cost nothing, while three turns carrying file dumps
    can already be over the line.
    """
    return conversation_tokens(messages) > max(1, int(budget * threshold))


def _head_end(messages: Sequence[Message]) -> int:
    """Index just past the leading system messages, which are never cut."""
    i = 0
    while i < len(messages) and messages[i].role == "system":
        i += 1
    return i


def find_cut_point(
    messages: Sequence[Message],
    *,
    budget: int = DEFAULT_BUDGET,
    keep_ratio: float = KEEP_RECENT,
) -> int:
    """
    First index to keep verbatim; everything from the system prompt to here
    is what a compaction would fold away.

    The boundary may never land inside a tool round. A `tool` message whose
    call ended up on the far side is an orphan, and both wire formats reject
    one outright, so a cut that would sever a round backs up to the assistant
    turn that opened it and keeps the round whole.
    """
    head = _head_end(messages)
    keep = max(1, int(budget * keep_ratio))
    used = 0
    cut = len(messages)
    while cut > head:
        cost = message_tokens(messages[cut - 1])
        # The newest message is kept whatever it costs — a tail of nothing is
        # not a conversation.
        if used and used + cost > keep:
            break
        used += cost
        cut -= 1
    while head < cut < len(messages) and messages[cut].role == "tool":
        cut -= 1
    return cut


def render_span(messages: Sequence[Message]) -> str:
    """Flatten a span of turns into plain transcript text for the summarizer."""
    lines: List[str] = []
    for m in messages:
        body = (m.content or "").strip()
        if m.role == "tool":
            lines.append(f"[result of {m.name or 'tool'}] {body[:SPAN_LINE_LIMIT]}")
            continue
        if body:
            lines.append(f"{m.role}: {body[:SPAN_LINE_LIMIT]}")
        for tc in m.tool_calls or []:
            args = json.dumps(tc.arguments, ensure_ascii=False)[:SPAN_LINE_LIMIT]
            lines.append(f"{m.role} called {tc.name}({args})")
    return "\n".join(lines)


def _is_summary(m: Message) -> bool:
    return m.role == "system" and (m.content or "").startswith(SUMMARY_HEADER)


def compact(
    messages: Sequence[Message],
    summarize: Summarizer,
    *,
    budget: int = DEFAULT_BUDGET,
) -> List[Message]:
    """
    Replace the oldest turns with a single summary, keeping the tail verbatim.

    The summary rides as a system message: both encoders hoist those out of
    the turn sequence, so what the run already learned cannot later be cut in
    half or reordered by a merge.

    There is only ever one of them. A standing summary sits in the head, which
    nothing cuts, so leaving it beside the new one would stack a briefing per
    fold until they crowded out the transcript they were meant to stand in for
    — and a long run folds many times. It is fed back into the summarizer
    instead, and the briefing that comes out supersedes it.

    A summarizer that fails must not take a live conversation with it — the
    span is then dropped unsummarized, which loses exactly what plain
    truncation always lost, and the briefing already standing is left alone.
    """
    msgs = list(messages)
    head = _head_end(msgs)
    cut = find_cut_point(msgs, budget=budget)
    dropped = msgs[head:cut]
    if not dropped:
        return msgs

    span = render_span(dropped)
    standing = [m.content[len(SUMMARY_HEADER) :] for m in msgs[:head] if _is_summary(m)]
    if standing:
        span = "\n".join(standing + [span])

    try:
        summary = (summarize(span) or "").strip()
    except Exception:  # noqa: BLE001 — losing history beats losing the turn
        summary = ""
    if not summary:
        return msgs[:head] + msgs[cut:]

    pinned = [m for m in msgs[:head] if not _is_summary(m)]
    return pinned + [Message(role="system", content=SUMMARY_HEADER + summary)] + msgs[cut:]


def maybe_compact(
    messages: Sequence[Message],
    summarize: Summarizer,
    *,
    budget: int = DEFAULT_BUDGET,
) -> List[Message]:
    """Compact only if the transcript is over budget."""
    if not should_compact(messages, budget):
        return list(messages)
    return compact(messages, summarize, budget=budget)


def provider_summarizer(slot: str = "dream") -> Summarizer:
    """
    A summarizer backed by a model slot.

    Deliberately not the slot doing the work: the face is picked for latency
    and the subagent is mid-thought, whereas `dream` already exists to turn
    long histories into short ones.
    """

    def summarize(transcript: str) -> str:
        provider, cfg = chat_for_slot(slot)
        result = provider.chat(
            [
                Message(role="system", content=SUMMARY_SYSTEM),
                Message(role="user", content=transcript),
            ],
            model=cfg.get("model") or "deepseek/deepseek-v4-flash",
            max_tokens=SUMMARY_MAX_TOKENS,
            temperature=0.2,
            effort=str(cfg.get("effort") or "medium"),
        )
        return (result.content or "").strip()

    return summarize
