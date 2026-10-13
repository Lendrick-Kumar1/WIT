"""Which PDF to read for a deal and a month.

Folder layout (names in config/settings.yaml):

    <reports_root>/<deal folder>/<report type>/<month folder>/<any name>.pdf
    e.g.  Reports/Deal A/Monthly Trustee Report/2026_08/Trustee Report.pdf

- Report types are tried in the priority order of `report_types` (Monthly first, ...); the first
  one that has the month wins.
- A month folder is recognised by its name: a 4-digit year then the month, e.g. 2026_08, 2026-08,
  2026_8, 202608, 2026_08_15. A PDF whose OWN name carries the month, directly inside the report
  type folder, is accepted too.
- Every candidate PDF is checked (check_pdf). Broken files are skipped and reported.
- Normally there is one PDF. If there are several: identical copies -> one is used; different
  files -> the newest is used and the run report says so.

Deal, trustee and month always come from the deal list and the user's selection, never from the
PDF text.
"""
import hashlib
import re
from pathlib import Path

import pandas as pd
import pymupdf

MONTH_IN_NAME = re.compile(r"(?<!\d)(\d{4})[ _.-]?(\d{1,2})(?!\d)")


# ---------------------------------------------------------------------------------------------
# months
# ---------------------------------------------------------------------------------------------
def month_of(name):
    """'2026_08' / '2026-8' / '202608' / '2026_08_15' -> (2026, 8), else None.
    If a name holds several, the LAST one counts ('Deal 2019-1 2026_08' -> 2026-08)."""
    found = None
    for m in MONTH_IN_NAME.finditer(name):
        y, mo = int(m.group(1)), int(m.group(2))
        if 1990 < y < 2100 and 1 <= mo <= 12:
            found = (y, mo)
    return found


def parse_month(text):
    """'2026-08' / '2026_8' / '202608' -> (2026, 8). Raises ValueError otherwise."""
    ym = month_of(str(text))
    if not ym:
        raise ValueError(f"not a month: {text!r} (use YYYY-MM)")
    return ym


def months_between(first, last):
    """('2026-01', '2026-03') -> [(2026, 1), (2026, 2), (2026, 3)]."""
    (y, m), end = parse_month(first), parse_month(last)
    if (y, m) > end:
        raise ValueError(f"{first} is after {last}")
    out = []
    while (y, m) <= end:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


# ---------------------------------------------------------------------------------------------
# deal list
# ---------------------------------------------------------------------------------------------
def active_deals(settings):
    """[{deal, trustee, folder}] from the deal list Excel (filter applied)."""
    dl = settings["deal_list"]
    df = pd.read_excel(dl["path"], sheet_name=dl.get("sheet", 0))
    for col, val in (dl.get("filter") or {}).items():
        df = df[df[col].astype(str).str.strip().str.lower() == str(val).strip().lower()]
    c = dl["columns"]
    deals = [dict(deal=str(r[c["deal"]]).strip(), trustee=str(r[c["trustee"]]).strip(),
                  folder=str(r[c.get("folder") or c["deal"]]).strip()) for _, r in df.iterrows()]
    return [d for d in deals if d["deal"] and d["deal"].lower() != "nan"]


def select_deals(deals, names=None, trustee=None):
    """Deals by exact name (case-insensitive) and/or trustee text. Unknown names raise."""
    out = deals
    if names:
        by_name = {d["deal"].lower(): d for d in deals}
        unknown = [n for n in names if n.strip().lower() not in by_name]
        if unknown:
            raise ValueError("not in the deal list: " + ", ".join(unknown))
        out = [by_name[n.strip().lower()] for n in names]
    if trustee:
        out = [d for d in out if trustee.lower() in d["trustee"].lower()]
    return out


# ---------------------------------------------------------------------------------------------
# finding and checking the PDF
# ---------------------------------------------------------------------------------------------
def check_pdf(path):
    """'ok', or why the file can't be used.
    Bytes first (cheap, catches empty / non-PDF / cut-off files), then a real open."""
    path = Path(path)
    size = path.stat().st_size
    if size == 0:
        return "empty file"
    with open(path, "rb") as f:
        head = f.read(1024)
        f.seek(max(0, size - 2048))
        tail = f.read()
    if b"%PDF-" not in head:
        return "not a PDF (no PDF header)"
    if b"%%EOF" not in tail:
        return "damaged (file is cut off: no end marker)"
    try:
        doc = pymupdf.open(path)
    except Exception as e:                          # noqa: BLE001  (any failure = unusable)
        return f"cannot be opened ({e})"
    with doc:
        if doc.needs_pass:
            return "password protected"
        if doc.page_count == 0:
            return "no pages"
        if doc.is_repaired:
            return "damaged (had to be repaired to open)"
        if not any(doc[i].get_text().strip() for i in range(min(10, doc.page_count))):
            return "no text (scanned image?)"
    return "ok"


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _pdfs_for_month(type_dir, ym):
    """PDFs in the month folder(s) of one report-type folder, plus PDFs named by the month."""
    found = []
    for p in type_dir.iterdir():
        if p.is_dir() and month_of(p.name) == ym:
            found += [f for f in p.rglob("*") if f.is_file() and f.suffix.lower() == ".pdf"]
        elif p.is_file() and p.suffix.lower() == ".pdf" and month_of(p.stem) == ym:
            found.append(p)
    return sorted(found)


def _latest_month(deal_dir, report_types):
    """Most recent month available for a deal (any report type), for the MISSING message."""
    best = None
    for rtype in report_types:
        d = deal_dir / rtype
        if not d.is_dir():
            continue
        for p in d.iterdir():
            ym = month_of(p.name if p.is_dir() else p.stem)
            if ym and (best is None or ym > best[0]):
                best = (ym, rtype)
    return best


def find_report(settings, deal_folder, ym):
    """-> {pdf, report_type, file_status, file_note}
    file_status: ok | check (used, but read the note) | missing | broken"""
    root = Path(settings["reports_root"]) / deal_folder
    types = settings["report_types"]
    if not root.is_dir():
        return dict(pdf=None, report_type="", file_status="missing", file_note=f"no folder {root}")
    for rtype in types:
        d = root / rtype
        if not d.is_dir():
            continue
        cands = _pdfs_for_month(d, ym)
        if cands:
            return _pick(cands, rtype)
    latest = _latest_month(root, types)
    note = "no report for this month"
    if latest:
        note += f"; latest is {latest[0][0]}-{latest[0][1]:02d} ({latest[1]})"
    return dict(pdf=None, report_type="", file_status="missing", file_note=note)


def _pick(cands, rtype):
    checked = [(p, check_pdf(p)) for p in cands]
    good = [p for p, c in checked if c == "ok"]
    notes = [f"skipped {p.name}: {c}" for p, c in checked if c != "ok"]
    if not good:
        return dict(pdf=None, report_type=rtype, file_status="broken", file_note="; ".join(notes))
    status = "check" if notes else "ok"
    good.sort(key=lambda p: (len(p.name), p.name))         # 'Report.pdf' before 'Report (1).pdf'
    if len(good) > 1:
        if len({_md5(p) for p in good}) == 1:
            notes.append(f"{len(good)} identical copies, used {good[0].name}")
        else:
            good.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            notes.append(f"{len(good)} different PDFs, used the newest {good[0].name} "
                         f"(others: {', '.join(p.name for p in good[1:])})")
            status = "check"
    return dict(pdf=str(good[0]), report_type=rtype, file_status=status, file_note="; ".join(notes))


# ---------------------------------------------------------------------------------------------
# the plan: one job per (month, deal)
# ---------------------------------------------------------------------------------------------
def plan(settings, months, deal_names=None, trustee=None):
    """[{deal, trustee, folder, year, month, pdf, report_type, file_status, file_note}]"""
    deals = select_deals(active_deals(settings), deal_names, trustee)
    jobs = []
    for ym in months:
        for d in deals:
            jobs.append(dict(**d, year=ym[0], month=ym[1], **find_report(settings, d["folder"], ym)))
    return jobs
