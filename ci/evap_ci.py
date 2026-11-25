#!/usr/bin/env python3
"""EVAP CI client (Python stdlib only).

Triggers an EVAP validation of the pushed commit, waits for the result and exits with the
quality gate: 0 = PASSED (or validation skipped by EVAP policy), 1 = FAILED, 2 = error/timeout.

Environment: EVAP_URL, EVAP_CI_TOKEN (secret) and the standard GITHUB_* variables.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = os.environ.get("EVAP_URL", "http://127.0.0.1:8300").rstrip("/")
TOKEN = os.environ.get("EVAP_CI_TOKEN", "")
WAIT_S = int(os.environ.get("EVAP_WAIT_SECONDS", "900"))
FINAL = {"PASS", "FAIL", "ERROR"}


def call(method, path, body=None):
    req = urllib.request.Request(URL + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main() -> int:
    if not TOKEN:
        print("::error::EVAP_CI_TOKEN is not set")
        return 2
    gh = os.environ
    server, repo, run_id = gh.get("GITHUB_SERVER_URL", ""), gh.get("GITHUB_REPOSITORY", ""), gh.get("GITHUB_RUN_ID", "")
    body = {"commit_sha": gh["GITHUB_SHA"], "branch": gh.get("GITHUB_REF_NAME") or gh.get("GITHUB_REF", ""),
            "repository": repo, "event_id": f"{run_id}-{gh.get('GITHUB_RUN_ATTEMPT', '1')}",
            "run_url": f"{server}/{repo}/actions/runs/{run_id}" if run_id else ""}
    try:
        res = call("POST", "/api/ci/trigger", body)
    except urllib.error.HTTPError as e:
        print(f"::error::EVAP trigger failed: HTTP {e.code} {e.read().decode()[:500]}")
        return 2
    except (urllib.error.URLError, OSError) as e:
        print(f"::error::EVAP not reachable at {URL}: {e}")
        return 2
    if res["status"] == "SKIPPED":
        print(f"EVAP validation skipped: {res['reason']}")
        return 0
    run = res["run"]
    print(f"EVAP run #{run['id']} ({res['status']}) for commit {body['commit_sha']}")
    deadline = time.time() + WAIT_S
    while run["status"] not in FINAL:
        if time.time() > deadline:
            print(f"::error::Timed out after {WAIT_S}s waiting for EVAP run #{run['id']}")
            return 2
        time.sleep(3)
        try:
            run = call("GET", f"/api/ci/runs/{run['id']}")
        except (urllib.error.URLError, OSError) as e:
            print(f"warning: polling failed ({e}); retrying")
    for e in run.get("executions", []):
        print(f"  {e['requirement_code']:<10} {e['tc_id']:<10} r{e['script_revision']:<3} {e['status']}")
    print(f"Verdict: {run['status']}  passed {run['passed']}/{run['total']}  "
          f"quality gate: {run['quality_gate']} ({run['gate_policy']})")
    if run.get("message"):
        print(f"Message: {run['message']}")
    if run["quality_gate"] != "PASSED":
        print(f"::error::EVAP quality gate FAILED for {body['commit_sha'][:8]} (run #{run['id']})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
