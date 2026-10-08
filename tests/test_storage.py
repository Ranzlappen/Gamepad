import json

import pytest

from app import defaults, model, settings
from app.profiles import ProfileError, ProfileStore


@pytest.fixture
def store(tmp_path):
    s = ProfileStore(tmp_path / "profiles")
    s.ensure_defaults(first_run=True)
    return s


def test_first_run_creates_the_three_templates(store):
    assert store.names() == sorted(defaults.TEMPLATE_NAMES, key=str.casefold)
    assert store.load(defaults.FPS)["buttons"]["a"]["press"]["keys"] == ["space"]


def test_create_duplicate_rename_delete(store):
    created = store.create("Mine", defaults.DESKTOP, 0.2, 0.1)
    assert created["name"] == "Mine"
    store.duplicate("Mine", "Copy")
    assert store.load("Copy") == {**store.load("Mine"), "name": "Copy"}
    store.rename("Copy", "Renamed")
    assert "Copy" not in store.names() and "Renamed" in store.names()
    store.rename("Renamed", "renamed")  # case-only rename keeps a single file
    assert len(list(store.directory.glob("renamed*.json"))) == 1
    store.delete("renamed")
    assert "renamed" not in store.names()


def test_name_rules(store):
    with pytest.raises(ProfileError):
        store.create("fps standard", defaults.EMPTY, 0.15, 0.08)  # case-insensitive duplicate
    with pytest.raises(ProfileError):
        store.create("   ", defaults.EMPTY, 0.15, 0.08)
    with pytest.raises(ProfileError):
        store.rename(defaults.EMPTY, defaults.FPS)
    assert store.unique_name(defaults.FPS) == "FPS Standard (2)"


def test_cannot_delete_last_profile(tmp_path):
    s = ProfileStore(tmp_path)
    s.create("Only", defaults.EMPTY, 0.15, 0.08)
    with pytest.raises(ProfileError):
        s.delete("Only")


def test_import_export_round_trip_and_hostile_files(store, tmp_path):
    target = tmp_path / "out.json"
    store.export(defaults.DESKTOP, target)
    imported = store.import_file(target)
    assert imported["name"] == "Desktop / Mouse (2)"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ProfileError):
        store.import_file(bad)
    weird = tmp_path / "weird.json"
    weird.write_text(json.dumps({"name": "W", "buttons": {"a": {"press": {"type": "rm -rf"}}}}))
    assert store.import_file(weird)["buttons"]["a"] == model.make_slot()


def test_unreadable_files_are_skipped(tmp_path):
    (tmp_path / "junk.json").write_text("nope", encoding="utf-8")
    s = ProfileStore(tmp_path)
    assert s.names() == []
    assert s.ensure_defaults(first_run=False) == [defaults.EMPTY]


def test_settings_round_trip_and_sanitising(tmp_path):
    path = tmp_path / "settings.json"
    s = settings.Settings(polling_hz=500, theme="light", mouse_sensitivity=2.5)
    s.save(path)
    assert settings.Settings.load(path) == s
    path.write_text(json.dumps({"polling_hz": 77, "theme": "neon", "mouse_sensitivity": 99,
                                "default_deadzone": "x", "layouts": []}), encoding="utf-8")
    loaded = settings.Settings.load(path)
    assert loaded.polling_hz == 250 and loaded.theme == "dark"
    assert loaded.mouse_sensitivity == 10.0 and loaded.default_deadzone == model.DEFAULT_DEADZONE
    assert loaded.layouts == {}
    path.write_text("garbage", encoding="utf-8")
    assert settings.Settings.load(path) == settings.Settings()
