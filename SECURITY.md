# EVAP Security

EVAP is an MVP for local or trusted-network deployment. This file lists the controls that are
implemented (and tested) and the limitations that remain before any production use.

## Implemented controls

| Area | Control | Verified by |
|---|---|---|
| Authentication | Username/password (PBKDF2-SHA256, 240k iterations, per-user salt); HS256 JWT with expiry; secret from env (≥ 32 chars) | `backend/tests` |
| Authorization | Roles engineer / reviewer / admin enforced server-side on every endpoint; CI configuration needs reviewer/admin; user management needs admin | `test_roles` |
| Four-eyes | Script authors cannot approve their own revision; only `draft` revisions can be reviewed; checksum re-verified at approval | `test_script_validation_and_four_eyes` |
| Execution policy | Only the latest **approved** revision executes (manual and automatic); no approved scripts → no execution | `test_manual_run_requires_approved_script` |
| Integrity | SHA-256 per script revision; the runner refuses to execute when the source does not match the checksum | runner code |
| CI authentication | Per-project CI token (`evapci_…`), only its SHA-256 is stored, shown once, can be rotated; scoped to its own project's runs | `test_ci_trigger_idempotency_and_gate` |
| Runner API | Separate shared secret (`EVAP_RUNNER_TOKEN`), constant-time comparison | `test_manual_run_and_runner_flow` |
| Input validation | Pydantic schemas; codes/branches by regex; repository URL restricted to `https://` / `git@host:` (no `file://`, local paths, `ext::`, shell characters); size limits on scripts/uploads; Excel parsed with `openpyxl` (no macros, `data_only`) | `test_repo_url_validation`, `test_excel_bad_files` |
| No shell from UI | No endpoint accepts commands; Git runs with argument lists (no shell) and `--` separators | code review |
| SIL sandbox | Per-test disposable container: `network_mode=none`, uid 10001, `cap_drop=ALL`, `no-new-privileges`, 256 MiB memory (no swap), 1 CPU, 128 PIDs, 64 MiB `/tmp` tmpfs, hard timeout + kill, no bind mounts, no Docker socket, no env secrets, symlinks and `..` dropped from the SUT archive, always removed | `runner/sandbox_check.py` (live), `runner/tests` |
| Network exposure | Only nginx is published, on `127.0.0.1:8300`; backend and DB sit on an `internal` Docker network without Internet access | compose config |
| Containers | Backend: read-only rootfs, non-root, `no-new-privileges`; runner: non-root (docker group only), `no-new-privileges` | compose config |
| Git access | Private SUT cloned with a **read-only deploy key scoped to that one repository**; GitHub SSH host key pinned (`runner/known_hosts`), `StrictHostKeyChecking=yes` | live demo |
| Secrets | All secrets in `.env` / `secrets/` (git-ignored, mode 600); `.env.example` has placeholders only; no credentials in code or images | `git ls-files` |
| HTTP headers | Strict CSP (`script-src 'self'`), `X-Frame-Options DENY`, `nosniff`, `no-referrer`; Swagger page has its own narrower CSP that allows only jsDelivr | curl |
| CI hardening | Workflow is triggered **only** by `push` to `main` of the **private** repo (job-level guard on repository, ref and event); `permissions: contents: read`; repo allows only GitHub-owned actions; default `GITHUB_TOKEN` read-only; only `.github/evap` is sparse-checked out and SUT code is never executed on the runner host | GitHub settings |

## Self-hosted runner policy

- Attached **only** to the private `mini-bms` repository. It is **never** attached to a public
  repository (the public `evap` repo has no workflows and no runner).
- No `pull_request` / `pull_request_target` triggers, so untrusted pull requests never run on
  this machine.
- Runs as the local user, not as root, and not as a system service. The CI job only sends HTTP
  requests to EVAP on localhost.

## Known limitations (MVP)

1. **Runner has the Docker socket.** The `runner` container (trusted EVAP code) needs it to
   create sandboxes, and the socket is root-equivalent on the host. Sandboxes never get it.
   Production: rootless Docker/Podman, gVisor/Kata, or a dedicated VM for execution.
2. **Sandbox root filesystem is writable** by uid 10001 in the paths it owns (needed for
   `put_archive`). It is still non-root, capability-free and discarded after each test.
   `read_only` + a tmpfs workspace would be stronger.
3. **Approved scripts are trusted code.** Isolation limits the blast radius, but a reviewer
   still has to read scripts before approval. Static checks only warn; they do not block.
4. **Self-hosted runner trust**: anyone with push access to the private SUT repo can change the
   workflow, which then runs on this host as the local user. Keep write access limited to trusted
   people. Consider branch protection and an isolated VM for the runner.
5. **No TLS** (localhost only). Put a TLS-terminating proxy in front before exposing EVAP on a
   network. The JWT is kept in `localStorage`, so XSS would expose it (mitigated by the strict CSP).
6. **No login rate limiting, lockout, MFA or password reset**, and no token revocation (logout
   is client-side; tokens expire after `EVAP_JWT_TTL_MINUTES`).
7. **Bootstrap admin password** stays in `.env` after first start. Change it in the UI or remove
   it from `.env` afterwards.
8. **Single shared runner token**, no audit log of user actions beyond author/reviewer/run
   metadata.
9. SIL environments offer only Python 3.11 + pytest; tests cannot install dependencies (no network).
10. Default credentials do not exist. Every secret must be generated (see `.env.example`).
