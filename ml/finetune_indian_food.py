"""Fine-tune the Food-101 ViT (`nateraw/food`) further on Indian dishes. Transfer learning, step 2.

Not part of the server; run it on a GPU (Colab / Kaggle). See "Fine-tuning the classifier" in README.md.

Data layout (ImageFolder):   ml/data/indian_food/<class_name>/*.jpg
  e.g. the Kaggle "Indian Food Images" dataset (80 classes). Optionally merge a Food-101 subset with
  --food101-classes N so the model keeps its Western coverage.

Training plan:
  Phase 1 — freeze the ViT encoder, train the new classification head (3 epochs, lr 1e-3).
  Phase 2 — unfreeze the last 4 encoder layers (8 epochs, lr 5e-5, cosine schedule, warmup 0.1,
            label smoothing 0.1).
  Augmentations: RandomResizedCrop(224), RandomHorizontalFlip, ColorJitter.
Reports top-1 / top-5 accuracy and saves to ml/output/indian-food-vit/.

Usage:
  pip install -r requirements.txt datasets accelerate evaluate
  python ml/finetune_indian_food.py --data-dir ml/data/indian_food --food101-classes 20
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch.utils.data import ConcatDataset, Dataset
from torchvision import transforms
from torchvision.datasets import ImageFolder
from transformers import (
    AutoImageProcessor,
    AutoModelForImageClassification,
    Trainer,
    TrainingArguments,
    set_seed,
)

BASE_MODEL = "nateraw/food"
OUTPUT_DIR = Path("ml/output/indian-food-vit")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fine-tune nateraw/food on Indian dishes")
    p.add_argument("--data-dir", default="ml/data/indian_food", help="ImageFolder root: <class>/*.jpg")
    p.add_argument("--food101-classes", type=int, default=0, help="merge N random Food-101 classes (0 = none)")
    p.add_argument("--food101-per-class", type=int, default=150, help="images per merged Food-101 class")
    p.add_argument("--val-split", type=float, default=0.15)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--head-epochs", type=int, default=3)
    p.add_argument("--head-lr", type=float, default=1e-3)
    p.add_argument("--ft-epochs", type=int, default=8)
    p.add_argument("--ft-lr", type=float, default=5e-5)
    p.add_argument("--unfreeze-layers", type=int, default=4)
    p.add_argument("--output-dir", default=str(OUTPUT_DIR))
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


class TransformedSubset(Dataset):
    """A view of (image, label) pairs with its own transform and label remapping."""

    def __init__(self, base: Any, indices: list[int], transform: Any, label_map: dict[int, int] | None = None):
        self.base, self.indices, self.transform, self.label_map = base, indices, transform, label_map

    def __len__(self) -> int:
        return len(self.indices)

    def __getitem__(self, i: int) -> dict[str, Any]:
        image, label = self.base[self.indices[i]]
        if self.label_map is not None:
            label = self.label_map[label]
        return {"pixel_values": self.transform(image.convert("RGB")), "labels": label}


class Food101Subset(Dataset):
    """A few Food-101 classes (Hugging Face `datasets`) exposed as (PIL image, label) pairs."""

    def __init__(self, hf_split: Any, keep: dict[int, int]):
        self.rows = [i for i, lbl in enumerate(hf_split["label"]) if lbl in keep]
        self.split, self.keep = hf_split, keep

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, i: int) -> tuple[Any, int]:
        row = self.split[self.rows[i]]
        return row["image"], self.keep[row["label"]]


def build_transforms(processor: Any) -> tuple[Any, Any]:
    size = processor.size.get("height", 224) if isinstance(processor.size, dict) else 224
    normalize = transforms.Normalize(mean=processor.image_mean, std=processor.image_std)
    train_tf = transforms.Compose(
        [
            transforms.RandomResizedCrop(size, scale=(0.6, 1.0)),
            transforms.RandomHorizontalFlip(),
            transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, hue=0.05),
            transforms.ToTensor(),
            normalize,
        ]
    )
    eval_tf = transforms.Compose(
        [transforms.Resize(int(size * 1.14)), transforms.CenterCrop(size), transforms.ToTensor(), normalize]
    )
    return train_tf, eval_tf


def split_indices(n: int, val_split: float, seed: int) -> tuple[list[int], list[int]]:
    idx = list(range(n))
    random.Random(seed).shuffle(idx)
    cut = int(n * (1 - val_split))
    return idx[:cut], idx[cut:]


def load_data(args: argparse.Namespace, processor: Any) -> tuple[Dataset, Dataset, list[str]]:
    train_tf, eval_tf = build_transforms(processor)
    indian = ImageFolder(args.data_dir)
    class_names = list(indian.classes)
    tr, va = split_indices(len(indian), args.val_split, args.seed)
    train_parts: list[Dataset] = [TransformedSubset(indian, tr, train_tf)]
    val_parts: list[Dataset] = [TransformedSubset(indian, va, eval_tf)]

    if args.food101_classes > 0:
        from datasets import load_dataset  # optional dependency

        food = load_dataset("food101", split="train")
        names = food.features["label"].names
        chosen = random.Random(args.seed).sample(range(len(names)), args.food101_classes)
        keep = {orig: len(class_names) + j for j, orig in enumerate(chosen)}
        class_names += [names[c] for c in chosen]
        subset = Food101Subset(food, keep)
        per_class: dict[int, list[int]] = {}
        for i, row_idx in enumerate(subset.rows):
            per_class.setdefault(food[row_idx]["label"], []).append(i)
        picked = [i for rows in per_class.values() for i in rows[: args.food101_per_class]]
        f_tr, f_va = split_indices(len(picked), args.val_split, args.seed)
        train_parts.append(TransformedSubset(subset, [picked[i] for i in f_tr], train_tf))
        val_parts.append(TransformedSubset(subset, [picked[i] for i in f_va], eval_tf))

    return ConcatDataset(train_parts), ConcatDataset(val_parts), class_names


def compute_metrics(eval_pred: Any) -> dict[str, float]:
    logits, labels = eval_pred
    logits = torch.as_tensor(logits)
    labels = torch.as_tensor(labels)
    top5 = logits.topk(min(5, logits.shape[-1]), dim=-1).indices
    return {
        "top1": (top5[:, 0] == labels).float().mean().item(),
        "top5": (top5 == labels.unsqueeze(-1)).any(dim=-1).float().mean().item(),
    }


def collate(batch: list[dict[str, Any]]) -> dict[str, torch.Tensor]:
    return {
        "pixel_values": torch.stack([b["pixel_values"] for b in batch]),
        "labels": torch.tensor([b["labels"] for b in batch]),
    }


def set_trainable(model: Any, unfreeze_last: int) -> None:
    """Freeze the ViT encoder except the last `unfreeze_last` layers; the head always trains."""
    for p in model.base_model.parameters():
        p.requires_grad = False
    if unfreeze_last > 0:
        for layer in model.base_model.encoder.layer[-unfreeze_last:]:
            for p in layer.parameters():
                p.requires_grad = True
        for p in model.base_model.layernorm.parameters():
            p.requires_grad = True
    for p in model.classifier.parameters():
        p.requires_grad = True
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"trainable parameters: {trainable:,}")


def train_phase(model: Any, args: argparse.Namespace, train_ds: Dataset, val_ds: Dataset, **kw: Any) -> Trainer:
    targs = TrainingArguments(
        output_dir=str(Path(args.output_dir) / f"checkpoints-{kw['name']}"),
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        num_train_epochs=kw["epochs"],
        learning_rate=kw["lr"],
        lr_scheduler_type=kw.get("scheduler", "linear"),
        warmup_ratio=kw.get("warmup", 0.0),
        label_smoothing_factor=kw.get("label_smoothing", 0.0),
        weight_decay=0.01,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=1,
        load_best_model_at_end=True,
        metric_for_best_model="top1",
        remove_unused_columns=False,
        fp16=torch.cuda.is_available(),
        dataloader_num_workers=2,
        report_to="none",
        seed=args.seed,
    )
    trainer = Trainer(
        model=model,
        args=targs,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        data_collator=collate,
        compute_metrics=compute_metrics,
    )
    trainer.train()
    return trainer


def main() -> None:
    args = parse_args()
    set_seed(args.seed)
    np.random.seed(args.seed)
    processor = AutoImageProcessor.from_pretrained(BASE_MODEL)
    train_ds, val_ds, class_names = load_data(args, processor)
    id2label = dict(enumerate(class_names))
    label2id = {v: k for k, v in id2label.items()}
    print(f"classes: {len(class_names)} · train: {len(train_ds)} · val: {len(val_ds)}")

    model = AutoModelForImageClassification.from_pretrained(
        BASE_MODEL,
        num_labels=len(class_names),
        id2label=id2label,
        label2id=label2id,
        ignore_mismatched_sizes=True,  # replace the 101-class head
    )

    print("Phase 1: train the head (encoder frozen)")
    set_trainable(model, unfreeze_last=0)
    train_phase(model, args, train_ds, val_ds, name="head", epochs=args.head_epochs, lr=args.head_lr)

    print(f"Phase 2: unfreeze the last {args.unfreeze_layers} encoder layers")
    set_trainable(model, unfreeze_last=args.unfreeze_layers)
    trainer = train_phase(
        model,
        args,
        train_ds,
        val_ds,
        name="finetune",
        epochs=args.ft_epochs,
        lr=args.ft_lr,
        scheduler="cosine",
        warmup=0.1,
        label_smoothing=0.1,
    )

    metrics = trainer.evaluate()
    print(f"validation top-1: {metrics['eval_top1']:.3f} · top-5: {metrics['eval_top5']:.3f}")
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(out))
    processor.save_pretrained(str(out))
    print(f"saved to {out}")
    print(f"set CLASSIFIER_MODEL_ID={out.as_posix()}")


if __name__ == "__main__":
    main()
