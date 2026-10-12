"""Verify the Gemini key, mode and models, then run text, image and function-call round trips.

Usage:
    python scripts/smoke_gemini.py            # full smoke test (text + image + tool call)
    python scripts/smoke_gemini.py --minimal  # just "Reply with OK" on GEMINI_MODEL and GEMINI_FALLBACK_MODEL
    python scripts/smoke_gemini.py --image path/to/plate.jpg

The key is read from .env / the environment and is never printed. Auth mode: tries the Gemini Developer API
first; if that rejects the key (400/401/403) it retries with Vertex AI express mode and tells you which
GEMINI_USE_VERTEX value to set. If a model name is not found, it lists available Flash models.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw

from app.core.config import get_settings
from app.services.llm import gemini_client as gc
from app.services.llm.schemas import ChatHistoryItem, FunctionResult, ToolSpec

OK, FAIL = "OK  ", "FAIL"


def _version_key(name: str) -> tuple[float, ...]:
    nums = re.findall(r"\d+(?:\.\d+)?", name)
    return tuple(float(n) for n in nums) or (0.0,)


def pick_models(names: list[str]) -> tuple[str | None, str | None]:
    """Newest stable-looking Flash and Flash-Lite model names from a list."""
    skip = ("image", "tts", "live", "audio", "embedding", "thinking", "exp", "8b")
    flash = [n for n in names if "flash" in n and "lite" not in n and not any(s in n for s in skip)]
    lite = [n for n in names if "flash-lite" in n and not any(s in n for s in skip)]

    def best(candidates: list[str]) -> str | None:
        stable = [c for c in candidates if "preview" not in c] or candidates
        return max(stable, key=_version_key) if stable else None

    return best(flash), best(lite)


def test_image(path: str | None) -> bytes:
    if path:
        return Path(path).read_bytes()
    img = Image.new("RGB", (512, 512), (240, 236, 228))
    d = ImageDraw.Draw(img)
    d.ellipse((20, 20, 492, 492), fill=(252, 252, 250), outline=(190, 190, 190), width=6)
    d.ellipse((80, 90, 250, 260), fill=(245, 242, 230))  # rice
    d.ellipse((260, 90, 430, 250), fill=(150, 70, 30))  # curry
    for i in range(3):  # rotis
        d.ellipse((120 + i * 30, 280, 300 + i * 30, 440), fill=(215, 170, 110), outline=(160, 110, 60))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


async def detect_mode(key: str, model: str, prefer_vertex: bool, timeout_s: float) -> tuple[bool | None, str]:
    """Return (use_vertex, message). use_vertex None → key rejected in both modes."""
    order = [prefer_vertex, not prefer_vertex]
    errors: list[str] = []
    for use_vertex in order:
        mode = "Vertex AI express" if use_vertex else "Gemini Developer API"
        try:
            text = await gc.ping(key, model=model, use_vertex=use_vertex, timeout_s=timeout_s)
            return use_vertex, f"{mode}: '{text[:40]}'"
        except Exception as exc:
            if gc.is_network_error(exc):
                return None, (
                    f"couldn't reach Google ({gc.describe_error(exc)}). This is a network problem, not the key: "
                    "check this machine's internet connection, proxy or VPN, then run the script again."
                )
            if gc.is_not_found(exc):
                return use_vertex, f"{mode}: key accepted but model '{model}' not found"
            errors.append(f"{mode}: {gc.describe_error(exc)}")
            if not gc.is_auth_error(exc):
                return use_vertex, errors[-1]
    return None, " | ".join(errors)


async def minimal(key: str, use_vertex: bool, models: list[str], timeout_s: float) -> tuple[bool, bool]:
    """Ping each model. Returns (at least one answered, some model name was not found)."""
    any_ok, missing = False, False
    for model in models:
        start = time.perf_counter()
        try:
            text = await gc.ping(key, model=model, use_vertex=use_vertex, timeout_s=timeout_s)
            any_ok = True
            print(f"[{OK}] {model}: '{text[:40]}' ({(time.perf_counter() - start) * 1000:.0f} ms)")
        except Exception as exc:
            missing = missing or gc.is_not_found(exc)
            tag = "FAIL" if gc.is_not_found(exc) else "WARN"
            print(f"[{tag}] {model}: {gc.describe_error(exc)}")
    return any_ok, missing


async def full(settings, image_path: str | None) -> bool:
    client = gc.GeminiClient(settings)
    ctx = "Country: IN\nDiet type: veg\nAllergies: none\nGoal: maintain"
    ok = True

    async def step(name: str, coro):
        nonlocal ok
        start = time.perf_counter()
        try:
            result = await coro
            ms = (time.perf_counter() - start) * 1000
            print(f"[{OK}] {name} — model={client.last_model_used} latency={ms:.0f} ms")
            return result
        except Exception as exc:
            ok = False
            detail = getattr(exc, "message", None) or gc.describe_error(exc)
            print(f"[{FAIL}] {name} — {type(exc).__name__}: {detail}")
            return None

    text = await step("text estimate", client.estimate_from_text("2 roti, dal and a glass of lassi", user_ctx=ctx))
    if text:
        print(
            f"        meal={text.meal_name!r} "
            f"items={[(i.name, i.quantity_g, i.nutrients.calories) for i in text.items]}"
        )

    image = test_image(image_path)
    analysis = await step(
        "image analysis",
        client.analyze_food_image(
            image,
            "image/jpeg",
            hints=[{"label": "chicken_curry", "score": 0.4}],
            user_ctx=ctx,
            description="test plate",
        ),
    )
    if analysis:
        print(
            f"        is_food={analysis.is_food} meal={analysis.meal_name!r} items={[i.name for i in analysis.items]}"
        )

    tool = ToolSpec(
        name="get_daily_intake",
        description="Get what the user ate today: totals and targets.",
        parameters={"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD"}}},
    )
    history = [ChatHistoryItem(role="user", text="How did I do today? Please check my intake first.")]
    system = "You are NutriBuddy, a nutrition assistant. Always call get_daily_intake before answering about today."
    turn = await step("function call (request)", client.chat_turn(system=system, history=history, tools=[tool]))
    if turn is not None:
        if not turn.function_calls:
            ok = False
            print(f"[{FAIL}] model answered without calling the tool: {(turn.text or '')[:80]!r}")
        else:
            fc = turn.function_calls[0]
            print(f"        call={fc.name}({fc.args})")
            history.append(
                ChatHistoryItem(role="model", text=turn.text, function_calls=turn.function_calls, raw=turn.raw)
            )
            fake = {
                "result": {
                    "totals": {"calories": 1250, "protein_g": 38},
                    "targets": {"calories": 2200, "protein_g": 60},
                }
            }
            history.append(
                ChatHistoryItem(role="tool", function_results=[FunctionResult(name=fc.name, response=fake, id=fc.id)])
            )
            final = await step("function call (answer)", client.chat_turn(system=system, history=history, tools=[tool]))
            if final is not None:
                print(f"        answer={(final.text or '')[:120]!r}")
    return ok


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--minimal", action="store_true", help="only send 'Reply with OK' to both models")
    parser.add_argument("--image", help="path to a food photo for the image test")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        print("GEMINI_API_KEY is not set — skipping the live smoke test (use MOCK_AI=true for local development).")
        return 0

    models = [settings.GEMINI_MODEL, settings.GEMINI_FALLBACK_MODEL]
    print(f"Models: primary={models[0]} fallback={models[1]} (key: set, {len(settings.GEMINI_API_KEY)} chars)")
    use_vertex, message = await detect_mode(
        settings.GEMINI_API_KEY, models[0], settings.GEMINI_USE_VERTEX, settings.GEMINI_TIMEOUT_S
    )
    if use_vertex is None:
        if message.startswith("couldn't reach Google"):
            print(f"[{FAIL}] {message}")
        else:
            print(f"[{FAIL}] The key was rejected in both modes: {message}")
        return 1
    mode = "Vertex AI express (GEMINI_USE_VERTEX=true)" if use_vertex else "Developer API (GEMINI_USE_VERTEX=false)"
    print(f"Mode: {mode} — {message}")
    if use_vertex != settings.GEMINI_USE_VERTEX:
        print(f"  → set GEMINI_USE_VERTEX={'true' if use_vertex else 'false'} in .env")
        settings.GEMINI_USE_VERTEX = use_vertex

    any_ok, missing = await minimal(settings.GEMINI_API_KEY, use_vertex, models, settings.GEMINI_TIMEOUT_S)
    if missing or not any_ok:
        try:
            names = await gc.list_model_names(settings.GEMINI_API_KEY, use_vertex=use_vertex)
            flash, lite = pick_models(names)
            print(f"Available Flash models: {sorted(n for n in names if 'flash' in n)}")
            print(f"  → suggested GEMINI_MODEL={flash} GEMINI_FALLBACK_MODEL={lite}")
        except Exception as exc:
            print(f"Could not list models: {gc.describe_error(exc)}")
        return 1
    # A transient 503/429 on one model is fine: the client retries and falls back automatically.
    if args.minimal:
        return 0
    return 0 if await full(settings, args.image) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
