"""Classification prompt: a versioned template rendered with the taxonomy.

The complaint goes in the user message between `<reclamacao>` tags and is never
interpolated into the system prompt, so the instructions stay fixed across
requests and the text is clearly marked as data.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from customer_feedback_ai.labeling.taxonomy import Taxonomy

_TOPICS = "{{TOPICS}}"
_URGENCY = "{{URGENCY}}"


@dataclass(frozen=True)
class ClassificationPrompt:
    version: str
    system: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.system.encode("utf-8")).hexdigest()

    def user_message(self, complaint: str) -> str:
        # A closing tag inside the text would end the data block early.
        safe = complaint.replace("</reclamacao>", "</ reclamacao>")
        return f"<reclamacao>\n{safe}\n</reclamacao>"


def _bullets(labels: list[tuple[str, str]]) -> str:
    return "\n".join(f"- `{label}`: {description}" for label, description in labels)


def render_prompt(template_path: Path, taxonomy: Taxonomy) -> ClassificationPrompt:
    template = template_path.read_text(encoding="utf-8")
    for placeholder in (_TOPICS, _URGENCY):
        if template.count(placeholder) != 1:
            msg = f"{template_path} must contain {placeholder} exactly once"
            raise ValueError(msg)
    system = template.replace(
        _TOPICS, _bullets([(t.id, t.description) for t in taxonomy.topics])
    ).replace(_URGENCY, _bullets([(u.id, u.description) for u in taxonomy.urgency]))
    version = f"{template_path.parent.name}/{template_path.stem}"
    return ClassificationPrompt(version=version, system=system.strip() + "\n")
