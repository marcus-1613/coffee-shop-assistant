"""Integration tests for registration, login, and protected identity."""
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_register_login_and_read_current_user():
    username = f"user_{uuid4().hex[:10]}"
    password = "strong-password-123"

    registered = client.post(
        "/auth/register",
        json={"username": username, "password": password},
    )
    assert registered.status_code == 201
    assert registered.json()["username"] == username

    logged_in = client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )
    assert logged_in.status_code == 200
    token = logged_in.json()["access_token"]

    me = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    assert me.json()["username"] == username


def test_register_rejects_short_password():
    response = client.post(
        "/auth/register",
        json={"username": "valid-user", "password": "short"},
    )
    assert response.status_code == 422
