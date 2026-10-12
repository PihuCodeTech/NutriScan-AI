"""HFClassifier wrapper with a fake transformers pipeline (never downloads weights)."""

import pytest

from app.services.classifier import DisabledClassifier, HFClassifier
from tests.conftest import make_jpeg


async def test_hf_classifier_formats_predictions(monkeypatch):
    clf = HFClassifier("nateraw/food", top_k=2)
    calls = {}

    def fake_pipe(img, top_k):
        calls["size"], calls["top_k"] = img.size, top_k
        return [{"label": "butter_chicken", "score": 0.81234}, {"label": "samosa", "score": 0.1}]

    monkeypatch.setattr(clf, "_load_sync", lambda: setattr(clf, "_pipe", fake_pipe))
    assert clf.status == "loading"
    await clf.load()
    assert clf.status == "loaded"
    preds = await clf.predict(make_jpeg())
    assert preds == [
        {"label": "butter_chicken", "display_name": "Butter Chicken", "score": 0.812},
        {"label": "samosa", "display_name": "Samosa", "score": 0.1},
    ]
    assert calls == {"size": (256, 256), "top_k": 2}


async def test_hf_classifier_load_failure_is_non_fatal(monkeypatch):
    clf = HFClassifier("does/not-exist", top_k=3)

    def boom():
        raise OSError("no internet")

    monkeypatch.setattr(clf, "_load_sync", boom)
    await clf.load()
    assert clf.status == "error"
    assert await clf.predict(make_jpeg()) is None


async def test_hf_classifier_predict_failure_returns_none(monkeypatch):
    clf = HFClassifier("x", top_k=3)

    def bad_pipe(img, top_k):
        raise RuntimeError("inference failed")

    monkeypatch.setattr(clf, "_load_sync", lambda: setattr(clf, "_pipe", bad_pipe))
    await clf.load()
    assert await clf.predict(make_jpeg()) is None


@pytest.mark.parametrize("cls", [DisabledClassifier])
async def test_disabled_classifier(cls):
    clf = cls("nateraw/food")
    await clf.load()
    assert clf.status == "disabled" and await clf.predict(b"") is None
