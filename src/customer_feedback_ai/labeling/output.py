"""Schema and validation of the label an LLM returns.

The schema goes to the API as structured output, and every reply is validated
again here: an answer outside the taxonomy is rejected, never coerced.
"""

import json
from dataclasses import dataclass
from typing import Any

from customer_feedback_ai.labeling.taxonomy import Taxonomy


class LabelParseError(ValueError):
    """The reply is not a valid label."""


@dataclass(frozen=True)
class TopicUrgency:
    topic: str
    urgency: str


def label_json_schema(taxonomy: Taxonomy) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "enum": list(taxonomy.topic_ids)},
            "urgency": {"type": "string", "enum": list(taxonomy.urgency_ids)},
        },
        "required": ["topic", "urgency"],
        "additionalProperties": False,
    }


def parse_label(text: str | None, taxonomy: Taxonomy) -> TopicUrgency:
    if not text:
        raise LabelParseError("empty reply")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise LabelParseError(f"invalid JSON: {error.msg}") from None
    if not isinstance(data, dict) or set(data) != {"topic", "urgency"}:
        raise LabelParseError("reply must be an object with exactly topic and urgency")
    topic, urgency = data["topic"], data["urgency"]
    if topic not in taxonomy.topic_ids:
        raise LabelParseError(f"unknown topic {topic!r}")
    if urgency not in taxonomy.urgency_ids:
        raise LabelParseError(f"unknown urgency {urgency!r}")
    return TopicUrgency(topic=topic, urgency=urgency)
