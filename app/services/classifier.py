"""Transfer-learned food classifier (ViT fine-tuned on Food-101) used as weak hints for Gemini."""

from __future__ import annotations

import io
import logging
import time
from typing import Any, Protocol

from anyio import to_thread
from PIL import Image

from app.core.metrics import metrics

logger = logging.getLogger(__name__)

MOCK_PREDICTIONS = [
    {"label": "chicken_curry", "score": 0.62},
    {"label": "samosa", "score": 0.11},
    {"label": "falafel", "score": 0.05},
]


def _format(preds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "label": str(p["label"]),
            "display_name": str(p["label"]).replace("_", " ").title(),
            "score": round(float(p["score"]), 3),
        }
        for p in preds
    ]


class Classifier(Protocol):
    model_id: str

    @property
    def status(self) -> str: ...  # "loading" | "loaded" | "disabled" | "error"

    async def load(self) -> None: ...

    async def predict(self, image_bytes: bytes) -> list[dict[str, Any]] | None: ...


class HFClassifier:
    """Hugging Face `image-classification` pipeline on CPU. Loaded once; inference in a thread."""

    def __init__(self, model_id: str, top_k: int) -> None:
        self.model_id = model_id
        self.top_k = top_k
        self._pipe: Any = None
        self._status = "loading"  # load() runs in the background right after startup

    @property
    def status(self) -> str:
        return self._status

    def _load_sync(self) -> None:
        from transformers import pipeline  # heavy import, only when the real classifier is used

        self._pipe = pipeline("image-classification", model=self.model_id, device=-1)

    async def load(self) -> None:
        start = time.perf_counter()
        self._status = "loading"
        try:
            await to_thread.run_sync(self._load_sync)
            self._status = "loaded"
            logger.info(
                "classifier loaded",
                extra={"model": self.model_id, "load_ms": round((time.perf_counter() - start) * 1000)},
            )
        except Exception as exc:
            self._status = "error"
            logger.warning("classifier failed to load; scans continue without hints", extra={"error": str(exc)})

    def _predict_sync(self, image_bytes: bytes) -> list[dict[str, Any]]:
        with Image.open(io.BytesIO(image_bytes)) as img:
            preds = self._pipe(img.convert("RGB"), top_k=self.top_k)
        return _format(preds)

    async def predict(self, image_bytes: bytes) -> list[dict[str, Any]] | None:
        if self._status != "loaded":
            return None
        try:
            return await to_thread.run_sync(self._predict_sync, image_bytes)
        except Exception as exc:
            metrics.inc("classifier_failures_total")
            logger.warning("classifier prediction failed", extra={"error": str(exc)})
            return None


class MockClassifier:
    """Deterministic predictions; never downloads weights."""

    def __init__(self, model_id: str = "nateraw/food", top_k: int = 3) -> None:
        self.model_id = model_id
        self.top_k = top_k
        self.calls = 0

    @property
    def status(self) -> str:
        return "loaded"

    async def load(self) -> None:
        return None

    async def predict(self, image_bytes: bytes) -> list[dict[str, Any]] | None:
        self.calls += 1
        return _format(MOCK_PREDICTIONS[: self.top_k])


class DisabledClassifier:
    """Used when CLASSIFIER_ENABLED=false: scans skip hints."""

    def __init__(self, model_id: str = "") -> None:
        self.model_id = model_id

    @property
    def status(self) -> str:
        return "disabled"

    async def load(self) -> None:
        return None

    async def predict(self, image_bytes: bytes) -> list[dict[str, Any]] | None:
        return None
