"""The web API, through the real server: sign-in, request checks, and keeping users' data apart."""

import http.client

import limits

NEW_BENEFIT = {"benefit_name": "Movie voucher", "provider": "Golden Village", "type": "voucher",
               "category": "entertainment", "value": "S$13", "expiry_date": "2027-03-31", "code": "GV1234"}


# --- Request checks --------------------------------------------------------------------

def test_signed_out_requests_are_refused(client):
    assert client.get("/api/benefits")[0] == 401
    assert client.post("/api/benefits", NEW_BENEFIT)[0] == 401
    status, data = client.get("/api/session")
    assert status == 200 and data["user"] is None


def test_posts_must_be_json(client):
    client.sign_up("alex@example.com")
    status, _ = client.request("POST", "/api/benefits", None, headers={"Content-Type": "text/plain"})
    assert status == 415


def test_posts_from_other_sites_are_blocked(client):
    client.sign_up("alex@example.com")
    status, _ = client.post("/api/benefits", NEW_BENEFIT, headers={"Origin": "https://evil.example"})
    assert status == 403


def test_security_headers(client):
    conn = http.client.HTTPConnection("127.0.0.1", client.port)
    conn.request("GET", "/api/session")
    headers = conn.getresponse().headers
    conn.close()
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"


# --- Sign-up, sign-in, sign-out ------------------------------------------------------------

def test_sign_up_sign_out_sign_in(client, sent_emails):
    user = client.sign_up("alex@example.com")
    assert client.get("/api/session")[1]["user"]["id"] == user["id"]
    assert client.post("/api/auth/logout")[0] == 200
    assert client.get("/api/benefits")[0] == 401
    status, data = client.post("/api/auth/login", {"email": "alex@example.com", "password": "correct horse battery"})
    assert status == 200 and data["user"]["id"] == user["id"]
    assert client.get("/api/benefits")[0] == 200


def test_wrong_password_is_rejected(client):
    client.sign_up("alex@example.com")
    client.post("/api/auth/logout")
    status, _ = client.post("/api/auth/login", {"email": "alex@example.com", "password": "not my password"})
    assert status == 400
    assert client.get("/api/benefits")[0] == 401


# --- Benefits ----------------------------------------------------------------------------------

def test_add_edit_remove_restore(client):
    client.sign_up("alex@example.com")
    status, created = client.post("/api/benefits", NEW_BENEFIT)
    assert status == 200 and created["code"] == "GV1234"
    bid = created["id"]

    status, edited = client.post(f"/api/benefits/{bid}/update", {**NEW_BENEFIT, "value": "S$15"})
    assert status == 200 and edited["value"] == "S$15"

    assert client.post(f"/api/benefits/{bid}/dismiss")[0] == 200
    assert bid not in [b["id"] for b in client.get("/api/benefits")[1]]
    assert [b["id"] for b in client.get("/api/benefits/removed")[1]] == [bid]

    status, restored = client.post(f"/api/benefits/{bid}/restore")
    assert status == 200 and restored["value"] == "S$15"
    assert bid in [b["id"] for b in client.get("/api/benefits")[1]]


def test_bad_benefit_input_is_rejected(client):
    client.sign_up("alex@example.com")
    for bad in ({**NEW_BENEFIT, "benefit_name": ""}, {**NEW_BENEFIT, "type": "spaceship"},
                {**NEW_BENEFIT, "expiry_date": "next week"}):
        assert client.post("/api/benefits", bad)[0] == 400


def test_users_cannot_see_or_change_each_others_benefits(client, other_client):
    client.sign_up("alex@example.com")
    other_client.sign_up("sam@example.com")
    bid = client.post("/api/benefits", NEW_BENEFIT)[1]["id"]

    assert other_client.get("/api/benefits")[1] == []
    assert other_client.post(f"/api/benefits/{bid}/update", NEW_BENEFIT)[0] == 404
    assert other_client.post(f"/api/benefits/{bid}/quick", {"used": True})[0] == 404
    assert other_client.post(f"/api/benefits/{bid}/dismiss")[0] == 404

    client.post(f"/api/benefits/{bid}/dismiss")
    assert other_client.get("/api/benefits/removed")[1] == []
    assert other_client.post(f"/api/benefits/{bid}/restore")[0] == 404
    # Untouched for its owner.
    assert client.post(f"/api/benefits/{bid}/restore")[1]["benefit_name"] == "Movie voucher"


# --- Cards and the daily scan ----------------------------------------------------------------------

def test_cards_endpoint(client):
    client.sign_up("alex@example.com")
    status, data = client.get("/api/cards")
    assert status == 200 and data["cards"] == []
    assert any(c["key"] == "uob_one" for c in data["catalog"]["cards"])
    status, card = client.post("/api/cards", {"card_key": "citi_premiermiles", "anniversary_month": None})
    assert status == 200
    names = [b["benefit_name"] for b in client.get("/api/benefits")[1]]
    assert names == ["Airport lounge visits"]


def test_daily_scan_switch(client):
    client.sign_up("alex@example.com")
    assert client.get("/api/session")[1]["auto_scan"]["enabled"] is False
    assert client.post("/api/auto-scan", {"enabled": "yes"})[0] == 400
    status, data = client.post("/api/auto-scan", {"enabled": True})
    assert status == 200 and data["enabled"] is True
    assert data["running"] is False  # nothing connected, so nothing to scan


def test_retry_given_up_emails(client):
    import db
    import scan_jobs
    user = client.sign_up("alex@example.com")
    with db.connect() as conn:
        conn.execute("INSERT INTO processed_emails (user_id, message_id, done, failures) VALUES (?, 'a', 0, ?)",
                     (user["id"], scan_jobs.MAX_TRIES))
    assert client.get("/api/scan-failures") == (200, {"count": 1})
    assert client.post("/api/scan-failures/retry") == (200, {"count": 1})
    assert client.get("/api/scan-failures") == (200, {"count": 0})


def test_session_says_when_reminders_are_failing(client):
    import db
    user = client.sign_up("alex@example.com")
    assert client.get("/api/session")[1]["reminders_failing_since"] is None
    with db.connect() as conn:
        conn.execute("INSERT INTO reminder_settings (user_id, enabled, days_before, failing_since) "
                     "VALUES (?, 1, 7, '2026-10-01T00:00:00+00:00')", (user["id"],))
    assert client.get("/api/session")[1]["reminders_failing_since"] == "2026-10-01T00:00:00+00:00"


# --- Limits on AI requests ---------------------------------------------------------------------------

def test_hourly_ai_limit():
    for _ in range(limits.LIMITS["ask"]):
        assert limits.take("u1", "ask") is None
    assert limits.take("u1", "ask") >= 1  # minutes to wait
    assert limits.take("u2", "ask") is None  # per user
