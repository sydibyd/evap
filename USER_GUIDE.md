# EVAP User Guide

Roles: **engineer** writes requirements, test cases and scripts and runs tests. **Reviewer**
does the same, can also approve scripts and configure CI/CD. **Admin** can do everything and
manages users. Nobody can approve their own script (four-eyes rule).

## 1. First start

1. Sign in with the bootstrap admin from `.env`.
2. **CI/CD Integration → Users & roles**: create at least one engineer and one reviewer.

## 2. Create a project and connect the repository

1. **+ New project** (top bar) → name, e.g. `Mini BMS`.
2. **CI/CD Integration** (reviewer/admin):
   - Git repository URL: `git@github.com:<owner>/mini-bms.git` (private, via the deploy key) or
     `https://github.com/<owner>/<repo>.git` (public).
   - Branch (e.g. `main`), Python environment, test timeout, quality gate policy.
   - Leave *Automatic validation* **off** until a test is approved.
   - **Save Git integration**.

## 3. Import requirements (Excel SRS)

- **Requirements → Download Excel template** gives the expected format. Required columns:
  `Requirement_ID, Subsystem, Description, Priority, Status`.
- **Import Excel SRS** → pick the `.xlsx`. The result banner lists what was created, revised and
  left unchanged. Requirements that are missing from the file are **kept**: imports never delete
  requirements, test cases or results.
- Changing a requirement (import or **Edit**) creates a new revision. The full history is in the
  requirement detail. Use search and the status/priority filters to find requirements.
  `uncovered` marks requirements without test cases.

## 4. Design a test case and its script

1. Open a requirement → **+ Test case** (or **Test Design → + New test case**). Fill in
   preconditions, inputs, expected results, SIL environment → **Create test case**.
2. In **Test script**, write pytest code in the editor or click **Import .py**. The SUT
   repository root is on `sys.path`, so `from bms import BMS` works. Only the standard library and
   pytest are available, and there is no network.
3. **Validate** checks syntax and that at least one `test_*` function exists. It also flags
   sensitive imports for the reviewer.
4. **Save as new revision** stores revision *rN* as **draft**, with its SHA-256 and author.

Example (TC-001 / SW-001, `examples/test_tc001_sw001.py`):

```python
import pytest
from bms import BMS

@pytest.mark.parametrize("temperature, expected", [(59.9, True), (60.0, False), (60.1, False)])
def test_sw001_overtemperature_protection(temperature, expected):
    assert BMS().charging_allowed(temperature) is expected
```

## 5. Review and approval

A reviewer other than the author opens the test case, reads the revision and adds a comment →
**Approve rN** or **Reject**. Only approved revisions can execute. A new draft does not replace
the approved revision until it is approved itself.

## 6. Execute

- **Single test**: Test Design → **Execute approved rN**. It runs against the current head of
  the configured branch, and the run dialog shows the resolved commit SHA, verdict and pytest log.
- **Regression campaign**: Overview or Validation Results → **Run regression campaign** runs
  every approved test.

## 7. Automatic validation on every push (GitHub Actions)

1. **CI/CD Integration → Generate CI token**. Copy it (it is shown only once) and store it in the
   SUT repo: `gh secret set EVAP_CI_TOKEN -R <owner>/<repo>`.
2. Copy `ci/evap-validation.yml` to `.github/workflows/` and `ci/evap_ci.py` to
   `.github/evap/` in the SUT repo. Adjust the branch and the `github.repository` guard.
3. Register a self-hosted runner with label `evap-local` on the EVAP host, **for a private
   repository only** (Settings → Actions → Runners → New self-hosted runner, or
   `./config.sh --url https://github.com/<owner>/<repo> --token <token> --labels evap-local`),
   then start it with `./run.sh` (or `sudo ./svc.sh install && sudo ./svc.sh start` to keep it
   across reboots).
4. Back in EVAP, enable **Automatic validation** → Save.

From then on every push to the branch creates a CI run for that exact commit. The GitHub job
waits for the result and succeeds or fails with the quality gate. A re-run of the same workflow
(same commit, same approved test baseline) returns the existing result instead of a duplicate.

## 8. Results and traceability

**Validation Results** lists runs (ID, trigger, repo, branch, commit, scope, verdict, quality
gate) and test executions (requirement, test case, script revision, date, duration, verdict).
Filter by requirement, test case, commit SHA prefix and verdict. Click a run to see the
requirement revision, script SHA-256 and the full pytest log per test. Commit SHAs link to
GitHub. **Overview** refreshes every few seconds.
