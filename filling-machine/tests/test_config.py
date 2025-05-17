#!/usr/bin/env python3
"""
A standalone script to load and display all entries from a config.json file.
Usage:
    python test_config.py /full/path/to/config.json
"""
import json
import pytest
import os
from config import Config

@pytest.fixture
def tmp_config_file(tmp_path):
    # Create a temp JSON config file
    data = {
        "Foo": 1.23,
        "Foo_mould": 0.45,
        "mqttBroker": "test:1883"
    }
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path), data

def test_config_loads(tmp_config_file):
    path, data = tmp_config_file
    cfg = Config(path)
    # Check each key via get and raw data
    for key, val in data.items():
        assert cfg.get(key) == pytest.approx(val)
        assert cfg._data[key] == val

def test_config_missing_file(tmp_path):
    missing = str(tmp_path / "does_not_exist.json")
    with pytest.raises(FileNotFoundError):
        Config(missing)

def test_config_empty_file(tmp_path):
    empty_file = tmp_path / "empty.json"
    empty_file.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        Config(str(empty_file))

def test_config_invalid_json(tmp_path):
    invalid_file = tmp_path / "invalid.json"
    invalid_file.write_text("{ invalid json }", encoding="utf-8")
    with pytest.raises(ValueError):
        Config(str(invalid_file))
