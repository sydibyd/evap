"""Excel SRS import/template. Imports are additive: they create or revise requirements
and never delete requirements, test cases or validation evidence."""
import io

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Requirement, RequirementRevision

COLUMNS = ["Requirement_ID", "Subsystem", "Description", "Priority", "Status"]
FIELDS = {"Subsystem": "subsystem", "Description": "description", "Priority": "priority", "Status": "status"}


class ImportError_(ValueError):
    pass


def build_template(example: bool = True) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Requirements"
    ws.append(COLUMNS)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E79")
    if example:
        ws.append(["SW-001", "Thermal Management",
                   "The BMS shall disable charging when the battery temperature is greater than or "
                   "equal to 60 degrees Celsius. Charging shall remain permitted below this threshold "
                   "when all other charging conditions are satisfied.",
                   "High", "Approved"])
    for col, width in zip("ABCDE", (16, 22, 90, 10, 12)):
        ws.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cell(v) -> str:
    return "" if v is None else str(v).strip()


def parse_rows(data: bytes) -> list[dict]:
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises many types for bad files
        raise ImportError_(f"Not a valid .xlsx file: {exc.__class__.__name__}")
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ImportError_("Workbook is empty")
    header = [_cell(h) for h in rows[0]]
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        raise ImportError_(f"Missing required columns: {', '.join(missing)}")
    idx = {c: header.index(c) for c in COLUMNS}
    out, seen = [], set()
    for n, row in enumerate(rows[1:], start=2):
        row = list(row) + [None] * (len(header) - len(row))
        rid = _cell(row[idx["Requirement_ID"]])
        if not rid:
            if any(_cell(v) for v in row):
                raise ImportError_(f"Row {n}: Requirement_ID is empty")
            continue
        if len(rid) > 64:
            raise ImportError_(f"Row {n}: Requirement_ID too long")
        if rid in seen:
            raise ImportError_(f"Row {n}: duplicate Requirement_ID {rid}")
        seen.add(rid)
        out.append({"req_id": rid, **{f: _cell(row[idx[c]]) for c, f in FIELDS.items()}})
    return out


def import_requirements(db: Session, project_id: int, data: bytes, filename: str, author: str) -> dict:
    rows = parse_rows(data)
    created, revised, unchanged = [], [], []
    for r in rows:
        req = db.scalar(select(Requirement).where(
            Requirement.project_id == project_id, Requirement.req_id == r["req_id"]))
        fields = {f: r[f] for f in FIELDS.values()}
        if req is None:
            req = Requirement(project_id=project_id, req_id=r["req_id"], revision=1, **fields)
            db.add(req)
            db.flush()
            created.append(r["req_id"])
        elif all(getattr(req, k) == v for k, v in fields.items()):
            unchanged.append(r["req_id"])
            continue
        else:
            for k, v in fields.items():
                setattr(req, k, v)
            req.revision += 1
            revised.append(r["req_id"])
        db.add(RequirementRevision(requirement_id=req.id, revision=req.revision,
                                   source=f"excel:{filename}"[:256], author=author, **fields))
    existing = db.scalars(select(Requirement.req_id).where(Requirement.project_id == project_id)).all()
    not_in_file = sorted(set(existing) - {r["req_id"] for r in rows})
    db.commit()
    return {"created": created, "revised": revised, "unchanged": unchanged,
            "not_in_file_kept": not_in_file}
