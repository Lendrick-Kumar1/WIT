import yaml

from trustee_extract.core.config import DEFAULTS, build_config, threads_per_worker
from trustee_extract.doctor import recommend_workers


def test_defaults_have_no_machine_specific_paths():
    text = DEFAULTS.read_text(encoding="utf-8")
    assert "C:/Users" not in text and "C:\\Users" not in text
    cfg = build_config(local=DEFAULTS.parent / "nope.yaml", env={})
    assert cfg["runtime"]["workers"] == 1
    assert cfg["docling"]["artifacts_path"].startswith("~")


def test_local_yaml_then_env_override(tmp_path):
    local = tmp_path / "local.yaml"
    local.write_text(yaml.safe_dump({"runtime": {"workers": 2}, "paths": {"reports": "D:/r"}}))
    cfg = build_config(local=local, env={})
    assert cfg["runtime"]["workers"] == 2 and cfg["paths"]["reports"] == "D:/r"
    assert cfg["runtime"]["min_free_ram_gb_for_2_workers"] == 8  # untouched keys survive the merge
    cfg = build_config(local=local, env={"TE_WORKERS": "1", "DOCLING_ARTIFACTS_PATH": "E:/m"})
    assert cfg["runtime"]["workers"] == 1 and cfg["docling"]["artifacts_path"] == "E:/m"


def test_threads_split_cores(monkeypatch):
    monkeypatch.setattr("trustee_extract.core.config.physical_cores", lambda: 4)
    assert threads_per_worker({"runtime": {"workers": 1, "threads_per_worker": None}}) == 4
    assert threads_per_worker({"runtime": {"workers": 2, "threads_per_worker": None}}) == 2
    assert threads_per_worker({"runtime": {"workers": 2, "threads_per_worker": 3}}) == 3


def test_recommend_workers():
    assert recommend_workers(free_gb=5.5, peak_gb=1.1, cores=4, min_free_for_2=8) == 1   # typical laptop
    assert recommend_workers(free_gb=9.0, peak_gb=1.1, cores=4, min_free_for_2=8) == 2
    assert recommend_workers(free_gb=9.0, peak_gb=3.0, cores=4, min_free_for_2=8) == 1   # 2*3+4 > 9
    assert recommend_workers(free_gb=12, peak_gb=1.1, cores=2, min_free_for_2=8) == 1
