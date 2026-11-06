"""C3: BERTimbau fine-tuned with two heads, topic and urgency (AGENTS.md, section 8).

- One encoder, two linear heads on the [CLS] vector, trained together with the
  sum of the two cross-entropy losses (class-balanced by default, as in C1).
- Inputs are cut at `max_length` tokens (256 by default). The model records how
  many texts were cut in each set.
- Training may use the maintainer's GPU, with fp16. Early stopping keeps the
  epoch with the best topic macro-F1 on `silver_val`. After training the model
  moves to the CPU, where its quality and inference cost are measured.
- Seeds are fixed, but GPU kernels are not bit-for-bit deterministic, so two
  trainings may differ slightly; the report records the device.

The fine-tuned weights are derived from the corpus and stay in the local data
directory; they are never published (G1).
"""

import json
import math
import random
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn
from transformers import AutoModel, AutoTokenizer, get_linear_schedule_with_warmup

from customer_feedback_ai.evaluation.metrics import macro_f1
from customer_feedback_ai.models.base import LabeledTexts
from customer_feedback_ai.models.config import C3Config
from customer_feedback_ai.models.embeddings import quiet_hf


class TwoHeadClassifier(nn.Module):
    def __init__(self, encoder: Any, n_topics: int, n_urgency: int, dropout: float):
        super().__init__()
        self.encoder = encoder
        hidden = int(encoder.config.hidden_size)
        self.dropout = nn.Dropout(dropout)
        self.topic = nn.Linear(hidden, n_topics)
        self.urgency = nn.Linear(hidden, n_urgency)

    def forward(self, input_ids: Any, attention_mask: Any) -> tuple[Any, Any]:
        output = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        cls = self.dropout(output.last_hidden_state[:, 0])
        return self.topic(cls), self.urgency(cls)


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def resolve_device(choice: str) -> torch.device:
    if choice == "cuda" and not torch.cuda.is_available():
        msg = "configs/train.yaml asks for c3.device=cuda, but PyTorch sees no GPU"
        raise RuntimeError(msg)
    if choice == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(choice)


def balanced_weights(indices: Sequence[int], classes: int) -> torch.Tensor:
    """n / (classes * count), as scikit-learn's class_weight='balanced'."""
    counts = np.bincount(np.asarray(indices), minlength=classes).astype(np.float64)
    weights = len(indices) / (classes * np.maximum(counts, 1.0))
    return torch.tensor(weights, dtype=torch.float32)


class BertTwoHeads:
    name = "c3"

    def __init__(self, config: C3Config, seed: int):
        self.config = config
        self.seed = seed
        self.net: TwoHeadClassifier | None = None
        self.tokenizer: Any = None
        self.topic_labels: list[str] = []
        self.urgency_labels: list[str] = []
        self.truncation: dict[str, int] = {}
        self.train_info: dict[str, Any] = {}
        self.history: list[dict[str, Any]] = []

    # --- tokens ----------------------------------------------------------------

    def _truncated(self, texts: Sequence[str]) -> int:
        lengths = self.tokenizer(list(texts), add_special_tokens=True, truncation=False)
        return sum(len(ids) > self.config.max_length for ids in lengths["input_ids"])

    def _batch(self, texts: Sequence[str], device: torch.device) -> Any:
        return self.tokenizer(
            list(texts),
            truncation=True,
            max_length=self.config.max_length,
            padding=True,
            return_tensors="pt",
        ).to(device)

    def _logits(
        self, net: TwoHeadClassifier, texts: Sequence[str], device: torch.device
    ) -> tuple[list[int], list[int]]:
        net.eval()
        topics: list[int] = []
        urgencies: list[int] = []
        amp = device.type == "cuda" and self.config.fp16
        size = self.config.eval_batch_size
        with torch.no_grad():
            for start in range(0, len(texts), size):
                batch = self._batch(texts[start : start + size], device)
                with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=amp):
                    topic, urgency = net(batch["input_ids"], batch["attention_mask"])
                topics += topic.argmax(dim=-1).tolist()
                urgencies += urgency.argmax(dim=-1).tolist()
        return topics, urgencies

    # --- training --------------------------------------------------------------

    def fit(self, train: LabeledTexts, val: LabeledTexts | None = None) -> None:
        quiet_hf()
        cfg = self.config
        seed_everything(self.seed)
        device = resolve_device(cfg.device)
        self.tokenizer = AutoTokenizer.from_pretrained(cfg.encoder, revision=cfg.revision)
        encoder = AutoModel.from_pretrained(cfg.encoder, revision=cfg.revision)
        self.topic_labels = sorted(set(train.topics))
        self.urgency_labels = sorted(set(train.urgencies))
        topic_index = {label: i for i, label in enumerate(self.topic_labels)}
        urgency_index = {label: i for i, label in enumerate(self.urgency_labels)}
        y_topic = [topic_index[label] for label in train.topics]
        y_urgency = [urgency_index[label] for label in train.urgencies]
        has_val = val is not None and len(val) > 0

        self.truncation = {"train": self._truncated(train.texts), "train_total": len(train)}
        if has_val and val is not None:
            self.truncation |= {"val": self._truncated(val.texts), "val_total": len(val)}

        net = TwoHeadClassifier(
            encoder, len(self.topic_labels), len(self.urgency_labels), cfg.dropout
        ).to(device)
        balanced = cfg.class_weight == "balanced"
        topic_loss = nn.CrossEntropyLoss(
            weight=balanced_weights(y_topic, len(self.topic_labels)).to(device)
            if balanced
            else None
        )
        urgency_loss = nn.CrossEntropyLoss(
            weight=balanced_weights(y_urgency, len(self.urgency_labels)).to(device)
            if balanced
            else None
        )
        y_topic_t = torch.tensor(y_topic, device=device)
        y_urgency_t = torch.tensor(y_urgency, device=device)

        n = len(train)
        batches = math.ceil(n / cfg.batch_size)
        total_steps = math.ceil(batches / cfg.grad_accumulation) * cfg.epochs
        optimizer = torch.optim.AdamW(
            net.parameters(), lr=cfg.learning_rate, weight_decay=cfg.weight_decay
        )
        scheduler = get_linear_schedule_with_warmup(
            optimizer, int(cfg.warmup_ratio * total_steps), total_steps
        )
        amp = cfg.fp16 and device.type == "cuda"
        scaler = torch.amp.GradScaler("cuda", enabled=amp)
        generator = torch.Generator().manual_seed(self.seed)
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)

        best_score = -1.0
        best_state: dict[str, Any] | None = None
        best_epoch = 0
        stale = 0
        self.history = []
        for epoch in range(1, cfg.epochs + 1):
            net.train()
            order = torch.randperm(n, generator=generator).tolist()
            optimizer.zero_grad()
            losses: list[float] = []
            for step, start in enumerate(range(0, n, cfg.batch_size), 1):
                idx = order[start : start + cfg.batch_size]
                batch = self._batch([train.texts[i] for i in idx], device)
                with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=amp):
                    topic, urgency = net(batch["input_ids"], batch["attention_mask"])
                    loss = topic_loss(topic.float(), y_topic_t[idx]) + urgency_loss(
                        urgency.float(), y_urgency_t[idx]
                    )
                scaler.scale(loss / cfg.grad_accumulation).backward()
                losses.append(float(loss.detach()))
                if step % cfg.grad_accumulation == 0 or step == batches:
                    scaler.unscale_(optimizer)
                    nn.utils.clip_grad_norm_(net.parameters(), 1.0)
                    scaler.step(optimizer)
                    scaler.update()
                    optimizer.zero_grad()
                    scheduler.step()

            score: float | None = None
            if has_val and val is not None:
                predicted, _ = self._logits(net, val.texts, device)
                score = macro_f1(val.topics, [self.topic_labels[i] for i in predicted]) or 0.0
            self.history.append(
                {"epoch": epoch, "train_loss": float(np.mean(losses)), "val_topic_macro_f1": score}
            )
            if score is None or score > best_score:
                best_score = score if score is not None else best_score
                best_state = {
                    k: v.detach().to("cpu", copy=True) for k, v in net.state_dict().items()
                }
                best_epoch = epoch
                stale = 0
            else:
                stale += 1
                if stale > cfg.patience:
                    break

        assert best_state is not None
        net.load_state_dict(best_state)
        self.train_info = {
            "device": device.type,
            "gpu": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
            "gpu_peak_bytes": torch.cuda.max_memory_allocated(device)
            if device.type == "cuda"
            else None,
            "fp16": amp,
            "epochs_run": len(self.history),
            "best_epoch": best_epoch,
            "base_commit": getattr(encoder.config, "_commit_hash", None),
        }
        self.net = net.to("cpu").eval()

    # --- inference -------------------------------------------------------------

    def predict(self, texts: Sequence[str]) -> tuple[list[str], list[str]]:
        if self.net is None:
            msg = "fit the model before predicting"
            raise RuntimeError(msg)
        topics, urgencies = self._logits(self.net, texts, torch.device("cpu"))
        return (
            [self.topic_labels[i] for i in topics],
            [self.urgency_labels[i] for i in urgencies],
        )

    def params(self) -> dict[str, Any]:
        cfg = self.config
        shares = {
            f"truncated_share_{key}": self.truncation[key] / self.truncation[f"{key}_total"]
            for key in ("train", "val")
            if self.truncation.get(f"{key}_total")
        }
        return {
            "encoder": cfg.encoder,
            "encoder_revision": cfg.revision,
            "max_length": cfg.max_length,
            "batch_size": cfg.batch_size,
            "grad_accumulation": cfg.grad_accumulation,
            "learning_rate": cfg.learning_rate,
            "epochs": cfg.epochs,
            "patience": cfg.patience,
            "class_weight": cfg.class_weight,
            **self.train_info,
            **{f"truncated_{k}": v for k, v in self.truncation.items()},
            **shares,
            "history": self.history,
        }

    # --- persistence -----------------------------------------------------------

    def save(self, path: Path) -> None:
        if self.net is None:
            msg = "fit the model before saving"
            raise RuntimeError(msg)
        path.mkdir(parents=True, exist_ok=True)
        self.net.encoder.save_pretrained(path / "encoder")
        self.tokenizer.save_pretrained(path / "encoder")
        torch.save(
            {"topic": self.net.topic.state_dict(), "urgency": self.net.urgency.state_dict()},
            path / "heads.pt",
        )
        meta = {
            "config": self.config.model_dump(mode="json"),
            "seed": self.seed,
            "topic_labels": self.topic_labels,
            "urgency_labels": self.urgency_labels,
            "truncation": self.truncation,
            "train_info": self.train_info,
            "history": self.history,
        }
        (path / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "BertTwoHeads":
        quiet_hf()
        meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        model = cls(C3Config.model_validate(meta["config"]), int(meta["seed"]))
        model.topic_labels, model.urgency_labels = meta["topic_labels"], meta["urgency_labels"]
        model.truncation, model.train_info = meta["truncation"], meta["train_info"]
        model.history = meta["history"]
        model.tokenizer = AutoTokenizer.from_pretrained(path / "encoder")
        encoder = AutoModel.from_pretrained(path / "encoder")
        net = TwoHeadClassifier(
            encoder, len(model.topic_labels), len(model.urgency_labels), model.config.dropout
        )
        heads = torch.load(path / "heads.pt", map_location="cpu", weights_only=True)
        net.topic.load_state_dict(heads["topic"])
        net.urgency.load_state_dict(heads["urgency"])
        model.net = net.eval()
        return model
