import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="ig_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["INSIDERGUARD_SECRET_KEY"] = "test-secret-key-not-for-production-use-0123456789"
os.environ["INSIDERGUARD_ADMIN_PASSWORD"] = "Guard#Test12345"
os.environ["INSIDERGUARD_ANALYST_PASSWORD"] = "Review#Test12345"
os.environ.pop("AI_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def _login(client, user, pw):
    r = client.post("/api/auth/login", data={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin(client):
    return _login(client, "admin", "Guard#Test12345")


@pytest.fixture(scope="session")
def analyst(client):
    return _login(client, "analyst", "Review#Test12345")
