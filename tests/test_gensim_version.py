"""Тесты версионирования gensim-модели."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from keywords.gensim_extractor import (
    get_gensim_model_version,
    next_gensim_model_version,
    write_gensim_meta,
    default_model_dir,
)


class TestGensimModelVersion:
    def test_next_version_increments(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "keywords.gensim_extractor.default_model_dir",
            lambda: tmp_path,
        )
        write_gensim_meta(1, model_dir=tmp_path, document_count=100, limit=100)
        assert next_gensim_model_version(tmp_path) == 2

    def test_legacy_model_without_meta_returns_one(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "keywords.gensim_extractor.default_model_dir",
            lambda: tmp_path,
        )
        (tmp_path / "dictionary.gensim").write_text("stub")
        (tmp_path / "tfidf.gensim").write_text("stub")
        assert get_gensim_model_version(tmp_path) == 1

    def test_missing_model_returns_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "keywords.gensim_extractor.default_model_dir",
            lambda: tmp_path,
        )
        assert get_gensim_model_version(tmp_path) == 0

    def test_meta_written(self, tmp_path):
        meta = write_gensim_meta(3, model_dir=tmp_path, document_count=500, limit=80000)
        assert meta["version"] == 3
        loaded = json.loads((tmp_path / "meta.json").read_text())
        assert loaded["document_count"] == 500
