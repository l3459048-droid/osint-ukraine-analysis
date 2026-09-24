from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DOMAINS = {
    "Drones": ["drone", "uav", "uas", "fpv", "бпла", "дрон", "безпілот"],
    "Electronic Warfare": [
        "electronic warfare", "ew", "jamming", "jammer", "radar",
        "рэб", "реб", "глуш",
    ],
    "Artillery": [
        "artillery", "howitzer", "himars", "mortar",
        "артилл", "гаубиц", "миномет", "міномет",
    ],
    "Air Defense": [
        "air defense", "sam", "patriot", "nasams",
        "пво", "зенит", "протиповітр",
    ],
    "Logistics": [
        "logistics", "supply", "transport", "maintenance",
        "логист", "снабж", "постач", "ремонт",
    ],
    "Combat Medicine": [
        "medic", "medevac", "casualty", "first aid",
        "эвакуац", "медик", "евакуац",
    ],
}

DEFAULT_CONFIG = {
    "input_dir": "inbox",
    "workspace_dir": "workspace",
    "allowed_extensions": [".pdf", ".docx", ".txt", ".md"],
    "ocr": {
        "enabled": True,
        "languages": "eng+rus+ukr",
        "min_text_chars_per_page": 80,
        "dpi": 220,
    },
    "classification": {"min_score": 1, "domains": DEFAULT_DOMAINS},
}


@dataclass(frozen=True)
class Settings:
    project_root: Path
    input_dir: Path
    workspace_dir: Path
    allowed_extensions: frozenset[str]
    ocr: dict[str, Any]
    classification: dict[str, Any]

    @property
    def db_path(self) -> Path:
        return self.workspace_dir / "osint.db"

    @property
    def text_dir(self) -> Path:
        return self.workspace_dir / "text"

    @property
    def metadata_dir(self) -> Path:
        return self.workspace_dir / "metadata"

    @property
    def logs_dir(self) -> Path:
        return self.workspace_dir / "logs"


def load_settings(config_path: str | Path = "config.json") -> Settings:
    config_path = Path(config_path).expanduser().resolve()
    root = config_path.parent
    data = json.loads(json.dumps(DEFAULT_CONFIG))
    if config_path.exists():
        user = json.loads(config_path.read_text(encoding="utf-8"))
        _deep_update(data, user)

    return Settings(
        project_root=root,
        input_dir=_resolve(root, data["input_dir"]),
        workspace_dir=_resolve(root, data["workspace_dir"]),
        allowed_extensions=frozenset(_normalize_ext(x) for x in data["allowed_extensions"]),
        ocr=data["ocr"],
        classification=data["classification"],
    )


def write_default_config(path: str | Path) -> Path:
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _resolve(root: Path, value: str) -> Path:
    p = Path(value).expanduser()
    return p.resolve() if p.is_absolute() else (root / p).resolve()


def _normalize_ext(value: str) -> str:
    value = value.lower().strip()
    return value if value.startswith(".") else "." + value


def _deep_update(base: dict[str, Any], override: dict[str, Any]) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
