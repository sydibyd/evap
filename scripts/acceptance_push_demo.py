#!/usr/bin/env python3
"""Acceptance test: PASS -> FAIL -> PASS through real Git pushes and GitHub Actions.

For each commit (A correct, B regression, C fix) this script:
  1. edits bms/core.py in the Mini BMS working copy, commits and pushes to main,
  2. waits for the GitHub Actions workflow run of that exact SHA (gh CLI),
  3. reads EVAP's validation run for that SHA through the EVAP REST API,
  4. asserts: EVAP verdict + quality gate + GitHub job conclusion match the expectation.
Finally it re-runs the last workflow to prove idempotency (same EVAP run, no duplicate).

Usage: python3 scripts/acceptance_push_demo.py ../mini-bms   (reads .env and secrets/demo_users.env)
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BMS = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "..", "mini-bms"))
GH_REPO = os.environ.get("GH_REPO", "sydibyd/mini-bms")


def envfile(path):
    out = {}
    for line in open(path):
        m = re.match(r"^([A-Z_]+)=([^#\s]*)", line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


ENV = {**envfile(os.path.join(ROOT, ".env")), **envfile(os.path.join(ROOT, "secrets", "demo_users.env"))}
URL = f"http://127.0.0.1:{ENV.get('EVAP_HTTP_PORT', '8300')}"


def sh(*cmd, cwd=BMS):
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def evap(path, body=None, token=None):
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def gh_run_for(sha, timeout=600):
    deadline = time.time() + timeout
    while time.time() < deadline:
        runs = json.loads(sh("gh", "run", "list", "-R", GH_REPO, "-L", "20", "--json",
                             "databaseId,headSha,status,conclusion,url"))
        mine = [r for r in runs if r["headSha"] == sha]
        if mine and mine[0]["status"] == "completed":
            return mine[0]
        time.sleep(5)
    raise TimeoutError(f"GitHub workflow for {sha} did not complete")


def set_impl(op, label):
    path = os.path.join(BMS, "bms", "core.py")
    src = open(path).read()
    src = re.sub(r"return temperature <=? 60\.0", f"return temperature {op} 60.0", src)
    src = re.sub(r'"""SW-001: charging is disabled when temperature >= 60 degC\.(.*?)"""',
                 f'"""SW-001: charging is disabled when temperature >= 60 degC. ({label})"""', src, flags=re.S)
    open(path, "w").write(src)
    sh("git", "add", "bms/core.py")
    sh("git", "commit", "-q", "-m", label)
    sh("git", "push", "-q", "origin", "main")
    return sh("git", "rev-parse", "HEAD")


def main():
    tok = evap("/api/auth/login", {"username": "alice", "password": ENV["ENG_PASSWORD"]})["token"]
    pid = evap("/api/projects", token=tok)[0]["id"]
    steps = [("<", "Commit A: correct overtemperature implementation (temperature < 60.0)", "PASS", "success"),
             ("<=", "Commit B: introduce regression (temperature <= 60.0)", "FAIL", "failure"),
             ("<", "Commit C: fix regression (temperature < 60.0)", "PASS", "success")]
    results, ok = [], True
    for op, label, exp_verdict, exp_ci in steps:
        sha = set_impl(op, label)
        print(f"pushed {sha[:8]}  {label}")
        gh = gh_run_for(sha)
        runs = [r for r in evap(f"/api/projects/{pid}/runs?commit={sha}", token=tok) if r["trigger"] == "ci"]
        run = evap(f"/api/runs/{runs[0]['id']}", token=tok) if runs else None
        verdicts = [e["status"] for e in run["executions"]] if run else []
        passed = (run is not None and run["status"] == exp_verdict and run["commit_sha"] == sha
                  and run["quality_gate"] == ("PASSED" if exp_verdict == "PASS" else "FAILED")
                  and gh["conclusion"] == exp_ci and len(runs) == 1)
        ok &= passed
        results.append({"commit": label.split(":")[0], "sha": sha, "expected": exp_verdict,
                        "evap_run": run and run["id"], "evap_verdict": run and run["status"],
                        "quality_gate": run and run["quality_gate"], "executions": verdicts,
                        "github_conclusion": gh["conclusion"], "github_run": gh["url"],
                        "result": "OK" if passed else "MISMATCH"})
        print(f"  EVAP run #{run and run['id']}: {run and run['status']} / gate {run and run['quality_gate']}"
              f" | GitHub job: {gh['conclusion']} -> {'OK' if passed else 'MISMATCH'}")
        if run:
            log = run["executions"][0]["log"]
            print("  " + "\n  ".join(line for line in log.splitlines() if "::test_" in line and "%]" in line))

    # Idempotency: re-run the last GitHub workflow -> EVAP must return the same run (no duplicate)
    last = results[-1]
    gh_id = last["github_run"].rstrip("/").split("/")[-1]
    sh("gh", "run", "rerun", gh_id, "-R", GH_REPO)
    time.sleep(10)
    deadline = time.time() + 300
    while time.time() < deadline:
        st = json.loads(sh("gh", "api", f"repos/{GH_REPO}/actions/runs/{gh_id}",
                           "--jq", "{status,conclusion,attempt:.run_attempt}"))
        if st["status"] == "completed" and st["attempt"] >= 2:
            break
        time.sleep(5)
    dup_runs = [r for r in evap(f"/api/projects/{pid}/runs?commit={last['sha']}", token=tok) if r["trigger"] == "ci"]
    idem = len(dup_runs) == 1 and dup_runs[0]["id"] == last["evap_run"] and st["conclusion"] == "success"
    ok &= idem
    print(f"idempotency: workflow re-run attempt {st.get('attempt')} -> EVAP CI runs for {last['sha'][:8]}: "
          f"{[r['id'] for r in dup_runs]} -> {'OK' if idem else 'MISMATCH'}")
    out = {"scenario": results, "idempotency": {"rerun_github_run": gh_id, "evap_runs_for_sha": [r["id"] for r in dup_runs],
                                               "result": "OK" if idem else "MISMATCH"},
           "overall": "PASS" if ok else "FAIL", "executed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with open(os.path.join(ROOT, "docs", "acceptance_results.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("OVERALL:", out["overall"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
