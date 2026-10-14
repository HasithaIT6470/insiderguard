import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import create_admin
from app.api import _login_failures
from app.database import Base, get_db
from app.main import app
from app.models import User
from app.security import hash_password, validate_password, verify_password

PASSWORD = "StrongPass1234"


@pytest.fixture
def account_env():
    _login_failures.clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add_all([User(username="rootadmin", role="admin", password_hash=hash_password(PASSWORD, "rootadmin")),
                    User(username="viewer", role="analyst", password_hash=hash_password(PASSWORD, "viewer"))])
        db.commit()
    def override_db():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        def login(username, password=PASSWORD):
            response = client.post("/api/auth/login", data={"username": username, "password": password})
            assert response.status_code == 200, response.text
            return {"Authorization": f"Bearer {response.json()['access_token']}"}
        yield client, login("rootadmin"), login("viewer"), login, sessions
    app.dependency_overrides.pop(get_db, None)
    _login_failures.clear()
    engine.dispose()


def accounts(client, headers):
    return client.get("/api/auth/accounts", headers=headers).json()


def test_create_roles_duplicates_and_private_account_list(account_env):
    client, admin, _, _, _ = account_env
    for role in ("admin", "analyst"):
        body = {"username": f"new_{role}", "password": PASSWORD, "role": role}
        assert client.post("/api/auth/accounts", json=body, headers=admin).status_code == 201
        assert client.post("/api/auth/accounts", json=body, headers=admin).status_code == 409
        body["username"] = body["username"].upper()
        assert client.post("/api/auth/accounts", json=body, headers=admin).status_code == 409
    rows = accounts(client, admin)
    assert len(rows) == 4
    assert all(set(row) == {"id", "username", "role", "created_at"} for row in rows)
    assert [row["created_at"] for row in rows] == sorted(row["created_at"] for row in rows)


@pytest.mark.parametrize("password", ["Ab123", "abcdefghijk", "12345678901", "\u00e9" * 36 + "A1"])
def test_password_validation_for_create_and_reset(account_env, password):
    client, admin, _, _, _ = account_env
    create = client.post("/api/auth/accounts", json={"username": "newuser", "password": password, "role": "analyst"}, headers=admin)
    target = next(row for row in accounts(client, admin) if row["username"] == "viewer")
    reset = client.post(f"/api/auth/accounts/{target['id']}/reset-password", json={"new_password": password}, headers=admin)
    assert reset.status_code == 422
    assert isinstance(reset.json()["detail"], str)
    assert create.status_code == 422


def test_password_byte_boundary_and_username_containment(account_env):
    validate_password("\u00e9" * 35 + "A1", "someone")
    with pytest.raises(HTTPException) as error:
        validate_password("prefixUSER12345", "user")
    assert error.value.status_code == 422
    client, admin, _, _, _ = account_env
    assert client.post("/api/auth/accounts", json={"username": "newuser", "password": "prefixNEWUSER12345", "role": "analyst"}, headers=admin).status_code == 422
    target = next(row for row in accounts(client, admin) if row["username"] == "viewer")
    assert client.post(f"/api/auth/accounts/{target['id']}/reset-password", json={"new_password": "prefixVIEWER12345"}, headers=admin).status_code == 422


def test_analyst_forbidden_on_all_account_operations(account_env):
    client, admin, analyst, _, _ = account_env
    target = accounts(client, admin)[0]["id"]
    assert client.get("/api/auth/accounts", headers=analyst).status_code == 403
    assert client.post("/api/auth/accounts", json={"username": "newuser", "password": PASSWORD, "role": "admin"}, headers=analyst).status_code == 403
    assert client.delete(f"/api/auth/accounts/{target}", headers=analyst).status_code == 403
    assert client.post(f"/api/auth/accounts/{target}/reset-password", json={"new_password": PASSWORD}, headers=analyst).status_code == 403


def test_delete_guards_deleted_token_and_audit(account_env):
    client, admin, analyst, _, _ = account_env
    rows = accounts(client, admin)
    caller = next(row for row in rows if row["username"] == "rootadmin")
    target = next(row for row in rows if row["username"] == "viewer")
    last = client.delete(f"/api/auth/accounts/{caller['id']}", headers=admin)
    assert last.status_code == 409 and "last remaining" in last.json()["detail"]
    assert client.post("/api/auth/accounts", json={"username": "secondadmin", "password": PASSWORD, "role": "admin"}, headers=admin).status_code == 201
    own = client.delete(f"/api/auth/accounts/{caller['id']}", headers=admin)
    assert own.status_code == 409 and "own account" in own.json()["detail"]
    assert client.delete("/api/auth/accounts/99999", headers=admin).status_code == 404
    assert client.delete(f"/api/auth/accounts/{target['id']}", headers=admin).json() == {"deleted": "viewer"}
    assert client.get("/api/auth/me", headers=analyst).status_code == 401
    audit = client.get("/api/audit", headers=admin).json()
    entry = next(row for row in audit if row["action"] == "delete_account")
    assert entry["target"] == "viewer" and entry["detail"] == {"role": "analyst"}
    assert any(row["action"] == "create_account" for row in audit)


def test_reset_invalidates_sessions_and_audits(account_env):
    client, admin, analyst, login, _ = account_env
    rows = accounts(client, admin)
    target = next(row for row in rows if row["username"] == "viewer")
    caller = next(row for row in rows if row["username"] == "rootadmin")
    assert client.post(f"/api/auth/accounts/{caller['id']}/reset-password", json={"new_password": PASSWORD}, headers=admin).status_code == 409
    assert client.post("/api/auth/accounts/99999/reset-password", json={"new_password": PASSWORD}, headers=admin).status_code == 404
    new_password = "Replacement5678"
    assert client.post(f"/api/auth/accounts/{target['id']}/reset-password", json={"new_password": new_password}, headers=admin).status_code == 200
    assert client.get("/api/auth/me", headers=analyst).status_code == 401
    assert client.post("/api/auth/login", data={"username": "viewer", "password": PASSWORD}).status_code == 401
    assert client.get("/api/auth/me", headers=login("viewer", new_password)).status_code == 200
    assert client.get("/api/auth/me", headers=admin).status_code == 200
    entry = next(row for row in client.get("/api/audit", headers=admin).json() if row["action"] == "reset_password")
    assert entry["target"] == "viewer"
    assert "password" not in str(entry["detail"])


def test_bootstrap_admin_with_hidden_prompts(account_env, monkeypatch, capsys):
    _, _, _, _, sessions = account_env
    monkeypatch.setattr(create_admin, "SessionLocal", sessions)
    monkeypatch.setattr(create_admin, "init_db", lambda: None)
    prompts = iter(["bootstrapadmin", PASSWORD, PASSWORD])
    monkeypatch.setattr(create_admin, "getpass", lambda prompt: next(prompts))
    assert create_admin.main() == 0
    with sessions() as db:
        row = db.query(User).filter_by(username="bootstrapadmin").one()
        assert row.role == "admin" and verify_password(PASSWORD, row.password_hash)
    assert PASSWORD not in capsys.readouterr().out
    prompts = iter(["BOOTSTRAPADMIN", PASSWORD, PASSWORD])
    monkeypatch.setattr(create_admin, "getpass", lambda prompt: next(prompts))
    assert create_admin.main() == 1
    prompts = iter(["otheruser", PASSWORD, "Mismatch1234"])
    monkeypatch.setattr(create_admin, "getpass", lambda prompt: next(prompts))
    assert create_admin.main() == 1


def test_production_can_bootstrap_without_seeded_accounts(account_env, monkeypatch):
    import app.main as application
    from app import config

    _, _, _, _, sessions = account_env
    with sessions() as db:
        db.query(User).delete()
        db.commit()
    monkeypatch.setattr(config, "ENV", "production")
    monkeypatch.setattr(application, "SessionLocal", sessions)
    monkeypatch.setattr(application, "init_db", lambda: None)
    application.startup()
    with sessions() as db:
        assert db.query(User).count() == 0
    monkeypatch.setattr(create_admin, "SessionLocal", sessions)
    monkeypatch.setattr(create_admin, "init_db", lambda: None)
    prompts = iter(["firstadmin", PASSWORD, PASSWORD])
    monkeypatch.setattr(create_admin, "getpass", lambda prompt: next(prompts))
    assert create_admin.main() == 0
    with sessions() as db:
        assert db.query(User).one().role == "admin"


def test_profile_requires_auth_and_returns_only_current_user(account_env):
    client, admin, analyst, _, _ = account_env
    assert client.get('/api/auth/me').status_code == 401
    assert client.post('/api/auth/change-password', json={'current_password': PASSWORD, 'new_password': 'Replacement5678'}).status_code == 401
    for headers, username in [(admin, 'rootadmin'), (analyst, 'viewer')]:
        response = client.get('/api/auth/me', headers=headers)
        assert response.status_code == 200
        assert set(response.json()) == {'username', 'role', 'created_at'}
        assert response.json()['username'] == username


def test_wrong_current_password_is_audited_without_invalidating_session(account_env):
    client, admin, analyst, _, _ = account_env
    response = client.post('/api/auth/change-password', headers=analyst, json={'current_password': 'wrong', 'new_password': 'Replacement5678'})
    assert response.status_code == 400
    assert response.json()['detail'] == 'Current password is incorrect'
    assert client.get('/api/auth/me', headers=analyst).status_code == 200
    entry = next(row for row in client.get('/api/audit', headers=admin).json() if row['action'] == 'change_password_failed')
    assert entry['actor'] == 'viewer' and entry['target'] == 'viewer'
    assert entry['detail'] == {}


def test_change_password_rate_limit_is_separate_and_expires(account_env, monkeypatch):
    from types import SimpleNamespace
    import app.api as endpoints

    client, _, analyst, login, _ = account_env
    clock = [10000]
    monkeypatch.setattr(endpoints, 'time', SimpleNamespace(time=lambda: clock[0]))
    wrong = {'current_password': 'wrong', 'new_password': 'Replacement5678'}
    for _ in range(5):
        assert client.post('/api/auth/change-password', headers=analyst, json=wrong).status_code == 400
    correct = {'current_password': PASSWORD, 'new_password': 'Replacement5678'}
    assert client.post('/api/auth/change-password', headers=analyst, json=correct).status_code == 429
    assert client.get('/api/auth/me', headers=login('viewer')).status_code == 200
    assert len(_login_failures['pw:viewer']) == 5
    clock[0] += endpoints.LOCK_WINDOW + 1
    assert client.post('/api/auth/change-password', headers=analyst, json=correct).status_code == 200
    assert 'pw:viewer' not in _login_failures


@pytest.mark.parametrize('new_password', [PASSWORD, 'short1', 'nodigitpassword', '12345678901', '\u00e9' * 36 + 'A1', 'prefixVIEWER12345'])
def test_change_password_rejects_same_and_weak_passwords(account_env, new_password):
    client, _, analyst, _, _ = account_env
    response = client.post('/api/auth/change-password', headers=analyst, json={'current_password': PASSWORD, 'new_password': new_password})
    assert response.status_code == 422
    assert client.get('/api/auth/me', headers=analyst).status_code == 200


@pytest.mark.parametrize('username', ['rootadmin', 'viewer'])
def test_change_password_returns_fresh_token_and_revokes_old_tokens(account_env, username):
    import hashlib
    from jose import jwt
    from app import config

    client, admin, analyst, login, sessions = account_env
    old = admin if username == 'rootadmin' else analyst
    second_session = login(username)
    response = client.post('/api/auth/change-password', headers=old, json={'current_password': PASSWORD, 'new_password': 'Replacement5678'})
    assert response.status_code == 200
    assert response.json()['token_type'] == 'bearer'
    fresh = {'Authorization': 'Bearer ' + response.json()['access_token']}
    assert client.get('/api/auth/me', headers=fresh).status_code == 200
    assert client.get('/api/auth/me', headers=old).status_code == 401
    assert client.get('/api/auth/me', headers=second_session).status_code == 401
    assert client.post('/api/auth/login', data={'username': username, 'password': PASSWORD}).status_code == 401
    assert client.get('/api/auth/me', headers=login(username, 'Replacement5678')).status_code == 200
    payload = jwt.decode(response.json()['access_token'], config.SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
    with sessions() as db:
        user = db.query(User).filter_by(username=username).one()
        assert payload['pwv'] == hashlib.sha256(user.password_hash.encode()).hexdigest()[:16]
    audit_headers = fresh if username == 'rootadmin' else admin
    entry = next(row for row in client.get('/api/audit', headers=audit_headers).json() if row['action'] == 'change_password')
    assert entry['actor'] == username and entry['detail'] == {}


def test_tokens_without_or_with_wrong_fingerprint_are_rejected(account_env):
    from datetime import datetime, timedelta, timezone
    from jose import jwt
    from app import config

    client, _, _, _, _ = account_env
    for claim in [{}, {'pwv': 'wrong'}, {'pwv': None}]:
        token = jwt.encode({'sub': 'viewer', 'exp': datetime.now(timezone.utc) + timedelta(minutes=5), **claim}, config.SECRET_KEY, algorithm=config.JWT_ALGORITHM)
        response = client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + token})
        assert response.status_code == 401
        assert response.json()['detail'] == 'Invalid or expired credentials'
