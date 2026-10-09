"""Real Docling conversion with network blocked: proves the offline config works."""

import socket
from pathlib import Path

import pytest

from trustee_extract.core.config import REPO_ROOT, docling_artifacts_path

PDF = REPO_ROOT / "reports" / "bny_1.pdf"

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not PDF.exists(), reason="reports/bny_1.pdf not present"),
    pytest.mark.skipif(not docling_artifacts_path().is_dir(), reason="Docling models not cached"),
]


@pytest.fixture
def no_network(monkeypatch):
    def deny(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"network access attempted: {address}")
        return real(self, address, *a, **k)

    real = socket.socket.connect
    monkeypatch.setattr(socket.socket, "connect", deny)


@pytest.fixture(scope="module")
def converter():
    from trustee_extract.detect.docling_layout import build_converter

    return build_converter()


def test_page1_converts_offline(converter, no_network):
    res = converter.convert(PDF, page_range=(1, 1))
    assert res.status.value == "success"
    assert len(res.pages) == 1


def test_page4_tableformer(converter, no_network):
    res = converter.convert(PDF, page_range=(4, 4))
    doc = res.document
    assert len(doc.tables) >= 1
    df = doc.tables[0].export_to_dataframe(doc=doc)
    assert "Numerator" in df.columns
    assert df.astype(str).apply(lambda c: c.str.contains("Class A/B Par Value Test")).any().any()
