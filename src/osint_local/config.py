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

PERFORMANCE_PROFILES = {
    "economy": {
        "label": "Economy",
        "description": "Lowest background and Q&A memory pressure.",
        "search": {"batch_size": 12},
        "translation": {"max_per_cycle": 1},
        "background": {"interval_seconds": 90},
        "qa": {
            "top_k": 5,
            "max_context_chars": 6500,
            "num_ctx": 4096,
            "think": False,
            "keep_alive": 0,
        },
    },
    "balanced": {
        "label": "Balanced",
        "description": "Faster follow-up questions and background processing.",
        "search": {"batch_size": 32},
        "translation": {"max_per_cycle": 2},
        "background": {"interval_seconds": 60},
        "qa": {
            "top_k": 6,
            "max_context_chars": 9000,
            "num_ctx": 4096,
            "think": False,
            "keep_alive": "5m",
        },
    },
}


DEFAULT_CONFIG = {
    "input_dir": "inbox",
    "workspace_dir": "workspace",
    "allowed_extensions": [".pdf", ".docx", ".txt", ".md"],
    "performance": {
        "profile": "economy",
    },
    "ocr": {
        "enabled": True,
        "languages": "eng+rus+ukr",
        "min_text_chars_per_page": 80,
        "dpi": 220,
    },
    "classification": {"min_score": 1, "domains": DEFAULT_DOMAINS},
    "search": {
        "chunk_chars": 1200,
        "overlap_chars": 180,
        "min_chunk_chars": 80,
        "semantic_enabled": True,
        "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "batch_size": 12,
        "auto_embed": False,
    },
    "translation": {
        "enabled": True,
        "output_dir": "auto",
        "default_source": "auto",
        "default_target": "ru",
        "max_chars_per_request": 1800,
        "auto_install_models": True,
        "passive_enabled": True,
        "max_per_cycle": 1,
    },
    "background": {
        "enabled": True,
        "initial_delay_seconds": 3,
        "interval_seconds": 90,
        "auto_index": True,
    },
    "qa": {
        "enabled": True,
        "base_url": "http://127.0.0.1:11434",
        "model": "qwen3:1.7b",
        "top_k": 5,
        "max_context_chars": 6500,
        "num_ctx": 4096,
        "think": False,
        "keep_alive": 0,
    },
    "web": {
        "host": "127.0.0.1",
        "port": 8080,
        "open_browser": True,
    },
    "ui": {
        "setup_complete": True,
    },
}


@dataclass(frozen=True)
class Settings:
    config_path: Path
    project_root: Path
    input_dir: Path
    workspace_dir: Path
    allowed_extensions: frozenset[str]
    performance: dict[str, Any]
    ocr: dict[str, Any]
    classification: dict[str, Any]
    search: dict[str, Any]
    translation: dict[str, Any]
    background: dict[str, Any]
    qa: dict[str, Any]
    web: dict[str, Any]
    ui: dict[str, Any]

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

    @property
    def translations_dir(self) -> Path:
        value = str(self.translation.get("output_dir", "auto"))
        if value.strip().casefold() == "auto":
            return (self.input_dir.parent / "translations").resolve()
        return _resolve(self.project_root, value)


def load_settings(config_path: str | Path = "config.json") -> Settings:
    config_path = Path(config_path).expanduser().resolve()
    root = config_path.parent
    data = json.loads(json.dumps(DEFAULT_CONFIG))
    if config_path.exists():
        user = json.loads(config_path.read_text(encoding="utf-8"))
        _deep_update(data, user)
        if "performance" not in user:
            _deep_update(data, performance_profile_patch("economy"))

    return Settings(
        config_path=config_path,
        project_root=root,
        input_dir=_resolve(root, data["input_dir"]),
        workspace_dir=_resolve(root, data["workspace_dir"]),
        allowed_extensions=frozenset(_normalize_ext(x) for x in data["allowed_extensions"]),
        performance=data["performance"],
        ocr=data["ocr"],
        classification=data["classification"],
        search=data["search"],
        translation=data["translation"],
        background=data["background"],
        qa=data["qa"],
        web=data["web"],
        ui=data["ui"],
    )


def write_default_config(path: str | Path) -> Path:
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        _atomic_write_json(path, DEFAULT_CONFIG)
    return path


def update_config(path: str | Path, patch: dict[str, Any]) -> Path:
    """Merge a small runtime/UI patch without discarding user configuration."""
    path = Path(path).expanduser().resolve()
    data = json.loads(json.dumps(DEFAULT_CONFIG))
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
        _deep_update(data, current)
        if "performance" not in current:
            _deep_update(data, performance_profile_patch("economy"))
    _deep_update(data, patch)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, data)
    return path



def performance_profile_patch(profile: str) -> dict[str, Any]:
    """Return the complete config patch for a supported local performance profile."""
    profile = str(profile).strip().casefold()
    if profile not in PERFORMANCE_PROFILES:
        raise ValueError(f"Unknown performance profile: {profile}")
    selected = PERFORMANCE_PROFILES[profile]
    return {
        "performance": {"profile": profile},
        "search": dict(selected["search"]),
        "translation": dict(selected["translation"]),
        "background": dict(selected["background"]),
        "qa": dict(selected["qa"]),
    }

def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


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
