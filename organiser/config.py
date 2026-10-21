"""Config loading, data paths and the module taxonomy."""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


@dataclass
class Module:
    key: str
    code: str
    name: str
    parts: list
    parts_by_term: bool = False
    aliases: list = field(default_factory=list)
    keywords: list = field(default_factory=list)
    part_keywords: list = field(default_factory=list)
    filename_prefixes: dict = field(default_factory=dict)


@dataclass
class Config:
    downloads_folder: Path
    root_folder: Path
    hotkey: str
    confidence_threshold: float
    gemini_model: str
    gemini_fallback_model: str
    port: int
    file_types: list
    part_categories: list
    module_categories: list
    modules: list
    part_extra_folders: list
    data_dir: Path

    def module(self, key):
        for m in self.modules:
            if m.key == key:
                return m
        return None

    @property
    def unsorted_dir(self):
        return self.root_folder / "_Unsorted"


def load_config(path=None):
    path = Path(path or os.environ.get("ORGANISER_CONFIG") or PROJECT_DIR / "config.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    data_dir = Path(os.environ.get("ORGANISER_DATA") or raw.get("data_dir") or PROJECT_DIR / "data")
    data_dir.mkdir(parents=True, exist_ok=True)
    modules = [Module(**m) for m in raw["modules"]]
    return Config(
        downloads_folder=Path(os.path.expandvars(raw["downloads_folder"])),
        root_folder=Path(os.path.expandvars(raw["root_folder"])),
        hotkey=raw.get("hotkey", "alt+o"),
        confidence_threshold=float(raw.get("confidence_threshold", 0.7)),
        gemini_model=raw.get("gemini_model", "gemini-2.5-flash"),
        gemini_fallback_model=raw.get("gemini_fallback_model", ""),
        port=int(raw.get("port", 47821)),
        file_types=[e.lower() for e in raw["file_types"]],
        part_categories=raw["part_categories"],
        module_categories=raw["module_categories"],
        modules=modules,
        part_extra_folders=raw.get("part_extra_folders", []),
        data_dir=data_dir,
    )


def gemini_key():
    """Env var first; fall back to the user registry value so processes started
    before the variable was set still find it."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key.strip()
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            value, _ = winreg.QueryValueEx(k, "GEMINI_API_KEY")
            return str(value).strip() or None
    except OSError:
        return None


def ensure_skeleton(cfg):
    """Module/{Lectures,Practicals,Website}/<Part> and Module/Other (additive only)."""
    cfg.unsorted_dir.mkdir(parents=True, exist_ok=True)
    for m in cfg.modules:
        mod_dir = cfg.root_folder / m.key
        (mod_dir / "Other").mkdir(parents=True, exist_ok=True)
        for top in ["Lectures", "Practicals"] + cfg.part_extra_folders:
            for part in m.parts or [""]:
                (mod_dir / top / part).mkdir(parents=True, exist_ok=True)
        for part in m.parts or [""]:
            (mod_dir / "Lectures" / part / "Readings").mkdir(parents=True, exist_ok=True)
