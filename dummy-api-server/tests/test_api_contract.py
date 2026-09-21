"""The contract the night-shift repair worker validates against.

This suite is the pass/fail signal for a repair attempt
(REPAIR_VALIDATION_COMMAND). Every seeded bug in mess-maker/bug_catalogue.py
has exactly one test here that fails while the bug is present and passes once
it is fixed.

It runs inside the API container, against the real Postgres and Redis the
compose stack provides:

    docker compose exec fastapi python -m pytest -q tests/test_api_contract.py
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def _make_user(client, first_name="Night"):
    """Create a user and return the created record (including its id).

    Deliberately does NOT use the list endpoint, so a pagination defect cannot
    cascade into unrelated tests.
    """
    payload = {
        "first_name": first_name,
        "last_name": "Shift",
        "email": f"{uuid.uuid4().hex[:12]}@example.com",
    }
    response = client.post("/users/create", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# --- baseline --------------------------------------------------------------

def test_health_check_is_up(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"message": "Server is up!"}


def test_create_user_returns_201(client):
    created = _make_user(client, "Ada")
    assert created["id"] > 0
    assert created["first_name"] == "Ada"


# --- B1: missing user must be 404, never 500 -------------------------------

def test_unknown_user_returns_404(client):
    response = client.get(f"/users/{uuid.uuid4().int % 9_000_000 + 1_000_000}")
    assert response.status_code == 404, (
        f"A user that does not exist must return 404, got {response.status_code}. "
        f"Body: {response.text[:400]}"
    )


# --- B2: pagination must honour limit and offset ---------------------------

def test_pagination_respects_limit_and_offset(client):
    for index in range(3):
        _make_user(client, f"Pager{index}")

    first_page = client.get("/users/", params={"limit": 2, "offset": 0})
    assert first_page.status_code == 200, first_page.text
    assert len(first_page.json()) == 2, (
        f"limit=2 must return exactly 2 users, got {len(first_page.json())}. "
        "limit and offset are probably swapped."
    )

    second_page = client.get("/users/", params={"limit": 2, "offset": 2})
    assert second_page.status_code == 200, second_page.text
    assert second_page.json() != first_page.json(), "offset=2 returned the first page again"


# --- B3: stats must survive a status with no entries -----------------------

def test_log_stats_handles_empty_status(client):
    response = client.get("/logs/stats", params={"status": "duplicate"})
    assert response.status_code == 200, (
        f"/logs/stats must not crash on a status with zero logs, got "
        f"{response.status_code}. Body: {response.text[:400]}"
    )
    body = response.json()
    assert "counts" in body and "open_share" in body


# --- B4: deleting a real user must succeed ---------------------------------

def test_delete_existing_user_succeeds(client):
    user = _make_user(client, "Doomed")

    response = client.delete(f"/users/{user['id']}")
    assert response.status_code == 200, (
        f"Deleting an existing user must return 200, got {response.status_code}. "
        f"Body: {response.text[:400]}"
    )
