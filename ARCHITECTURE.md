# EVAP Architecture

## 1. Components

```mermaid
flowchart LR
  subgraph GH[GitHub]
    SUT[(mini-bms<br/>private repo)]
    GHA[GitHub Actions<br/>workflow on push]
  end
  subgraph HOST[EVAP host · Ubuntu 22.04]
    SHR[Self-hosted runner<br/>label evap-local<br/>outbound only]
    subgraph C[docker compose project evap-v2]
      FE[frontend<br/>nginx + React<br/>127.0.0.1:8300]
      BE[backend<br/>FastAPI]
      DB[(PostgreSQL)]
      RN[runner<br/>SIL orchestrator]
    end
    SB[[sandbox container<br/>per test execution<br/>no network · non-root]]
  end
  User((Validation engineer)) -->|browser| FE
  FE -->|/api| BE
  BE --- DB
  SUT -->|push event| GHA -->|job| SHR
  SHR -->|POST /api/ci/trigger<br/>CI token| FE
  RN -->|claim / report<br/>runner token| BE
  RN -->|git fetch, read-only deploy key| SUT
  RN -->|create · copy workspace · start · wait · logs · remove| SB
```

| Component | Responsibility |
|---|---|
| **frontend** | React SPA (Overview, Requirements, Test Design, CI/CD Integration, Validation Results). nginx serves it and reverse-proxies `/api` to the backend. It is the only published port (`127.0.0.1` only). |
| **backend** | REST API, auth/RBAC, requirement revisions, Excel import, script registry (revisions, SHA-256, approval), run queue with idempotency, quality gate, metrics. Never executes test code. Runs read-only, non-root, on an `internal` network with no Internet access. |
| **db** | PostgreSQL 16; schema managed by Alembic (`backend/alembic/versions`), applied on backend start. |
| **runner** | Polls the queue (`FOR UPDATE SKIP LOCKED`), fetches the SUT repo mirror, resolves and archives the exact commit, launches one sandbox per approved script revision, reports verdicts and logs. |
| **sandbox** | Disposable `python:3.11-slim` + pytest image. Each test gets a fresh container: `network=none`, uid 10001, `cap_drop=ALL`, `no-new-privileges`, memory/CPU/PID limits, hard timeout, no mounts, no Docker socket, no credentials. |
| **self-hosted runner** | Official `actions/runner` registered **only** to the private SUT repo. It connects outbound to GitHub, so EVAP is never exposed publicly. |

## 2. Data model and traceability

```mermaid
erDiagram
  PROJECTS ||--o| GIT_INTEGRATIONS : "repo, branch, auto, env, timeout, gate, CI token hash"
  PROJECTS ||--o{ REQUIREMENTS : has
  REQUIREMENTS ||--o{ REQUIREMENT_REVISIONS : "history (never deleted)"
  REQUIREMENTS ||--o{ TEST_CASES : "verified by"
  TEST_CASES ||--o{ TEST_SCRIPT_REVISIONS : "versioned scripts"
  USERS ||--o{ TEST_SCRIPT_REVISIONS : "author / reviewer"
  PROJECTS ||--o{ VALIDATION_RUNS : has
  VALIDATION_RUNS ||--o{ TEST_EXECUTIONS : contains
  TEST_EXECUTIONS }o--|| TEST_SCRIPT_REVISIONS : "exact revision executed"
  TEST_EXECUTIONS }o--|| REQUIREMENTS : "requirement + revision at run time"
```

Traceability chain: **Requirement (rev) → Test Case → Script Revision (rev, SHA-256, approver)
→ Test Execution (verdict, log, duration) → Validation Run (repo, branch, commit SHA, trigger,
quality gate)**.

Key constraints: unique `(project, req_id)`, `(project, tc_id)`, `(requirement, revision)`,
`(test_case, revision)`, `(run, script_revision)`; unique `validation_runs.idempotency_key`.

## 3. Dynamic test registry

No allowlist and no rebuild. The executable set is computed per run as *the latest **approved**
revision of each test case* of the project (`services/validation.py: executable_scripts`).
When a run is queued, EVAP snapshots exactly which revisions it will execute (one
`test_executions` row each) and stores a **baseline hash** over `(test_case, revision, sha256)`.
Saving a new draft never changes what runs. Only approval does.

## 4. Continuous validation sequence

```mermaid
sequenceDiagram
  autonumber
  actor Dev as Developer
  participant GH as GitHub (mini-bms)
  participant SHR as Self-hosted runner
  participant API as EVAP backend
  participant RN as EVAP runner
  participant SB as Sandbox container
  Dev->>GH: git push (main)
  GH->>SHR: workflow job (push to main only)
  SHR->>API: POST /api/ci/trigger {sha, branch, event} (Bearer CI token)
  API->>API: auto enabled? branch matches? key = H(project, sha, baseline)
  alt already validated (same commit + same test baseline)
    API-->>SHR: DUPLICATE + existing run
  else new
    API-->>SHR: CREATED run (QUEUED)
  end
  RN->>API: POST /api/runner/claim
  API-->>RN: run + script revisions (source, sha256)
  RN->>GH: git fetch (read-only deploy key, pinned host key)
  RN->>RN: git archive <exact sha>, verify script checksums
  loop each approved script revision
    RN->>SB: create (no network, non-root, limits) · put workspace · start
    SB-->>RN: exit code (0 PASS · 1 FAIL · other/timeout ERROR) + log
    RN->>API: POST /api/runner/executions/{id}
    RN->>SB: remove
  end
  RN->>API: POST /api/runner/runs/{id}/complete → verdict + quality gate
  loop every 3 s
    SHR->>API: GET /api/ci/runs/{id}
  end
  SHR-->>GH: job success / failure = quality gate
```

## 5. Run states and quality gate

- Run / execution states: `QUEUED → RUNNING → PASS | FAIL | ERROR`.
- Run verdict: any FAIL → `FAIL`; else any ERROR → `ERROR`; else `PASS`. No approved scripts → `ERROR`.
- Quality gate policies: `all_pass` (every executed test passes) or `pass_rate` (≥ threshold %).
  Gate = `PASSED`/`FAILED`; the CI client exits 0/1 accordingly.
- Crash safety: on start-up the runner calls `/api/runner/recover`, which closes runs left `RUNNING` as `ERROR`.

## 6. Metrics (Overview)

Computed over the latest completed **regression** run (not single-test manual runs):
- **Mapping coverage**: requirements with ≥ 1 test case / all requirements (design-time).
- **Execution coverage**: requirements with ≥ 1 executed test in the latest campaign / all requirements.
- **Pass rate**: passed executions / executed tests in the latest campaign.

## 7. Key design decisions

| Decision | Reason |
|---|---|
| Runner polls the DB-backed queue via the API | No broker needed (no Redis/Celery); `SKIP LOCKED` allows several runners later. |
| One container per script revision | Tests cannot interfere with each other; cleanup is trivial. |
| Workspace copied in with `put_archive` | No host bind mounts, so the sandbox sees nothing of the host. |
| Self-hosted runner + localhost API | GitHub Actions reaches EVAP without any inbound port or tunnel. |
| SUT checked out by EVAP, not by the CI job | The verdict always refers to the commit EVAP itself fetched; the CI host never runs SUT code. |
| Single published port (nginx) | One origin for UI and API; strict CSP; backend unreachable from outside. |
