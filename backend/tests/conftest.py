import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("EVAP_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("EVAP_JWT_SECRET", "test-secret-test-secret-test-secret-123")
os.environ.setdefault("EVAP_RUNNER_TOKEN", "runner-test-token")
os.environ.setdefault("EVAP_BOOTSTRAP_ADMIN_USER", "admin")
os.environ.setdefault("EVAP_BOOTSTRAP_ADMIN_PASSWORD", "admin-password-123")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, get_engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


def login(c, user, pw):
    r = c.post("/api/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture()
def users(client):
    adm = login(client, "admin", "admin-password-123")
    for name, role in (("alice", "engineer"), ("rob", "reviewer")):
        r = client.post("/api/users", headers=adm, json={"username": name, "password": f"{name}-password-1", "role": role})
        assert r.status_code == 201, r.text
    return {"admin": adm, "eng": login(client, "alice", "alice-password-1"),
            "rev": login(client, "rob", "rob-password-1")}
