import os

import pytest

from trustee_extract.core.config import docling_artifacts_path, load_config


@pytest.fixture
def cfg(tmp_path):
    c = load_config()
    c = {**c, "docling": {**c["docling"], "artifacts_path": str(tmp_path)}}
    return c


def test_defaults_are_offline_egret_accurate_no_ocr():
    d = load_config()["docling"]
    assert d["do_ocr"] is False
    assert d["layout_preset"] == "layout_egret_large"
    assert d["table_mode"] == "accurate"
    assert d["num_threads"] * 2 <= os.cpu_count()  # 2 workers max


def test_env_overrides_artifacts_path(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCLING_ARTIFACTS_PATH", str(tmp_path))
    assert docling_artifacts_path() == tmp_path


def test_pipeline_options(cfg, monkeypatch):
    monkeypatch.delenv("DOCLING_ARTIFACTS_PATH", raising=False)
    from trustee_extract.detect.docling_layout import build_pipeline_options

    opts = build_pipeline_options(cfg)
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert opts.do_ocr is False
    assert opts.do_table_structure is True
    assert opts.enable_remote_services is False
    assert opts.table_structure_options.mode.value == "accurate"
    assert opts.layout_options.model_spec.repo_id == "docling-project/docling-layout-egret-large"
    assert str(opts.artifacts_path) == cfg["docling"]["artifacts_path"]


def test_missing_models_raise(cfg, monkeypatch, tmp_path):
    monkeypatch.delenv("DOCLING_ARTIFACTS_PATH", raising=False)
    from trustee_extract.detect.docling_layout import build_pipeline_options

    cfg["docling"]["artifacts_path"] = str(tmp_path / "missing")
    with pytest.raises(FileNotFoundError):
        build_pipeline_options(cfg)
