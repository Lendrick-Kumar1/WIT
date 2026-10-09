import json

import pymupdf
import yaml

from trustee_extract.core.config import sha256_file
from trustee_extract.core.types import Box
from trustee_extract.review.labelstudio_export import export


class FakeDetector:
    def detect_pages(self, pdf, first, last):
        return [
            Box(first, (0, 0, 300, 200), "table", 0.9, "egret"),
            Box(first, (300, 0, 600, 200), "table", 0.8, "egret"),  # adjacent table, own box
            Box(first, (0, 300, 100, 320), "text", 0.9, "egret"),   # not a class -> dropped
        ]


def make_pdf(path, pages=2):
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=600, height=800).insert_text((50, 50), "Par Value Tests 1,234.50")
    doc.save(path)
    return path


def test_export_tasks(tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf")
    n = export([pdf], tmp_path / "ls", pages="2", golden_manifest=tmp_path / "none.yaml", detector=FakeDetector())
    assert n == 1
    tasks = json.loads((tmp_path / "ls" / "tasks.json").read_text())
    t = tasks[0]
    assert t["data"]["page"] == 2 and t["data"]["image"].endswith("a_p002.png")
    res = t["predictions"][0]["result"]
    assert [r["value"]["rectanglelabels"] for r in res] == [["table"], ["table"]]
    assert res[1]["value"]["x"] == 50.0 and res[1]["value"]["width"] == 50.0  # percent of page
    assert res[0]["value"]["height"] == 25.0
    assert (tmp_path / "ls" / "images" / "a_p002.png").exists()
    xml = (tmp_path / "ls" / "label_config.xml").read_text()
    for c in ("table", "table_title", "section_header", "key_value_block"):
        assert f'value="{c}"' in xml


def test_golden_docs_excluded(tmp_path):
    pdf = make_pdf(tmp_path / "g.pdf")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(yaml.safe_dump({"documents": [{"file": "g.pdf", "sha256": sha256_file(pdf)}]}))
    assert export([pdf], tmp_path / "ls", golden_manifest=manifest, detector=FakeDetector()) == 0
