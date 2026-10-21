from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.routers.auth_db import get_current_user


def _build_app():
    app = FastAPI()

    @app.get("/secure")
    async def secure(current_user: dict = Depends(get_current_user)):
        return {"username": current_user["username"]}

    return app


def test_missing_authorization_header_returns_401():
    with TestClient(_build_app()) as client:
        resp = client.get("/secure")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "No authorization header"


def test_bearer_authorization_header_is_accepted():
    fake_user = SimpleNamespace(
        id="1",
        username="admin",
        email="admin@example.com",
        is_admin=True,
        is_active=True,
        preferences=None,
        phone=None,
        nickname=None,
        avatar=None,
    )
    token_data = SimpleNamespace(sub="admin")

    with (
        patch("app.routers.auth_db.AuthService.verify_token", return_value=token_data),
        patch(
            "app.routers.auth_db.user_service.get_user_by_username",
            new=AsyncMock(return_value=fake_user),
        ),
        TestClient(_build_app()) as client,
    ):
        resp = client.get("/secure", headers={"Authorization": "Bearer test-token"})

    assert resp.status_code == 200
    assert resp.json() == {"username": "admin"}
