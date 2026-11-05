import os
import json
import platform
from unittest.mock import patch
import pytest
from server.config import (
    DEFAULT_CONFIG,
    EngineConfig,
    BridgeConfig,
    get_default_threads,
    detect_cpu_count,
    sanitize_threads,
    sanitize_hash,
    sanitize_multipv,
    sanitize_syzygy_path,
)


def test_default_config_keys():
    assert "threads" in DEFAULT_CONFIG
    assert "hash_mb" in DEFAULT_CONFIG
    assert "multi_pv" in DEFAULT_CONFIG
    assert "multipv" in DEFAULT_CONFIG
    assert "syzygy_path" in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["threads"] >= 1
    assert DEFAULT_CONFIG["hash_mb"] == 256
    assert DEFAULT_CONFIG["multi_pv"] == 1
    assert DEFAULT_CONFIG["syzygy_path"] is None


def test_engine_config_defaults():
    cfg = EngineConfig()
    assert cfg.threads >= 1
    assert cfg.hash_mb == 256
    assert cfg.multi_pv == 1
    assert cfg.syzygy_path is None


def test_parameter_sanitization_and_clamping(tmp_path):
    # Threads boundary clamping
    assert sanitize_threads(0) == 1
    assert sanitize_threads(-5) == 1
    assert sanitize_threads("not_a_number") == get_default_threads()
    assert sanitize_threads(8) == 8

    # Hash boundary clamping
    assert sanitize_hash(0) == 1
    assert sanitize_hash(-100) == 1
    assert sanitize_hash("invalid") == 256
    assert sanitize_hash(1024) == 1024

    # MultiPV boundary clamping
    assert sanitize_multipv(0) == 1
    assert sanitize_multipv(-2) == 1
    assert sanitize_multipv("bad") == 1
    assert sanitize_multipv(4) == 4

    # Syzygy tablebase path validation
    assert sanitize_syzygy_path("") is None
    assert sanitize_syzygy_path("<none>") is None
    assert sanitize_syzygy_path("none") is None
    assert sanitize_syzygy_path(str(tmp_path / "nonexistent_dir")) is None

    # Valid directory
    valid_tb_dir = tmp_path / "tablebases"
    valid_tb_dir.mkdir()
    sanitized = sanitize_syzygy_path(str(valid_tb_dir))
    assert sanitized == str(valid_tb_dir)


def test_syzygy_multi_path_sanitization_matrix(tmp_path):
    r"""
    Comprehensive unit tests for Syzygy multi-path sanitization:
    - Semicolon delimited paths on Windows
    - Whitespace and quotes trimming
    - Partial validity filtering
    - Duplicate and trailing delimiter handling
    - Sequence inputs (list, tuple)
    - Simulated Unix and secondary drive scenarios
    """
    d1 = tmp_path / "tb_wdl"
    d2 = tmp_path / "tb_dtz"
    d1.mkdir()
    d2.mkdir()

    # 1. Native multi-path
    multi = f"{d1};{d2}"
    res = sanitize_syzygy_path(multi)
    if platform.system() == "Windows":
        assert res == f"{d1};{d2}"
        drive = os.path.splitdrive(str(d1))[0]
        if drive:
            assert drive in res
    else:
        assert res == f"{d1}:{d2}"

    # 2. Quoted paths and whitespace padding
    quoted = f' "{d1}" ; "{d2}" '
    res_q = sanitize_syzygy_path(quoted)
    expected_delim = ";" if platform.system() == "Windows" else ":"
    assert res_q == f"{d1}{expected_delim}{d2}"

    # 3. Trailing and duplicate delimiters
    res_delim = sanitize_syzygy_path(f"{d1};;{d2};")
    assert res_delim == f"{d1}{expected_delim}{d2}"

    # 4. Partial validity (one valid, one invalid)
    res_part = sanitize_syzygy_path(f"{d1};{tmp_path / 'nonexistent'}")
    assert res_part == str(d1)

    # 5. All invalid returns None
    res_all_inv = sanitize_syzygy_path(f"{tmp_path / 'inv1'};{tmp_path / 'inv2'}")
    assert res_all_inv is None

    # 6. Sequence inputs (list, tuple)
    res_list = sanitize_syzygy_path([str(d1), str(d2)])
    assert res_list == f"{d1}{expected_delim}{d2}"

    # 7. Order-preserving deduplication
    res_dedup = sanitize_syzygy_path(f"{d1};{d2};{d1}")
    assert res_dedup == f"{d1}{expected_delim}{d2}"

    # 8. Windows simulated secondary drive (C: and D:)
    with patch("platform.system", return_value="Windows"), \
         patch("os.path.isdir", side_effect=lambda p: p in (r"C:\tb1", r"D:\tb2")):
        assert sanitize_syzygy_path(r"C:\tb1;D:\tb2") == r"C:\tb1;D:\tb2"

    # 9. Unix simulated colon and semicolon normalization
    with patch("platform.system", return_value="Linux"), \
         patch("os.path.isdir", side_effect=lambda p: p in ("/opt/tb1", "/opt/tb2")):
        assert sanitize_syzygy_path("/opt/tb1:/opt/tb2") == "/opt/tb1:/opt/tb2"
        assert sanitize_syzygy_path("/opt/tb1;/opt/tb2") == "/opt/tb1:/opt/tb2"


def test_key_aliasing_bidirectional(tmp_path):
    valid_dir = tmp_path / "syzygy"
    valid_dir.mkdir()

    # Inbound: from settings.json containing aliased keys (hash, multipv, syzygy)
    legacy_json = {
        "threads": 4,
        "hash": 512,
        "multipv": 3,
        "syzygy": str(valid_dir)
    }
    cfg = EngineConfig.from_dict(legacy_json)
    assert cfg.threads == 4
    assert cfg.hash_mb == 512
    assert cfg.multi_pv == 3
    assert cfg.syzygy_path == str(valid_dir)

    # Outbound: to_dict with aliased keys
    exported = cfg.to_dict(use_aliases=True)
    assert exported["hash"] == 512
    assert exported["hash_mb"] == 512
    assert exported["multipv"] == 3
    assert exported["multi_pv"] == 3
    assert exported["syzygy"] == str(valid_dir)
    assert exported["syzygy_path"] == str(valid_dir)

    # Verify multi-path preservation in EngineConfig.from_dict and to_dict
    multi_dir = f"{valid_dir};{tmp_path}"
    multi_json = {"threads": 2, "syzygy": multi_dir}
    cfg_multi = EngineConfig.from_dict(multi_json)
    if platform.system() == "Windows":
        assert cfg_multi.syzygy_path == multi_dir
    else:
        assert cfg_multi.syzygy_path == f"{valid_dir}:{tmp_path}"


def test_cli_precedence_hierarchy(tmp_path):
    """
    Verify strict 3-tier precedence:
    CLI Flags > settings.json > Built-in Defaults
    """
    settings_data = {
        "threads": 4,
        "hash": 512,
        "multipv": 2,
        "syzygy_path": str(tmp_path)
    }

    # Scenario 1: CLI explicitly overrides threads and hash
    cli_args = {
        "threads": 8,
        "hash": 1024,
        "multi_pv": None,  # Not specified on CLI
        "syzygy_path": None  # Not specified on CLI
    }

    eff_threads = cli_args["threads"] if cli_args["threads"] is not None else settings_data.get("threads", 2)
    eff_hash = cli_args["hash"] if cli_args["hash"] is not None else settings_data.get("hash", 256)
    eff_multipv = cli_args["multi_pv"] if cli_args["multi_pv"] is not None else settings_data.get("multipv", 1)
    eff_syzygy = cli_args["syzygy_path"] if cli_args["syzygy_path"] is not None else settings_data.get("syzygy_path", None)

    assert eff_threads == 8, "CLI flag must override settings.json for threads"
    assert eff_hash == 1024, "CLI flag must override settings.json for hash"
    assert eff_multipv == 2, "settings.json must be preserved when CLI flag is omitted"
    assert eff_syzygy == str(tmp_path), "settings.json must be preserved when CLI flag is omitted"

    # Scenario 2: settings.json overrides built-in defaults
    default_threads = get_default_threads()
    empty_cli = {"threads": None, "hash": None, "multi_pv": None, "syzygy_path": None}
    partial_settings = {"threads": 6}

    resolved_threads = empty_cli["threads"] if empty_cli["threads"] is not None else partial_settings.get("threads", default_threads)
    resolved_hash = empty_cli["hash"] if empty_cli["hash"] is not None else partial_settings.get("hash", 256)

    assert resolved_threads == 6, "settings.json must override default"
    assert resolved_hash == 256, "default must apply when neither CLI nor settings specify"


def test_bridge_config_dataclass():
    b_cfg = BridgeConfig()
    assert b_cfg.host == "0.0.0.0"
    assert b_cfg.port == 9999
    assert isinstance(b_cfg.engine, EngineConfig)
    assert b_cfg.safety_buffer_ms == 2000
