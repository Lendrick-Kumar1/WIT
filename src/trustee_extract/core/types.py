"""Shared data types and component interfaces (ARCHITECTURE.md §6).

Coordinates are PDF points with a top-left origin (PyMuPDF convention): (x0, y0, x1, y1).
Pages are 1-based everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import pandas as pd

    from trustee_extract.core.page_model import PageModel

BBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str


@dataclass
class Box:
    page: int
    bbox: BBox
    label: str  # "table" | "table_title" | "section_header" | "key_value_block" | ...
    score: float
    source: str  # "egret" | "yolo" | "geometry" | ...


@dataclass
class TableGrid:
    page: int
    bbox: BBox
    title: str
    col_cuts: list[float]
    header_rows: int
    cells: list[list[str]]
    cell_boxes: list[list[BBox]]  # provenance per cell
    source: str
    debug: dict = field(default_factory=dict)


@dataclass
class LogicalTable:
    name: str
    pages: list[int]
    df: "pd.DataFrame"
    grids: list[TableGrid]


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class DocContext:
    pdf_path: str
    sha256: str
    trustee: str | None = None


class Detector(Protocol):
    """Finds table (and related) boxes on a page. Implementations: egret, yolo, geometry."""

    def detect(self, page: "PageModel") -> list[Box]: ...


class StructureExtractor(Protocol):
    def extract(self, page: "PageModel", box: Box) -> TableGrid: ...


class Validator(Protocol):
    def check(self, table: LogicalTable, ctx: DocContext) -> list[CheckResult]: ...
