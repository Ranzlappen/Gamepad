"""Profile storage: one human-readable JSON file per profile in profiles/."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app import defaults, model, paths
from app.logging_setup import log


class ProfileError(Exception):
    """A user-facing problem with a profile operation."""


def slugify(name: str) -> str:
    """File-name stem for a profile name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "profile"


class ProfileStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._paths: dict[str, Path] = {}  # profile name -> file
        self.refresh()

    # --- queries -----------------------------------------------------------

    def refresh(self) -> None:
        """Re-scan the folder; unreadable files are skipped and logged."""
        self._paths.clear()
        self.directory.mkdir(parents=True, exist_ok=True)
        for path in sorted(self.directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                name = model.clean_name(data.get("name")) if isinstance(data, dict) else ""
            except (OSError, ValueError):
                log.warning("Skipping unreadable profile %s", path.name)
                continue
            if name and self.find(name) is None:
                self._paths[name] = path

    def names(self) -> list[str]:
        return sorted(self._paths, key=str.casefold)

    def find(self, name: str) -> str | None:
        """Case-insensitive lookup of an existing profile name."""
        folded = name.casefold()
        return next((n for n in self._paths if n.casefold() == folded), None)

    def unique_name(self, base: str) -> str:
        base = model.clean_name(base) or "Profile"
        if self.find(base) is None:
            return base
        for i in range(2, 1000):
            candidate = model.clean_name(f"{base} ({i})")
            if self.find(candidate) is None:
                return candidate
        raise ProfileError("Too many profiles with the same name")

    def load(self, name: str) -> dict:
        path = self._paths.get(name)
        if path is None:
            raise ProfileError(f"Profile '{name}' does not exist")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ProfileError(f"Could not read {path.name}: {exc}") from exc
        profile = model.normalize_profile(data, name)
        profile["name"] = name
        return profile

    # --- mutations ---------------------------------------------------------

    def save(self, profile: dict) -> None:
        name = profile["name"]
        path = self._paths.get(name) or self._free_path(name)
        try:
            paths.atomic_write_text(path, json.dumps(profile, indent=2, ensure_ascii=False) + "\n")
        except OSError as exc:
            raise ProfileError(f"Could not save '{name}': {exc}") from exc
        self._paths[name] = path

    def create(self, name: str, template_name: str, deadzone: float, anti_drift: float) -> dict:
        name = self._validated_new_name(name)
        profile = defaults.template(template_name, deadzone, anti_drift)
        profile["name"] = name
        self.save(profile)
        return profile

    def duplicate(self, source: str, new_name: str) -> dict:
        profile = self.load(source)
        profile["name"] = self._validated_new_name(new_name)
        self.save(profile)
        return profile

    def rename(self, old: str, new: str) -> dict:
        new = model.clean_name(new)
        if not new:
            raise ProfileError("The name cannot be empty")
        existing = self.find(new)
        if existing is not None and existing != old:
            raise ProfileError(f"A profile named '{existing}' already exists")
        profile = self.load(old)
        old_path = self._paths.pop(old)
        profile["name"] = new
        if slugify(new) == old_path.stem:  # e.g. only the letter case changed: keep the file
            self._paths[new] = old_path
        try:
            self.save(profile)
        except ProfileError:
            self._paths.pop(new, None)
            self._paths[old] = old_path
            raise
        if self._paths[new] != old_path:
            old_path.unlink(missing_ok=True)
        return profile

    def delete(self, name: str) -> None:
        if len(self._paths) <= 1:
            raise ProfileError("At least one profile must remain")
        path = self._paths.pop(name, None)
        if path is not None:
            path.unlink(missing_ok=True)

    def import_file(self, source: Path) -> dict:
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
            profile = model.normalize_profile(data, source.stem)
        except (OSError, ValueError) as exc:
            raise ProfileError(f"Could not import {source.name}: {exc}") from exc
        profile["name"] = self.unique_name(profile["name"])
        self.save(profile)
        return profile

    def export(self, name: str, target: Path) -> None:
        profile = self.load(name)
        try:
            target.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError as exc:
            raise ProfileError(f"Could not export to {target}: {exc}") from exc

    def ensure_defaults(self, first_run: bool) -> list[str]:
        """Write the template profiles on first run; always keep one profile available."""
        created = []
        if first_run:
            for name in defaults.TEMPLATE_NAMES:
                if self.find(name) is None:
                    self._write_template(name)
                    created.append(name)
        if not self._paths:
            self._write_template(defaults.EMPTY)
            created.append(defaults.EMPTY)
        return created

    # --- helpers -----------------------------------------------------------

    def _write_template(self, name: str) -> None:
        path = self.directory / defaults.TEMPLATE_FILES[name]
        if path.exists():  # occupied by a renamed profile; fall back to a fresh file name
            path = self._free_path(name)
        self._paths[name] = path
        self.save(defaults.template(name))

    def _validated_new_name(self, name: str) -> str:
        name = model.clean_name(name)
        if not name:
            raise ProfileError("The name cannot be empty")
        if self.find(name) is not None:
            raise ProfileError(f"A profile named '{name}' already exists")
        return name

    def _free_path(self, name: str) -> Path:
        """First unused file name for a new profile; never overwrites any file."""
        used = {p.resolve() for p in self._paths.values()}
        stem = slugify(name)
        candidate = self.directory / f"{stem}.json"
        i = 2
        while candidate.exists() or candidate.resolve() in used:
            candidate = self.directory / f"{stem}-{i}.json"
            i += 1
        return candidate
