import io

from openpyxl import Workbook

RUNNER = {"Authorization": "Bearer runner-test-token"}
GOOD = '''import pytest
from bms import BMS

@pytest.mark.parametrize("t, expected", [(59.9, True), (60.0, False), (60.1, False)])
def test_sw001(t, expected):
    assert BMS().charging_allowed(t) is expected
'''
SHA_A = "a" * 40
SHA_B = "b" * 40


def xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["Requirement_ID", "Subsystem", "Description", "Priority", "Status"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def setup_project(c, u, auto=True):
    p = c.post("/api/projects", headers=u["eng"], json={"name": "Mini BMS"}).json()
    r = c.put(f"/api/projects/{p['id']}/git", headers=u["rev"], json={
        "repo_url": "git@github.com:acme/mini-bms.git", "branch": "main", "auto_validation": auto})
    assert r.status_code == 200, r.text
    return p["id"]


def import_sw001(c, u, pid):
    data = xlsx([["SW-001", "Thermal", "Overtemp protection", "High", "Approved"]])
    r = c.post(f"/api/projects/{pid}/requirements/import", headers=u["eng"],
               files={"file": ("srs.xlsx", data, "application/octet-stream")})
    assert r.status_code == 200, r.text
    return r.json()


def approved_tc(c, u, pid):
    req = c.get(f"/api/projects/{pid}/requirements", headers=u["eng"]).json()[0]
    tc = c.post(f"/api/projects/{pid}/testcases", headers=u["eng"],
                json={"tc_id": "TC-001", "requirement_id": req["id"], "title": "Overtemp"}).json()
    s = c.post(f"/api/testcases/{tc['id']}/scripts", headers=u["eng"], json={"source": GOOD}).json()
    r = c.post(f"/api/scripts/{s['id']}/review", headers=u["rev"], json={"decision": "approve"})
    assert r.status_code == 200, r.text
    return tc, s


def test_health_and_auth(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/projects").status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401


def test_roles(client, users):
    assert client.get("/api/users", headers=users["eng"]).status_code == 403
    pid = client.post("/api/projects", headers=users["eng"], json={"name": "P"}).json()["id"]
    # engineers may not configure CI
    r = client.put(f"/api/projects/{pid}/git", headers=users["eng"], json={"repo_url": "https://github.com/a/b"})
    assert r.status_code == 403


def test_repo_url_validation(client, users):
    pid = client.post("/api/projects", headers=users["eng"], json={"name": "P"}).json()["id"]
    for bad in ("file:///etc", "/home/x/repo", "https://github.com/a/b;rm -rf", "ext::sh -c x"):
        r = client.put(f"/api/projects/{pid}/git", headers=users["rev"], json={"repo_url": bad})
        assert r.status_code == 422, bad


def test_excel_import_revisions_and_no_delete(client, users):
    pid = setup_project(client, users)
    res = import_sw001(client, users, pid)
    assert res["created"] == ["SW-001"]
    approved_tc(client, users, pid)
    # re-import: changed description -> new revision; SW-001 not deleted when absent
    data = xlsx([["SW-001", "Thermal", "Overtemp protection v2", "High", "Approved"],
                 ["SW-002", "Voltage", "Undervoltage", "Medium", "Draft"]])
    r = client.post(f"/api/projects/{pid}/requirements/import", headers=users["eng"],
                    files={"file": ("srs.xlsx", data, "application/octet-stream")}).json()
    assert r["revised"] == ["SW-001"] and r["created"] == ["SW-002"]
    data = xlsx([["SW-002", "Voltage", "Undervoltage", "Medium", "Draft"]])
    r = client.post(f"/api/projects/{pid}/requirements/import", headers=users["eng"],
                    files={"file": ("srs.xlsx", data, "application/octet-stream")}).json()
    assert r["unchanged"] == ["SW-002"] and r["not_in_file_kept"] == ["SW-001"]
    reqs = client.get(f"/api/projects/{pid}/requirements", headers=users["eng"]).json()
    sw1 = [x for x in reqs if x["req_id"] == "SW-001"][0]
    detail = client.get(f"/api/requirements/{sw1['id']}", headers=users["eng"]).json()
    assert detail["revision"] == 2 and len(detail["revisions"]) == 2 and len(detail["test_cases"]) == 1


def test_excel_bad_files(client, users):
    pid = setup_project(client, users)
    bad = Workbook()
    bad.active.append(["Requirement_ID", "Description"])
    buf = io.BytesIO()
    bad.save(buf)
    r = client.post(f"/api/projects/{pid}/requirements/import", headers=users["eng"],
                    files={"file": ("srs.xlsx", buf.getvalue(), "application/octet-stream")})
    assert r.status_code == 400 and "Missing required columns" in r.json()["detail"]
    r = client.post(f"/api/projects/{pid}/requirements/import", headers=users["eng"],
                    files={"file": ("srs.xlsx", b"not excel", "application/octet-stream")})
    assert r.status_code == 400
    t = client.get("/api/requirements/template.xlsx", headers=users["eng"])
    assert t.status_code == 200 and t.content[:2] == b"PK"


def test_manual_requirement_edit_keeps_history(client, users):
    pid = setup_project(client, users)
    r = client.post(f"/api/projects/{pid}/requirements", headers=users["eng"],
                    json={"req_id": "SW-010", "description": "a"}).json()
    r2 = client.patch(f"/api/requirements/{r['id']}", headers=users["eng"],
                      json={"subsystem": "", "description": "b", "priority": "", "status": ""}).json()
    assert r2["revision"] == 2 and [x["description"] for x in r2["revisions"]] == ["b", "a"]


def test_script_validation_and_four_eyes(client, users):
    pid = setup_project(client, users)
    import_sw001(client, users, pid)
    req = client.get(f"/api/projects/{pid}/requirements", headers=users["eng"]).json()[0]
    tc = client.post(f"/api/projects/{pid}/testcases", headers=users["eng"],
                     json={"tc_id": "TC-001", "requirement_id": req["id"]}).json()
    v = client.post("/api/scripts/validate", headers=users["eng"], json={"source": "def x(:"}).json()
    assert not v["ok"] and "SyntaxError" in v["errors"][0]
    v = client.post("/api/scripts/validate", headers=users["eng"], json={"source": "import subprocess\ndef test_a(): pass"}).json()
    assert v["ok"] and v["warnings"]
    assert client.post(f"/api/testcases/{tc['id']}/scripts", headers=users["eng"],
                       json={"source": "x = 1"}).status_code == 422
    s = client.post(f"/api/testcases/{tc['id']}/scripts", headers=users["rev"], json={"source": GOOD}).json()
    assert s["revision"] == 1 and len(s["sha256"]) == 64 and s["approval_status"] == "draft"
    assert client.post(f"/api/testcases/{tc['id']}/scripts", headers=users["eng"],
                       json={"source": GOOD}).status_code == 409  # identical
    # engineer cannot approve; reviewer cannot approve own script
    assert client.post(f"/api/scripts/{s['id']}/review", headers=users["eng"], json={"decision": "approve"}).status_code == 403
    assert client.post(f"/api/scripts/{s['id']}/review", headers=users["rev"], json={"decision": "approve"}).status_code == 403
    assert client.get(f"/api/projects/{pid}/registry", headers=users["eng"]).json() == []
    assert client.post(f"/api/scripts/{s['id']}/review", headers=users["admin"], json={"decision": "approve"}).status_code == 200
    reg = client.get(f"/api/projects/{pid}/registry", headers=users["eng"]).json()
    assert [x["revision"] for x in reg] == [1]
    # new draft does not replace the approved revision in the registry
    client.post(f"/api/testcases/{tc['id']}/scripts", headers=users["eng"], json={"source": GOOD + "\n# v2\n"})
    reg = client.get(f"/api/projects/{pid}/registry", headers=users["eng"]).json()
    assert [x["revision"] for x in reg] == [1]


def test_manual_run_requires_approved_script(client, users):
    pid = setup_project(client, users)
    r = client.post(f"/api/projects/{pid}/runs", headers=users["eng"], json={})
    assert r.status_code == 409


def run_runner(c, verdict="PASS", commit=SHA_A):
    claim = c.post("/api/runner/claim", headers=RUNNER).json()
    run = claim["run"]
    if not run["commit_sha"]:
        assert c.post(f"/api/runner/runs/{run['id']}/commit", headers=RUNNER, json={"commit_sha": commit}).status_code == 200
    for e in claim["executions"]:
        c.post(f"/api/runner/executions/{e['execution_id']}", headers=RUNNER, json={"status": "RUNNING"})
        c.post(f"/api/runner/executions/{e['execution_id']}", headers=RUNNER,
               json={"status": verdict, "log": "3 passed", "duration_s": 1.2})
    return c.post(f"/api/runner/runs/{run['id']}/complete", headers=RUNNER, json={}).json()


def test_manual_run_and_runner_flow(client, users):
    pid = setup_project(client, users)
    import_sw001(client, users, pid)
    tc, s = approved_tc(client, users, pid)
    assert client.post("/api/runner/claim", headers={"Authorization": "Bearer nope"}).status_code == 401
    run = client.post(f"/api/projects/{pid}/runs", headers=users["eng"], json={"test_case_id": tc["id"]}).json()
    assert run["status"] == "QUEUED" and run["total"] == 1
    done = run_runner(client, "PASS")
    assert done["status"] == "PASS" and done["quality_gate"] == "PASSED" and done["commit_sha"] == SHA_A
    detail = client.get(f"/api/runs/{run['id']}", headers=users["eng"]).json()
    e = detail["executions"][0]
    assert e["requirement_code"] == "SW-001" and e["tc_id"] == "TC-001" and e["script_revision"] == 1
    assert e["log"] == "3 passed"
    rows = client.get(f"/api/projects/{pid}/executions?verdict=PASS&commit=aaaa", headers=users["eng"]).json()
    assert len(rows) == 1 and rows[0]["commit_sha"] == SHA_A


def ci_setup(c, u, auto=True):
    pid = setup_project(c, u, auto)
    import_sw001(c, u, pid)
    approved_tc(c, u, pid)
    tok = c.post(f"/api/projects/{pid}/git/ci-token", headers=u["rev"]).json()["token"]
    return pid, {"Authorization": f"Bearer {tok}"}


def test_ci_trigger_idempotency_and_gate(client, users):
    pid, ci = ci_setup(client, users)
    assert client.post("/api/ci/trigger", headers={"Authorization": "Bearer bad"},
                       json={"commit_sha": SHA_A, "branch": "main"}).status_code == 401
    r1 = client.post("/api/ci/trigger", headers=ci, json={"commit_sha": SHA_A, "branch": "refs/heads/main"}).json()
    r2 = client.post("/api/ci/trigger", headers=ci, json={"commit_sha": SHA_A, "branch": "main"}).json()
    assert r1["status"] == "CREATED" and r2["status"] == "DUPLICATE" and r1["run"]["id"] == r2["run"]["id"]
    run_runner(client, "PASS")
    r3 = client.post("/api/ci/trigger", headers=ci, json={"commit_sha": SHA_B, "branch": "main"}).json()
    assert r3["status"] == "CREATED"
    done = run_runner(client, "FAIL")
    assert done["status"] == "FAIL" and done["quality_gate"] == "FAILED"
    st = client.get(f"/api/ci/runs/{r3['run']['id']}", headers=ci).json()
    assert st["quality_gate"] == "FAILED" and st["commit_sha"] == SHA_B
    other = client.post("/api/ci/trigger", headers=ci, json={"commit_sha": SHA_A, "branch": "feature"}).json()
    assert other["status"] == "SKIPPED"
    ov = client.get(f"/api/projects/{pid}/overview", headers=users["eng"]).json()
    assert ov["mapping_coverage"] == 100.0 and ov["execution_coverage"] == 100.0
    assert ov["pass_rate"] == 0.0 and ov["latest_run"]["commit_sha"] == SHA_B
    assert ov["last_passing_run"]["commit_sha"] == SHA_A and len(ov["history"]) == 2


def test_ci_trigger_disabled(client, users):
    _, ci = ci_setup(client, users, auto=False)
    r = client.post("/api/ci/trigger", headers=ci, json={"commit_sha": SHA_A, "branch": "main"}).json()
    assert r["status"] == "SKIPPED"


def test_runner_recover(client, users):
    pid, ci = ci_setup(client, users)
    client.post("/api/ci/trigger", headers=ci, json={"commit_sha": SHA_A, "branch": "main"})
    client.post("/api/runner/claim", headers=RUNNER)
    rec = client.post("/api/runner/recover", headers=RUNNER).json()
    assert len(rec["recovered"]) == 1
    runs = client.get(f"/api/projects/{pid}/runs", headers=users["eng"]).json()
    assert runs[0]["status"] == "ERROR" and runs[0]["quality_gate"] == "FAILED"
