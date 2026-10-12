from app.core.errors import AppError
from app.services.llm.schemas import ChatTurn, FunctionCall
from tests.conftest import create_scan, make_jpeg


async def _session(client, headers, **body):
    r = await client.post("/api/v1/chat/sessions", headers=headers, json=body)
    assert r.status_code == 201, r.text
    assert r.json()["code"] == "CHAT_CREATED"
    return r.json()["data"]


async def _send(client, headers, session_id, text=None, image=None):
    files = {"image": ("food.jpg", image, "image/jpeg")} if image else None
    data = {"text": text} if text is not None else {}
    return await client.post(f"/api/v1/chat/sessions/{session_id}/messages", headers=headers, data=data, files=files)


async def test_create_session_with_and_without_scan(client, auth_headers, sample_jpeg, mock_llm):
    plain = await _session(client, auth_headers)
    assert plain["title"] == "New chat" and plain["scan_id"] is None

    scan = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]
    linked = await _session(client, auth_headers, title="About lunch", scan_id=scan["id"])
    assert linked["scan_id"] == scan["id"] and linked["title"] == "About lunch"

    # the linked scan is in the system instruction
    await _send(client, auth_headers, linked["id"], "Is this enough protein for me?")
    system = mock_llm.last_kwargs["chat_turn"]["system"]
    assert "Rajma Chawal Plate" in system and "LINKED MEAL" in system
    assert "NutriBuddy" in system

    r = await client.post("/api/v1/chat/sessions", headers=auth_headers, json={"scan_id": "not-a-real-scan"})
    assert r.status_code == 404


async def test_send_text_reply_saved_and_auto_title(client, auth_headers):
    session = await _session(client, auth_headers)
    r = await _send(client, auth_headers, session["id"], "What are cheap high protein foods in a hostel mess?")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["code"] == "MESSAGE_CREATED"
    user_msg, assistant = body["data"]["user_message"], body["data"]["assistant_message"]
    assert user_msg["role"] == "user" and user_msg["tool_calls"] is None
    assert assistant["role"] == "assistant" and assistant["content"]
    assert assistant["tool_calls"] is None

    detail = (await client.get(f"/api/v1/chat/sessions/{session['id']}", headers=auth_headers)).json()["data"]
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["session"]["title"] == "What are cheap high protein foods…"
    assert detail["session"]["last_message_preview"]

    listing = (await client.get("/api/v1/chat/sessions", headers=auth_headers)).json()["data"]
    assert listing["total"] == 1
    flat = assistant["content"].replace("\n", " ")
    assert listing["items"][0]["last_message_preview"] == flat[:120] + ("…" if len(flat) > 120 else "")


async def test_today_question_triggers_get_daily_intake(client, auth_headers, mock_llm):
    session = await _session(client, auth_headers)
    r = await _send(client, auth_headers, session["id"], "How did I do today?")
    assistant = r.json()["data"]["assistant_message"]
    assert assistant["tool_calls"][0]["name"] == "get_daily_intake"
    assert assistant["tool_calls"][0]["summary"].startswith("Checked your intake for")
    assert "result" not in assistant["tool_calls"][0]  # raw payload is not exposed
    assert "kcal" in assistant["content"]
    assert mock_llm.calls["chat_turn"] == 2


async def test_log_message_creates_chat_intake_entry(client, auth_headers):
    session = await _session(client, auth_headers)
    r = await _send(client, auth_headers, session["id"], "log 2 roti and dal for dinner")
    assistant = r.json()["data"]["assistant_message"]
    trace = assistant["tool_calls"][0]
    assert trace["name"] == "log_meal"
    assert trace["args"] == {"description": "2 roti and dal", "meal_type": "dinner"}
    assert trace["summary"].startswith("Logged ") and trace["summary"].endswith("to your dinner")
    daily = (await client.get("/api/v1/intake/daily", headers=auth_headers)).json()["data"]
    assert len(daily["entries"]) == 1
    entry = daily["entries"][0]
    assert entry["source"] == "chat" and entry["meal_type"] == "dinner"
    assert [i["name"] for i in entry["items"]] == ["Roti", "Dal"]


async def test_image_message_stored_with_url(client, auth_headers, mock_llm):
    session = await _session(client, auth_headers)
    r = await _send(client, auth_headers, session["id"], image=make_jpeg())
    assert r.status_code == 201, r.text
    user_msg = r.json()["data"]["user_message"]
    assert user_msg["image_url"].startswith("http://testserver/api/v1/media/")
    assert (await client.get(user_msg["image_url"].replace("http://testserver", ""))).status_code == 200
    history = mock_llm.last_kwargs["chat_turn"]["history"]
    assert history[-1].image is not None and history[-1].image_mime == "image/jpeg"
    detail = (await client.get(f"/api/v1/chat/sessions/{session['id']}", headers=auth_headers)).json()["data"]
    assert detail["session"]["title"] == "Food photo"

    # on the next turn the old photo becomes a text marker, only the current message may carry bytes
    await _send(client, auth_headers, session["id"], "thanks!")
    history = mock_llm.last_kwargs["chat_turn"]["history"]
    assert history[0].image is None and history[0].text.startswith("[user shared a photo]")
    assert history[-1].image is None


async def test_history_limit_respected(client, auth_headers, mock_llm, settings, monkeypatch):
    monkeypatch.setattr(settings, "CHAT_HISTORY_TURNS", 4)
    session = await _session(client, auth_headers)
    for i in range(4):
        await _send(client, auth_headers, session["id"], f"question number {i}")
    history = mock_llm.last_kwargs["chat_turn"]["history"]
    assert len(history) == 4
    assert history[-1].role == "user" and history[-1].text == "question number 3"
    # window = [assistant 1, user 2, assistant 2, user 3]
    assert [h.role for h in history] == ["model", "user", "model", "user"]
    assert history[1].text == "question number 2"


async def test_tool_loop_limit_then_final_answer_without_tools(client, auth_headers, mock_llm, settings, monkeypatch):
    monkeypatch.setattr(settings, "CHAT_MAX_TOOL_ROUNDS", 2)
    loop_call = ChatTurn(text=None, function_calls=[FunctionCall(name="get_recent_scans", args={})])
    mock_llm.queue("chat_turn", loop_call)
    mock_llm.queue("chat_turn", loop_call)
    mock_llm.queue("chat_turn", ChatTurn(text="Final answer."))
    session = await _session(client, auth_headers)
    assert (await _send(client, auth_headers, session["id"], "hmm")).status_code == 201
    assistant = (await client.get(f"/api/v1/chat/sessions/{session['id']}", headers=auth_headers)).json()["data"][
        "messages"
    ][-1]
    assert assistant["content"] == "Final answer."
    assert [t["name"] for t in assistant["tool_calls"]] == ["get_recent_scans", "get_recent_scans"]
    assert mock_llm.calls["chat_turn"] == 3
    assert mock_llm.last_kwargs["chat_turn"]["tools"] == []


async def test_tool_errors_returned_to_model(client, auth_headers, mock_llm):
    mock_llm.queue(
        "chat_turn", ChatTurn(text=None, function_calls=[FunctionCall(name="get_scan_details", args={"scan_id": "x"})])
    )
    mock_llm.queue("chat_turn", ChatTurn(text="I couldn't find that scan."))
    session = await _session(client, auth_headers)
    r = await _send(client, auth_headers, session["id"], "show my scan")
    assert r.status_code == 201
    history = mock_llm.last_kwargs["chat_turn"]["history"]
    assert history[-1].role == "tool"
    assert history[-1].function_results[0].response == {"error": "scan not found"}


async def test_all_tools_execute(client, auth_headers, sample_jpeg, mock_llm):
    scan = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]
    calls = [
        FunctionCall(name="get_user_profile", args={}),
        FunctionCall(name="get_intake_summary", args={"days": 3.0}),
        FunctionCall(name="get_recent_scans", args={"limit": 2}),
        FunctionCall(name="get_scan_details", args={"scan_id": scan["id"]}),
        FunctionCall(name="estimate_meal", args={"description": "idli and sambar"}),
        FunctionCall(name="log_meal", args={"description": "banana", "meal_type": "brunch"}),
        FunctionCall(name="unknown_tool", args={}),
    ]
    mock_llm.queue("chat_turn", ChatTurn(text="Let me look.", function_calls=calls))
    mock_llm.queue("chat_turn", ChatTurn(text="All done."))
    session = await _session(client, auth_headers)
    assistant = (await _send(client, auth_headers, session["id"], "tell me everything")).json()["data"][
        "assistant_message"
    ]
    assert assistant["content"] == "Let me look.\n\nAll done."
    results = {r.name: r.response for r in mock_llm.last_kwargs["chat_turn"]["history"][-1].function_results}
    assert results["get_user_profile"]["result"]["targets"]["calories"] == 2000
    assert len(results["get_intake_summary"]["result"]["days"]) == 3
    assert results["get_recent_scans"]["result"]["scans"][0]["id"] == scan["id"]
    assert results["get_scan_details"]["result"]["meal_name"] == "Rajma Chawal Plate"
    assert results["estimate_meal"]["result"]["totals"]["calories"] > 0
    assert "error" in results["log_meal"]  # invalid meal_type
    assert "error" in results["unknown_tool"]


async def test_ai_unavailable_returns_503(client, auth_headers, mock_llm):
    mock_llm.queue("chat_turn", AppError("AI_UNAVAILABLE", "down", 503))
    session = await _session(client, auth_headers)
    r = await _send(client, auth_headers, session["id"], "hi")
    assert r.status_code == 503 and r.json()["code"] == "AI_UNAVAILABLE"


async def test_empty_and_too_long_message(client, auth_headers):
    session = await _session(client, auth_headers)
    r = await _send(client, auth_headers, session["id"], "   ")
    assert r.status_code == 400 and r.json()["code"] == "EMPTY_MESSAGE"
    r = await _send(client, auth_headers, session["id"])
    assert r.status_code == 400 and r.json()["code"] == "EMPTY_MESSAGE"
    r = await _send(client, auth_headers, session["id"], "x" * 2001)
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    r = await client.post(
        f"/api/v1/chat/sessions/{session['id']}/messages",
        headers=auth_headers,
        files={"image": ("x.jpg", b"not an image", "image/jpeg")},
    )
    assert r.status_code == 400 and r.json()["code"] == "INVALID_IMAGE"


async def test_other_users_sessions_404(client, auth_headers, second_user_headers):
    session = await _session(client, auth_headers)
    sid = session["id"]
    assert (await client.get(f"/api/v1/chat/sessions/{sid}", headers=second_user_headers)).status_code == 404
    assert (await _send(client, second_user_headers, sid, "hi")).status_code == 404
    r = await client.patch(f"/api/v1/chat/sessions/{sid}", headers=second_user_headers, json={"title": "x"})
    assert r.status_code == 404
    assert (await client.delete(f"/api/v1/chat/sessions/{sid}", headers=second_user_headers)).status_code == 404
    listing = (await client.get("/api/v1/chat/sessions", headers=second_user_headers)).json()["data"]
    assert listing["total"] == 0


async def test_rename_delete_and_suggestions(client, auth_headers, sample_jpeg):
    session = await _session(client, auth_headers)
    r = await client.patch(f"/api/v1/chat/sessions/{session['id']}", headers=auth_headers, json={"title": "Protein"})
    assert r.status_code == 200 and r.json()["data"]["title"] == "Protein"
    await _send(client, auth_headers, session["id"], "hello there")
    detail = (await client.get(f"/api/v1/chat/sessions/{session['id']}", headers=auth_headers)).json()["data"]
    assert detail["session"]["title"] == "Protein"  # explicit title is not overwritten
    r = await client.delete(f"/api/v1/chat/sessions/{session['id']}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["code"] == "DELETED"
    assert (await client.get(f"/api/v1/chat/sessions/{session['id']}", headers=auth_headers)).status_code == 404

    plain = (await client.get("/api/v1/chat/suggestions", headers=auth_headers)).json()["data"]["suggestions"]
    assert len(plain) == 4 and "How did I do today?" in plain
    scan = (await create_scan(client, auth_headers, sample_jpeg)).json()["data"]
    with_scan = (await client.get(f"/api/v1/chat/suggestions?scan_id={scan['id']}", headers=auth_headers)).json()
    assert "How can I make this meal healthier?" in with_scan["data"]["suggestions"]
    assert (await client.get("/api/v1/chat/suggestions?scan_id=nope", headers=auth_headers)).status_code == 404
