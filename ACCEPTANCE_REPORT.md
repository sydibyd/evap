# EVAP Acceptance Report

- **Date:** 2026-11-25
- **Host:** Ubuntu 22.04.5, Docker 29.1.3, Compose 2.40.3
- **EVAP:** compose project `evap-v2` at http://127.0.0.1:8300
- **SUT:** private repository `sydibyd/mini-bms`
- **Overall result: PASS.** Every mandatory acceptance item below was executed on the real
  stack. Nothing in this report is inferred.

## 1. Primary criterion: PASS → FAIL → PASS through real Git pushes

`scripts/acceptance_push_demo.py` edits `bms/core.py`, commits and pushes to `main`, waits for
the GitHub Actions job (self-hosted runner), then reads EVAP's run for that exact SHA. Raw data
is in [`docs/acceptance_results.json`](docs/acceptance_results.json).

| Commit | Change | SHA | EVAP run | Verdict | Quality gate | Per-parameter result (59.9 / 60.0 / 60.1) | GitHub job | Result |
|---|---|---|---|---|---|---|---|---|
| A | `temperature < 60.0` | `8bc74981` | #2 (ci) | **PASS** | PASSED | PASS / PASS / PASS | [success](https://github.com/sydibyd/mini-bms/actions/runs/45658935917) | OK |
| B | `temperature <= 60.0` | `eb4f7d34` | #3 (ci) | **FAIL** | FAILED | PASS / **FAIL** / PASS | [failure](https://github.com/sydibyd/mini-bms/actions/runs/45659011034) | OK |
| C | `temperature < 60.0` | `95be5085` | #4 (ci) | **PASS** | PASSED | PASS / PASS / PASS | [success](https://github.com/sydibyd/mini-bms/actions/runs/45659086130) | OK |

All three commits triggered validation automatically, and every EVAP run is stored with its
full commit SHA, branch, repository, script revision (r1, SHA-256) and requirement revision.
Commit B fails exactly at the 60.0 °C boundary (`[60.0-False] FAILED`).

**Idempotency:** re-running the workflow of commit C (GitHub attempt 2) returned the existing
EVAP run #4 (`DUPLICATE`), with no second run created, and the job concluded `success`.

An earlier rehearsal of the same scenario during development (commits `2d8ce810` → `e050daa6` →
`cc71542e`) also gave success / failure / success on GitHub. Its EVAP database was reset before
the final run above.

## 2. Mandatory demonstration through the web interface

Run with `scripts/run_ui_demo.sh` (Playwright/Chromium clicking through the real UI; no direct
API calls), starting from an empty database. Screenshots: `docs/screenshots/`.

| # | Step | Actor | Result |
|---|---|---|---|
| 1 | Create the *Mini BMS* project | admin | OK |
| – | Create users `alice` (engineer) and `rob` (reviewer) | admin | OK |
| 2 | Connect `git@github.com:sydibyd/mini-bms.git`, branch `main`; generate CI token | admin | OK (`setup_01_cicd_configured.png`) |
| 3 | Import `examples/SRS_mini_bms.xlsx` → SW-001 created | alice | OK (`demo_01_requirements_imported.png`) |
| 4 | Create TC-001 from the SW-001 requirement view | alice | OK |
| 5 | Import/write the parameterized pytest script, Validate, Save r1 (draft) | alice | OK (`demo_02_script_saved_draft.png`) |
| 6 | Approve r1 (four-eyes: author ≠ reviewer) | rob | OK |
| 7 | Execute TC-001 manually → run #1 PASS, 3 passed, commit SHA shown | alice | OK (`demo_03_manual_run_pass.png`) |
| 8 | Enable automatic Git-triggered validation | rob | OK (`demo_04_auto_validation_enabled.png`) |
| – | Overview / Results / Requirements after the push scenario | alice | OK (`check_*.png`) |

Before step 8, a push to `main` reached EVAP through GitHub Actions and was correctly
**skipped** ("Automatic validation is disabled for this project"), and the job passed.

## 3. Automated tests

| Suite | Command | Result |
|---|---|---|
| Backend API (auth, RBAC, four-eyes, Excel import/revisions/no-delete, bad files, template, registry, manual runs, runner protocol, CI trigger, idempotency, branch/disabled skip, quality gate, overview metrics, crash recovery, repo URL validation) | `cd backend && .venv/bin/python -m pytest -q` | **12 passed** |
| Runner workspace (layout, uid, symlink/`..` stripping) | `pytest -q runner/tests` | **1 passed** |
| Sandbox isolation (live Docker): non-root, no network, no Docker socket, no secrets in env, no `/run/secrets` or host home, cannot write `/etc`, SUT present; timeout kills infinite loop (ERROR); 1 GiB allocation killed (ERROR); no sandbox containers left | `docker compose exec -T runner python sandbox_check.py` | **PASS (4/4 groups, 7 probes)** |
| Mini BMS developer unit tests | `pytest -q tests` (in mini-bms) | **4 passed** |
| Migrations | `alembic upgrade head` + `alembic check` on PostgreSQL 16 | **No drift** |

## 4. Definition of done

| Criterion | Status | Evidence |
|---|---|---|
| EVAP starts successfully | ✅ | `docker compose up -d --build`; all services healthy |
| Web interface functional | ✅ | UI demo §2 |
| Excel requirements import works | ✅ | UI step 3, API tests |
| Test cases created through the UI | ✅ | UI step 4 |
| Scripts defined and approved through the UI | ✅ | UI steps 5–6 |
| SIL tests execute successfully | ✅ | UI step 7, §1 |
| Git pushes trigger automatic validation | ✅ | §1 (8 pushes in total, all reached EVAP) |
| PASS → FAIL → PASS succeeds | ✅ | §1 |
| Results linked to exact Git commits | ✅ | §1 table; run detail shows full SHA |
| Data persists after restart | ✅ | `docker compose restart` and `down` + `up`: 4 runs, 3 users, approved script all present |
| Documentation complete | ✅ | README, ARCHITECTURE, USER_GUIDE, SECURITY, this report |
| Mandatory acceptance tests executed | ✅ | §1–§3 |

## 5. Not verified / limitations

- The UI was exercised by a scripted browser (Playwright/Chromium 1.49), not by a person; other
  browsers were not tested.
- The backend API tests run on SQLite. PostgreSQL behaviour was verified through the live
  end-to-end runs, not by the unit suite.
- Throughput with many tests or concurrent runners was not measured. One runner executes tests
  sequentially.
- The self-hosted runner was started with `./run.sh` (not installed as a service), so it does
  not survive a reboot.
- See [SECURITY.md](SECURITY.md) for the remaining security limitations.
