"""Sandbox isolation acceptance check — executes hostile test scripts through the real runner
sandbox path (run_in_sandbox) and asserts the isolation properties.
Run: docker compose exec -T runner python sandbox_check.py
"""
import io
import sys
import tarfile

import docker

import runner

PROBE = r'''
import os, socket, pathlib
def test_not_root():
    assert os.getuid() != 0 and os.getgid() != 0
def test_no_network():
    s = socket.socket(); s.settimeout(3)
    try:
        s.connect(("1.1.1.1", 53)); raise AssertionError("network reachable")
    except OSError:
        pass
def test_no_docker_socket():
    assert not pathlib.Path("/var/run/docker.sock").exists()
def test_no_secrets_in_env():
    leaked = [k for k in os.environ if "TOKEN" in k or "SECRET" in k or "PASSWORD" in k or k.startswith("EVAP")]
    assert not leaked, leaked
def test_no_deploy_key_or_host_files():
    assert not pathlib.Path("/run/secrets").exists()
    assert not pathlib.Path("/home/saeii").exists()
def test_cannot_write_system_dirs():
    try:
        open("/etc/evil", "w"); raise AssertionError("wrote /etc")
    except PermissionError:
        pass
def test_sut_present_readonly_for_others():
    assert pathlib.Path("/work/sut/bms/core.py").exists()
'''
HANG = "def test_hang():\n    while True:\n        pass\n"
MEM = "def test_mem():\n    x = bytearray(1024 * 1024 * 1024)\n    assert x\n"


def sut():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for name, data in (("bms/__init__.py", b""), ("bms/core.py", b"X = 1\n")):
            ti = tarfile.TarInfo(name); ti.size = len(data); t.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def main():
    c = docker.from_env()
    img = runner.IMAGES["python3.11"]
    results = {}
    v, log = runner.run_in_sandbox(c, img, runner.build_workspace(sut(), "test_probe.py", PROBE), "test_probe.py", 60)
    results["isolation probes (7 checks)"] = (v == "PASS", v, log)
    v, log = runner.run_in_sandbox(c, img, runner.build_workspace(sut(), "test_hang.py", HANG), "test_hang.py", 5)
    results["timeout kills infinite loop"] = (v == "ERROR" and "TIMEOUT" in log, v, log[-200:])
    v, log = runner.run_in_sandbox(c, img, runner.build_workspace(sut(), "test_mem.py", MEM), "test_mem.py", 60)
    results["1 GiB allocation blocked by memory limit"] = (v in ("FAIL", "ERROR"), v, log[-300:])
    left = c.containers.list(all=True, filters={"label": "evap.role=sil-sandbox"})
    results["sandbox containers cleaned up"] = (not left, len(left), "")
    ok = True
    for name, (passed, v, log) in results.items():
        ok &= passed
        print(f"{'OK  ' if passed else 'FAIL'} {name}: {v}")
        if not passed:
            print(log)
    print("SANDBOX CHECK:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
