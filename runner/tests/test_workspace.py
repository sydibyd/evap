import io
import os
import sys
import tarfile

os.environ.setdefault("EVAP_RUNNER_TOKEN", "t")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import runner  # noqa: E402


def _tar(entries):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for name, kind, data in entries:
            ti = tarfile.TarInfo(name)
            if kind == "sym":
                ti.type, ti.linkname = tarfile.SYMTYPE, "/etc/passwd"
                t.addfile(ti)
            else:
                ti.size = len(data)
                t.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def test_workspace_layout_and_sanitising():
    src = _tar([("bms/core.py", "f", b"x=1"), ("evil", "sym", b""), ("../escape.py", "f", b"bad")])
    ws = tarfile.open(fileobj=io.BytesIO(runner.build_workspace(src, "test_tc.py", "def test_a(): pass")))
    names = {m.name: m for m in ws.getmembers()}
    assert set(names) == {"sut/bms/core.py", "tests/conftest.py", "tests/test_tc.py"}
    assert all(m.uid == runner.SANDBOX_UID for m in names.values())
    assert b"/work/sut" in ws.extractfile("tests/conftest.py").read()
