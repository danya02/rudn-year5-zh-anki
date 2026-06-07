"""Lesson schema migration engine (pipeline._migrate_lesson)."""

import pytest

import pipeline as pl


def test_markerless_file_stamped_to_current():
    data, changed = pl._migrate_lesson("t", {"words": [], "sentences": []})
    assert data["version"] == pl.SCHEMA_VERSION
    assert changed is True  # marker added → file should be rewritten


def test_current_version_is_unchanged():
    data, changed = pl._migrate_lesson(
        "t", {"version": pl.SCHEMA_VERSION, "words": [], "sentences": []}
    )
    assert changed is False


def test_chained_migration_runs_and_transforms(monkeypatch):
    def v1_to_v2(d):
        for w in d["words"]:
            w["new_field"] = "x"
        return d

    monkeypatch.setattr(pl, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(pl, "_MIGRATIONS", {1: v1_to_v2})
    data, changed = pl._migrate_lesson(
        "t", {"version": 1, "words": [{"character": "好"}], "sentences": []}
    )
    assert changed is True
    assert data["version"] == 2
    assert data["words"][0]["new_field"] == "x"


def test_markerless_file_migrates_under_newer_schema(monkeypatch):
    monkeypatch.setattr(pl, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(pl, "_MIGRATIONS", {1: lambda d: d})
    data, _ = pl._migrate_lesson("t", {"words": [], "sentences": []})
    assert data["version"] == 2


def test_missing_migration_step_raises(monkeypatch):
    monkeypatch.setattr(pl, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(pl, "_MIGRATIONS", {})
    with pytest.raises(ValueError, match="No migration"):
        pl._migrate_lesson("t", {"version": 1, "words": [], "sentences": []})


def test_file_newer_than_app_is_refused():
    with pytest.raises(ValueError, match="newer than this app"):
        pl._migrate_lesson(
            "t", {"version": pl.SCHEMA_VERSION + 1, "words": [], "sentences": []}
        )
