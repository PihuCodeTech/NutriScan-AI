import json

from app.core.errors import AppError


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    events = []
    for block in raw.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def _session(client, headers):
    return (await client.post("/api/v1/chat/sessions", headers=headers, json={})).json()["data"]


async def _stream(client, headers, session_id, text):
    return await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages/stream", headers=headers, data={"text": text}
    )


async def test_stream_event_order(client, auth_headers):
    session = await _session(client, auth_headers)
    r = await _stream(client, auth_headers, session["id"], "Any tips for late-night studying snacks?")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    names = [e for e, _ in events]
    assert names[0] == "user_message"
    assert names[-1] == "done"
    assert set(names[1:-1]) == {"delta"} and len(names[1:-1]) >= 3
    assert events[0][1]["role"] == "user"
    done = events[-1][1]
    assert done["role"] == "assistant"
    assert "".join(d["text"] for e, d in events if e == "delta") == done["content"]

    detail = (await client.get(f"/api/v1/chat/sessions/{session['id']}", headers=auth_headers)).json()["data"]
    assert [m["id"] for m in detail["messages"]] == [events[0][1]["id"], done["id"]]


async def test_stream_with_tool_call(client, auth_headers):
    session = await _session(client, auth_headers)
    r = await _stream(client, auth_headers, session["id"], "How did I do today?")
    events = parse_sse(r.text)
    names = [e for e, _ in events]
    assert names[0] == "user_message" and names[1] == "tool" and names[-1] == "done"
    assert events[1][1] == {"name": "get_daily_intake", "summary": "Checking today's intake…"}
    assert "delta" in names[2:-1]
    done = events[-1][1]
    assert done["tool_calls"][0]["name"] == "get_daily_intake"


async def test_stream_log_meal(client, auth_headers):
    session = await _session(client, auth_headers)
    r = await _stream(client, auth_headers, session["id"], "log a banana as snack")
    events = parse_sse(r.text)
    assert events[1][0] == "tool" and events[1][1]["name"] == "log_meal"
    entries = (await client.get("/api/v1/intake/daily", headers=auth_headers)).json()["data"]["entries"]
    assert entries[0]["source"] == "chat" and entries[0]["meal_type"] == "snack"


async def test_stream_error_saves_no_assistant_message(client, auth_headers, mock_llm):
    mock_llm.queue("chat_stream", AppError("AI_UNAVAILABLE", "The AI service is down.", 503))
    session = await _session(client, auth_headers)
    r = await _stream(client, auth_headers, session["id"], "hello")
    events = parse_sse(r.text)
    assert [e for e, _ in events] == ["user_message", "error"]
    assert events[1][1] == {"code": "AI_UNAVAILABLE", "message": "The AI service is down."}
    detail = (await client.get(f"/api/v1/chat/sessions/{session['id']}", headers=auth_headers)).json()["data"]
    assert [m["role"] for m in detail["messages"]] == ["user"]


async def test_stream_validation_errors_are_json(client, auth_headers, second_user_headers):
    session = await _session(client, auth_headers)
    r = await _stream(client, auth_headers, session["id"], "")
    assert r.status_code == 400 and r.json()["code"] == "EMPTY_MESSAGE"
    r = await _stream(client, second_user_headers, session["id"], "hi")
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"
