"""ReComp Launcher — a launcher/library for Nintendo recompiled & decomp-ported games.

Features: box-art grid (resizable, drag-reorder), per-game details with hero banner,
themes, folder scanning, tags/favorites, playtime tracking, launch profiles,
GitHub update checking, screenshots, system tray, keyboard shortcuts.

Run with:  python recomplauncher.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from PyQt6.QtCore import (
    Qt, QSize, QThread, pyqtSignal, QObject, QAbstractListModel, QModelIndex,
    QMimeData, QByteArray, QRect, QRectF, QTimer, QPropertyAnimation, QPoint,
    QEasingCurve,
)
from PyQt6.QtGui import (
    QPixmap, QIcon, QAction, QPainter, QColor, QFont, QLinearGradient, QBrush,
    QPen, QFontMetrics, QKeySequence, QShortcut, QImage,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QFrame, QFileDialog, QDialog, QLineEdit, QFormLayout, QTextEdit,
    QMessageBox, QListWidget, QListWidgetItem, QDialogButtonBox, QToolBar,
    QStatusBar, QInputDialog, QListView, QStyledItemDelegate, QStyle,
    QAbstractItemView, QComboBox, QSlider, QTabWidget, QSystemTrayIcon, QMenu,
    QGraphicsOpacityEffect, QCheckBox, QScrollArea, QSizePolicy,
)

# ======================================================================
# Config & paths
# ======================================================================

APP_NAME = "ReComp Launcher"
SUPPORT_URL = "https://buymeacoffee.com/zikuju"
DISCORD_URL = "https://discord.gg/QppkNN4rb3"
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
ART_DIR = DATA_DIR / "art"
SHOTS_DIR = DATA_DIR / "screenshots"
RA_ICON_DIR = DATA_DIR / "ra_icons"
GAMES_FILE = DATA_DIR / "games.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
for _d in (DATA_DIR, ART_DIR, SHOTS_DIR, RA_ICON_DIR):
    _d.mkdir(exist_ok=True)

USER_AGENT = "ReCompLauncher/0.2 (https://github.com/)"

# Custom item-data roles
ROLE_GAME = Qt.ItemDataRole.UserRole + 1

BASE_CARD_W, BASE_CARD_H = 168, 250  # at scale 1.0

# Executables to ignore when scanning a folder for games.
SCAN_BLACKLIST = re.compile(
    r"(unins|setup|install|vc_?redist|vcredist|dxsetup|dxwebsetup|crashpad|"
    r"crashreport|update|helper|launcher|notification|dotnet|redist)",
    re.IGNORECASE,
)

# ======================================================================
# Known-recomp fingerprint database
# ----------------------------------------------------------------------
# Maps the executables/folder names that recompiled & decomp PC ports ship
# under to the actual game they are, so a folder scan (or the Identify
# button) can auto-fill title, platform, search name, GitHub repo and tags
# instead of the user renaming everything by hand.
#
# This list is deliberately easy to extend — a great place for community
# pull requests. `names` = exact executable filenames (case-insensitive);
# `patterns` = substrings matched against the exe stem AND its parent folder
# name (catches versioned build dirs like "Zelda64Recompiled-v1.2.0-win64").
# More specific entries must come before generic ones (coop before sm64).
# ======================================================================
KNOWN_RECOMPS: list[dict] = [
    {
        "names": ["soh.exe"], "patterns": ["shipofharkinian", "shipwright"],
        "title": "The Legend of Zelda: Ocarina of Time",
        "platform": "Ship of Harkinian", "search": "The Legend of Zelda: Ocarina of Time",
        "github_repo": "HarbourMasters/Shipwright", "tags": ["Zelda", "N64"],
    },
    {
        "names": ["2ship.exe", "2s2h.exe"], "patterns": ["2ship", "2s2h"],
        "title": "The Legend of Zelda: Majora's Mask",
        "platform": "2 Ship 2 Harkinian", "search": "The Legend of Zelda: Majora's Mask",
        "github_repo": "HarbourMasters/2ship2harkinian", "tags": ["Zelda", "N64"],
    },
    {
        "names": ["zelda64recompiled.exe", "zelda64recomp.exe", "mm.exe"],
        "patterns": ["zelda64recomp", "mmrecomp"],
        "title": "The Legend of Zelda: Majora's Mask",
        "platform": "Zelda 64: Recompiled", "search": "The Legend of Zelda: Majora's Mask",
        "github_repo": "Zelda64Recomp/Zelda64Recomp", "tags": ["Zelda", "N64", "Recompiled"],
    },
    {
        "names": ["starship.exe"], "patterns": ["starship"],
        "title": "Star Fox 64",
        "platform": "Starship", "search": "Star Fox 64",
        "github_repo": "HarbourMasters/Starship", "tags": ["Star Fox", "N64"],
    },
    {
        "names": ["perfectdark.exe", "pd.exe"], "patterns": ["perfectdark", "perfect_dark"],
        "title": "Perfect Dark",
        "platform": "Perfect Dark (decomp port)", "search": "Perfect Dark 2000",
        "github_repo": "fgsfdsfgs/perfect_dark", "tags": ["Rare", "N64"],
    },
    {
        "names": ["banjorecompiled.exe", "banjo.exe"], "patterns": ["banjorecomp", "banjo"],
        "title": "Banjo-Kazooie",
        "platform": "Banjo: Recompiled", "search": "Banjo-Kazooie",
        "github_repo": "BanjoRecomp/BanjoRecomp", "tags": ["Rare", "N64", "Recompiled"],
    },
    {
        "names": ["goemon64recompiled.exe", "goemon.exe"], "patterns": ["goemon64recomp", "goemon"],
        "title": "Mystical Ninja Starring Goemon",
        "platform": "Goemon 64: Recompiled", "search": "Mystical Ninja Starring Goemon",
        "github_repo": "klorfmorf/Goemon64Recomp", "tags": ["Goemon", "N64", "Recompiled"],
    },
    {
        # Dusk: reverse-engineered reimplementation of Twilight Princess (GameCube),
        # built on the Aurora engine. Patterns kept specific to avoid matching the
        # unrelated "DUSK" retro FPS.
        "names": ["dusk.exe"], "patterns": ["dusk-zelda", "duskzelda", "twilitrealm"],
        "title": "The Legend of Zelda: Twilight Princess",
        "platform": "Dusk (decomp reimplementation)",
        "search": "The Legend of Zelda: Twilight Princess",
        "github_repo": "JapanDoudou/dusk-zelda", "tags": ["Zelda", "GameCube", "Decomp"],
    },
    {
        # zelda3: reverse-engineered reimplementation of A Link to the Past (SNES).
        "names": ["zelda3.exe"], "patterns": ["zelda3"],
        "title": "The Legend of Zelda: A Link to the Past",
        "platform": "zelda3 (decomp reimplementation)",
        "search": "The Legend of Zelda: A Link to the Past",
        "github_repo": "snesrev/zelda3", "tags": ["Zelda", "SNES", "Decomp"],
    },
    # ----- Non-Nintendo recomps / decomp PC ports -----
    {
        "names": ["unleashedrecomp.exe"], "patterns": ["unleashedrecomp"],
        "title": "Sonic Unleashed",
        "platform": "Unleashed Recompiled", "search": "Sonic Unleashed",
        "github_repo": "hedge-dev/UnleashedRecomp", "tags": ["Sonic", "Xbox 360", "Recompiled"],
    },
    {
        "names": ["doom64ex-plus.exe", "doom64ex.exe"], "patterns": ["doom64ex", "doom64"],
        "title": "Doom 64",
        "platform": "Doom 64 EX-Plus", "search": "Doom 64",
        "github_repo": "Erick194/Doom64EX-Plus", "tags": ["Doom", "N64", "Source Port"],
    },
    {
        "names": ["rsdkv4.exe"], "patterns": ["sonic-1-2-2013", "rsdkv4"],
        "title": "Sonic the Hedgehog 1 & 2 (2013)",
        "platform": "RSDKv4 Decompilation", "search": "Sonic the Hedgehog",
        "github_repo": "RSDKModding/RSDKv4-Decompilation", "tags": ["Sonic", "Retro Engine", "Decomp"],
    },
    {
        "names": ["rsdkv3.exe"], "patterns": ["sonic-cd", "rsdkv3"],
        "title": "Sonic CD (2011)",
        "platform": "RSDKv3 Decompilation", "search": "Sonic CD",
        "github_repo": "RSDKModding/RSDKv3-Decompilation", "tags": ["Sonic", "Retro Engine", "Decomp"],
    },
    {
        # OpenGOAL runtime ships the game as gk.exe ("game kernel"); patterns keep
        # the parent-folder match specific so a stray gk.exe elsewhere won't match.
        "names": ["gk.exe"], "patterns": ["opengoal", "jak-project", "jak1", "jak2"],
        "title": "Jak and Daxter: The Precursor Legacy",
        "platform": "OpenGOAL", "search": "Jak and Daxter The Precursor Legacy",
        "github_repo": "open-goal/jak-project", "tags": ["Jak", "PS2", "Decomp"],
    },
    {
        "names": ["sm64coopdx.exe"], "patterns": ["sm64coopdx", "coopdx"],
        "title": "Super Mario 64: Co-op Deluxe",
        "platform": "sm64coopdx", "search": "Super Mario 64",
        "github_repo": "coop-deluxe/sm64coopdx", "tags": ["Mario", "N64", "Co-op"],
    },
    {
        "names": ["sm64.us.f3dex2e.exe", "sm64.exe", "sm64ex.exe", "sm64plus.exe"],
        "patterns": ["sm64ex", "sm64plus", "sm64-port", "sm64"],
        "title": "Super Mario 64",
        "platform": "sm64ex / sm64plus", "search": "Super Mario 64",
        "github_repo": "", "tags": ["Mario", "N64"],
    },
]


def identify_exe(exe_path: str) -> dict | None:
    """Return the matching KNOWN_RECOMPS entry for an executable, or None."""
    p = Path(exe_path)
    name = p.name.lower()
    stem = p.stem.lower()
    parent = p.parent.name.lower()
    for entry in KNOWN_RECOMPS:
        if name in entry["names"]:
            return entry
    for entry in KNOWN_RECOMPS:                  # second pass: fuzzy patterns
        for pat in entry.get("patterns", []):
            if pat in stem or pat in parent:
                return entry
    return None


# ----- Themes -----------------------------------------------------------
THEMES: dict[str, dict[str, str]] = {
    "Dracula": {
        "bg": "#1e1f29", "surface": "#282a36", "surface2": "#21222c",
        "text": "#f8f8f2", "subtext": "#6272a4", "accent": "#ff79c6",
        "accent_text": "#1e1f29", "play": "#50fa7b", "play_text": "#1e1f29",
        "border": "#44475a",
    },
    "Nord": {
        "bg": "#2e3440", "surface": "#3b4252", "surface2": "#292e39",
        "text": "#eceff4", "subtext": "#81a1c1", "accent": "#88c0d0",
        "accent_text": "#2e3440", "play": "#a3be8c", "play_text": "#2e3440",
        "border": "#4c566a",
    },
    "Midnight": {
        "bg": "#0f0f1a", "surface": "#1a1a2e", "surface2": "#16162a",
        "text": "#e6e6fa", "subtext": "#7c7caa", "accent": "#e94560",
        "accent_text": "#ffffff", "play": "#00d9a3", "play_text": "#0f0f1a",
        "border": "#2a2a4a",
    },
    "Light": {
        "bg": "#f4f4f6", "surface": "#ffffff", "surface2": "#eaeaee",
        "text": "#1e1e28", "subtext": "#6b6b80", "accent": "#d6336c",
        "accent_text": "#ffffff", "play": "#2f9e44", "play_text": "#ffffff",
        "border": "#d0d0d8",
    },
}


def build_stylesheet(t: dict[str, str]) -> str:
    return f"""
        QMainWindow, QWidget {{ background: {t['bg']}; color: {t['text']};
            font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 13px; }}
        QToolBar {{ background: {t['surface2']}; border: 0; padding: 6px; spacing: 6px; }}
        QToolBar QToolButton {{ color: {t['text']}; padding: 6px 12px; border-radius: 6px; }}
        QToolBar QToolButton:hover {{ background: {t['border']}; }}
        QStatusBar {{ background: {t['surface2']}; color: {t['subtext']}; }}
        #sidebar {{ background: {t['surface2']}; border: 0; }}
        #sidebar::item {{ padding: 8px 12px; border-radius: 6px; }}
        #sidebar::item:selected {{ background: {t['accent']}; color: {t['accent_text']}; }}
        #sidebar::item:hover {{ background: {t['border']}; }}
        QListView#grid {{ background: {t['bg']}; border: 0; }}
        #detailsPanel {{ background: {t['surface']}; border-left: 1px solid {t['border']}; }}
        QTabWidget::pane {{ border: 0; }}
        QTabBar::tab {{ background: transparent; color: {t['subtext']};
            padding: 6px 14px; border-bottom: 2px solid transparent; }}
        QTabBar::tab:selected {{ color: {t['text']}; border-bottom: 2px solid {t['accent']}; }}
        QPushButton {{ background: {t['border']}; color: {t['text']}; border: 0;
            border-radius: 6px; padding: 6px 12px; }}
        QPushButton:hover {{ background: {t['subtext']}; }}
        QPushButton#playButton {{ background: {t['play']}; color: {t['play_text']};
            font-size: 16px; font-weight: 700; border-radius: 8px; }}
        QPushButton#playButton:hover {{ background: {t['play']}; }}
        QPushButton#playButton:disabled {{ background: {t['border']}; color: {t['subtext']}; }}
        QPushButton#stopButton {{ background: {t['accent']}; color: {t['accent_text']};
            font-size: 16px; font-weight: 700; border-radius: 8px; }}
        QLineEdit, QTextEdit, QComboBox {{ background: {t['surface2']}; color: {t['text']};
            border: 1px solid {t['border']}; border-radius: 6px; padding: 5px; }}
        QComboBox::drop-down {{ border: 0; }}
        QComboBox QAbstractItemView {{ background: {t['surface2']}; color: {t['text']};
            selection-background-color: {t['accent']}; }}
        QScrollBar:vertical {{ background: {t['surface2']}; width: 12px; margin: 0; }}
        QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 6px; min-height: 30px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar:horizontal {{ background: {t['surface2']}; height: 12px; }}
        QScrollBar::handle:horizontal {{ background: {t['border']}; border-radius: 6px; min-width: 30px; }}
        QSlider::groove:horizontal {{ height: 4px; background: {t['border']}; border-radius: 2px; }}
        QSlider::handle:horizontal {{ background: {t['accent']}; width: 14px; margin: -6px 0;
            border-radius: 7px; }}
        QCheckBox {{ spacing: 8px; }}
    """


# ======================================================================
# Default library
# ======================================================================

DEFAULT_GAMES = [
    {"title": "The Legend of Zelda: Ocarina of Time",
     "platform": "Zelda 64: Recompiled",
     "search": "The Legend of Zelda: Ocarina of Time",
     "github_repo": "Zelda64Recomp/Zelda64Recomp",
     "tags": ["Zelda", "N64"]},
    {"title": "The Legend of Zelda: Majora's Mask",
     "platform": "Majora's Mask: Recompiled",
     "search": "The Legend of Zelda: Majora's Mask",
     "github_repo": "Zelda64Recomp/Zelda64Recomp",
     "tags": ["Zelda", "N64"]},
    {"title": "Super Mario 64",
     "platform": "sm64ex / sm64plus",
     "search": "Super Mario 64",
     "github_repo": "",
     "tags": ["Mario", "N64"]},
]


def blank_game(title: str = "") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "title": title,
        "platform": "",
        "exe_path": "",
        "args": "",
        "art_path": "",
        "banner_path": "",
        "released": "",
        "genres": "",
        "description": "",
        "search_name": title,
        "github_repo": "",
        "installed_version": "",
        "latest_version": "",
        "ra_game_id": "",
        "tags": [],
        "favorite": False,
        "playtime_seconds": 0,
        "launch_count": 0,
        "last_played": "",
        "profiles": [],          # list of {"name": str, "args": str}
        "screenshots": [],       # list of file paths
    }


# ======================================================================
# Persistence
# ======================================================================

def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)


def migrate_game(g: dict) -> dict:
    """Fill in any fields added in later versions."""
    base = blank_game()
    base.update(g)
    # legacy key rename
    if "rawg_search" in g and not g.get("search_name"):
        base["search_name"] = g["rawg_search"]
    base.pop("rawg_search", None)
    if not base.get("search_name"):
        base["search_name"] = base.get("title", "")
    if not isinstance(base.get("tags"), list):
        base["tags"] = []
    if not isinstance(base.get("profiles"), list):
        base["profiles"] = []
    if not isinstance(base.get("screenshots"), list):
        base["screenshots"] = []
    return base


def load_library() -> list[dict]:
    games = load_json(GAMES_FILE, None)
    if games is None:
        games = []
        for g in DEFAULT_GAMES:
            ng = blank_game(g["title"])
            ng["platform"] = g["platform"]
            ng["search_name"] = g["search"]
            ng["github_repo"] = g.get("github_repo", "")
            ng["tags"] = list(g.get("tags", []))
            games.append(ng)
        save_json(GAMES_FILE, games)
        return games
    return [migrate_game(g) for g in games]


def save_library(games: list[dict]) -> None:
    save_json(GAMES_FILE, games)


def load_settings() -> dict:
    s = load_json(SETTINGS_FILE, {})
    s.setdefault("sgdb_api_key", "")
    s.setdefault("theme", "Dracula")
    s.setdefault("card_scale", 100)       # percent
    s.setdefault("minimize_to_tray", False)
    s.setdefault("check_updates_on_launch", True)
    s.setdefault("ra_username", "")
    s.setdefault("ra_api_key", "")
    return s


def save_settings(s: dict) -> None:
    save_json(SETTINGS_FILE, s)


# ======================================================================
# Art helpers
# ======================================================================

_PIX_CACHE: dict[tuple, QPixmap] = {}


def make_placeholder(title: str, size: tuple[int, int]) -> QPixmap:
    w, h = size
    pm = QPixmap(w, h)
    pm.fill(QColor(40, 42, 54))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor(98, 114, 164))
    p.setBrush(QColor(68, 71, 90))
    p.drawRoundedRect(6, 6, w - 12, h - 12, 10, 10)
    p.setPen(QColor(248, 248, 242))
    f = QFont("Segoe UI", max(8, int(h / 22)))
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect().adjusted(12, 12, -12, -12),
               int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap), title)
    p.end()
    return pm


def raw_art(game: dict) -> QPixmap:
    path = game.get("art_path", "")
    if path and Path(path).exists():
        pm = QPixmap(path)
        if not pm.isNull():
            return pm
    return QPixmap()


def art_for(game: dict, w: int, h: int) -> QPixmap:
    """Cached, scaled cover for a card (KeepAspectRatio, centered on transparent)."""
    key = (game.get("art_path", ""), game.get("id"), w, h)
    if key in _PIX_CACHE:
        return _PIX_CACHE[key]
    src = raw_art(game)
    if src.isNull():
        result = make_placeholder(game.get("title", "?"), (w, h))
    else:
        scaled = src.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        result = QPixmap(w, h)
        result.fill(Qt.GlobalColor.transparent)
        p = QPainter(result)
        x = (w - scaled.width()) // 2
        y = (h - scaled.height()) // 2
        p.drawPixmap(x, y, scaled)
        p.end()
    if len(_PIX_CACHE) > 200:
        _PIX_CACHE.clear()
    _PIX_CACHE[key] = result
    return result


def asset_path(name: str) -> Path:
    """Locate a bundled asset, working both from source and frozen builds."""
    base = Path(getattr(sys, "_MEIPASS", APP_DIR))
    return base / "assets" / name


# Big Picture background: drop an image with this name into data/ to use your
# own (user override), or ship one in assets/ as the project default.
_BG_NAMES = ("bigpicture_bg.png", "bigpicture_bg.jpg",
             "bigpicture_bg.jpeg", "bigpicture_bg.webp")


def find_bp_background() -> str | None:
    for n in _BG_NAMES:
        p = DATA_DIR / n
        if p.exists():
            return str(p)
    for n in _BG_NAMES:
        p = asset_path(n)
        if p.exists():
            return str(p)
    return None


def app_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#ff79c6"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(6, 6, 52, 52, 14, 14)
    p.setPen(QColor("#1e1f29"))
    f = QFont("Segoe UI", 26); f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), int(Qt.AlignmentFlag.AlignCenter), "▶")
    p.end()
    return QIcon(pm)


def fmt_playtime(seconds: int) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    mins = seconds // 60
    if mins < 60:
        return f"{mins} min"
    hrs = mins / 60
    return f"{hrs:.1f} hrs"


# ======================================================================
# Network workers (run on QThreads)
# ======================================================================

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_REST = "https://en.wikipedia.org/api/rest_v1"
SGDB_BASE = "https://www.steamgriddb.com/api/v2"


def download_image(url: str, dest: Path, headers: dict | None = None) -> bool:
    try:
        h = {"User-Agent": USER_AGENT}
        if headers:
            h.update(headers)
        r = requests.get(url, headers=h, timeout=30)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return True
    except Exception:
        return False


def _img_ext(url: str) -> str:
    ext = "." + url.rsplit(".", 1)[-1].split("?")[0][:4].lower()
    return ext if ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp") else ".jpg"


def wiki_find_page(query: str) -> str | None:
    r = requests.get(WIKI_API, params={
        "action": "query", "list": "search", "srsearch": query,
        "srlimit": 1, "format": "json"},
        headers={"User-Agent": USER_AGENT}, timeout=15)
    r.raise_for_status()
    hits = r.json().get("query", {}).get("search", [])
    return hits[0]["title"] if hits else None


def wiki_summary(title: str) -> dict:
    slug = urllib.parse.quote(title.replace(" ", "_"), safe=":/_")
    r = requests.get(f"{WIKI_REST}/page/summary/{slug}",
                     headers={"User-Agent": USER_AGENT}, timeout=15)
    r.raise_for_status()
    return r.json()


def sgdb_find_game(api_key: str, query: str) -> int | None:
    r = requests.get(f"{SGDB_BASE}/search/autocomplete/{urllib.parse.quote(query)}",
                     headers={"Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT},
                     timeout=15)
    r.raise_for_status()
    data = r.json().get("data", [])
    return data[0]["id"] if data else None


def sgdb_pick_cover(api_key: str, game_id: int) -> str | None:
    r = requests.get(f"{SGDB_BASE}/grids/game/{game_id}",
                     headers={"Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT},
                     params={"dimensions": "600x900,342x482,660x930,512x800"}, timeout=15)
    r.raise_for_status()
    grids = r.json().get("data", [])
    portrait = [g for g in grids if g.get("height", 0) > g.get("width", 0)] or grids
    portrait.sort(key=lambda g: g.get("score", 0), reverse=True)
    return portrait[0]["url"] if portrait else None


class FetchWorker(QObject):
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, query: str, game_id: str, sgdb_key: str = ""):
        super().__init__()
        self.query, self.game_id, self.sgdb_key = query, game_id, sgdb_key.strip()

    def run(self):
        result = {"description": "", "art_path": "", "source": ""}
        used, errors = [], []
        try:
            title = wiki_find_page(self.query)
            if not title:
                errors.append(f"No Wikipedia page for '{self.query}'.")
            else:
                summary = wiki_summary(title)
                if summary.get("extract"):
                    result["description"] = summary["extract"]
                    used.append("Wikipedia")
                img = summary.get("originalimage") or summary.get("thumbnail") or {}
                url = img.get("source", "")
                if url:
                    dest = ART_DIR / f"{self.game_id}{_img_ext(url)}"
                    if download_image(url, dest):
                        result["art_path"] = str(dest)
        except Exception as e:
            errors.append(f"Wikipedia: {e}")

        if self.sgdb_key:
            try:
                gid = sgdb_find_game(self.sgdb_key, self.query)
                if gid is not None:
                    cover = sgdb_pick_cover(self.sgdb_key, gid)
                    if cover:
                        dest = ART_DIR / f"{self.game_id}_sgdb{_img_ext(cover)}"
                        if download_image(cover, dest):
                            result["art_path"] = str(dest)
                            used.append("SteamGridDB")
            except Exception as e:
                errors.append(f"SteamGridDB: {e}")

        result["source"] = " + ".join(used)
        if not used and not result["art_path"]:
            self.failed.emit("; ".join(errors) or "No data found.")
        else:
            self.finished.emit(result)


class UpdateWorker(QObject):
    """Check the latest GitHub release tag for one or more games."""
    one = pyqtSignal(str, str)        # game_id, latest_tag
    done = pyqtSignal(int)            # number checked
    failed = pyqtSignal(str)

    def __init__(self, jobs: list[tuple[str, str]]):
        super().__init__()
        self.jobs = jobs              # [(game_id, repo)]

    def run(self):
        checked = 0
        for game_id, repo in self.jobs:
            try:
                r = requests.get(f"https://api.github.com/repos/{repo}/releases/latest",
                                 headers={"User-Agent": USER_AGENT,
                                          "Accept": "application/vnd.github+json"}, timeout=15)
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                tag = r.json().get("tag_name", "")
                if tag:
                    self.one.emit(game_id, tag)
                    checked += 1
            except Exception:
                continue
        self.done.emit(checked)


def pick_release_asset(assets: list[dict], platform: str | None = None) -> dict | None:
    """From a GitHub release's asset list, pick the best download for this OS.

    Windows prefers windows/win64/x64 archives (.zip/.7z) or installers (.exe);
    Linux prefers Linux-X64 archives, then AppImage, with Flatpak as a last
    resort; macOS prefers mac/osx builds. Returns the asset dict or None.
    """
    if not assets:
        return None
    platform = platform or sys.platform
    if platform == "win32":
        want = re.compile(r"win(dows|64|32|-?x?64)?", re.IGNORECASE)
        avoid = re.compile(r"(linux|mac|osx|android|flatpak|appimage|arm)", re.IGNORECASE)
        ok_ext = (".zip", ".7z", ".exe")
    elif platform == "darwin":
        want = re.compile(r"(mac|osx|darwin)", re.IGNORECASE)
        avoid = re.compile(r"(linux|win|android|flatpak|appimage)", re.IGNORECASE)
        ok_ext = (".zip", ".tar.gz", ".dmg", ".7z")
    else:  # linux and friends
        want = re.compile(r"(linux|appimage|x86_64|flatpak)", re.IGNORECASE)
        avoid = re.compile(r"(win|mac|osx|android|arm64|aarch64)", re.IGNORECASE)
        ok_ext = (".zip", ".tar.gz", ".appimage", ".7z")

    def ext_ok(name: str) -> bool:
        return name.lower().endswith(ok_ext)

    candidates = [a for a in assets
                  if want.search(a.get("name", "")) and ext_ok(a.get("name", ""))
                  and not avoid.search(a.get("name", ""))]
    if not candidates:
        # generically-named builds: any acceptable archive not for another OS
        candidates = [a for a in assets if ext_ok(a.get("name", ""))
                      and not avoid.search(a.get("name", ""))]
    if not candidates:
        return None

    def score(a):
        n = a.get("name", "").lower()
        s = 0
        if "x64" in n or "win64" in n or "x86_64" in n:
            s += 3
        if n.endswith(".appimage"):
            s += 2
        if n.endswith(".zip"):
            s += 2
        elif n.endswith(".7z"):
            s += 1
        if "flatpak" in n:
            s -= 2
        return s

    candidates.sort(key=score, reverse=True)
    return candidates[0]


def reveal_in_file_manager(path: Path):
    """Open a folder in the OS file manager (best effort, cross-platform)."""
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


class DownloadWorker(QObject):
    """Download the latest Windows release asset for a repo to a folder."""
    progress = pyqtSignal(int)            # percent (0-100, -1 if unknown)
    finished = pyqtSignal(str, str)       # saved_path, tag
    failed = pyqtSignal(str)
    no_asset = pyqtSignal(str, str)       # releases_url, tag  (fallback to browser)

    def __init__(self, repo: str, dest_dir: str):
        super().__init__()
        self.repo = repo
        self.dest_dir = dest_dir

    def run(self):
        try:
            r = requests.get(f"https://api.github.com/repos/{self.repo}/releases/latest",
                             headers={"User-Agent": USER_AGENT,
                                      "Accept": "application/vnd.github+json"}, timeout=20)
            r.raise_for_status()
            data = r.json()
            tag = data.get("tag_name", "")
            asset = pick_release_asset(data.get("assets", []))
            if not asset:
                self.no_asset.emit(data.get("html_url",
                                   f"https://github.com/{self.repo}/releases"), tag)
                return
            url = asset["browser_download_url"]
            dest = Path(self.dest_dir) / asset["name"]
            with requests.get(url, headers={"User-Agent": USER_AGENT},
                              stream=True, timeout=60) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                got = 0
                with dest.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            got += len(chunk)
                            if total:
                                self.progress.emit(int(got * 100 / total))
                            else:
                                self.progress.emit(-1)
            self.finished.emit(str(dest), tag)
        except Exception as e:
            self.failed.emit(str(e))


# ======================================================================
# RetroAchievements (Web API viewer)
# ----------------------------------------------------------------------
# No recomp can *earn* RA achievements today (RA hooks emulator memory and
# treats native ports as standalone games needing their own integration),
# but the public Web API lets us show each game's official achievement set
# and the user's unlocks earned via emulators. Username + Web API key go
# in Settings; game IDs are auto-matched by title where possible.
# ======================================================================

RA_API = "https://retroachievements.org/API"
RA_MEDIA = "https://media.retroachievements.org"

# tag hint -> RetroAchievements console id, for auto-matching game IDs
_RA_CONSOLES = {"N64": 2, "SNES": 3, "GameCube": 16, "PS2": 21}


def _ra_norm_title(s: str) -> str:
    """Normalize a title for matching. RA uses 'Legend of Zelda, The: ...'
    style, so ', the' and a leading 'the' both collapse away."""
    s = s.lower().replace(", the", " ")
    s = re.sub(r"[^a-z0-9]+", "", s)
    return re.sub(r"^the", "", s)


class RAWorker(QObject):
    """Fetch a game's RetroAchievements set + the user's progress."""
    finished = pyqtSignal(str, dict)     # library game id, payload
    failed = pyqtSignal(str, str)        # library game id, message

    def __init__(self, lib_id: str, title: str, tags: list[str],
                 ra_game_id: str, username: str, api_key: str):
        super().__init__()
        self.lib_id = lib_id
        self.title = title
        self.tags = tags
        self.ra_game_id = str(ra_game_id or "").strip()
        self.username = username
        self.api_key = api_key

    def _lookup_id(self) -> str:
        console = next((cid for tag, cid in _RA_CONSOLES.items()
                        if tag in self.tags), None)
        if console is None:
            return ""
        r = requests.get(f"{RA_API}/API_GetGameList.php",
                         params={"y": self.api_key, "i": console, "f": 1},
                         headers={"User-Agent": USER_AGENT}, timeout=30)
        r.raise_for_status()
        want = _ra_norm_title(self.title)
        for entry in r.json():
            if _ra_norm_title(str(entry.get("Title", ""))) == want:
                return str(entry.get("ID", ""))
        return ""

    def run(self):
        try:
            rid = self.ra_game_id or self._lookup_id()
            if not rid:
                self.failed.emit(self.lib_id,
                                 "No RetroAchievements match found — set the "
                                 "game's RA ID in Edit (use Find…).")
                return
            r = requests.get(f"{RA_API}/API_GetGameInfoAndUserProgress.php",
                             params={"y": self.api_key, "u": self.username,
                                     "g": rid, "a": 1},
                             headers={"User-Agent": USER_AGENT}, timeout=30)
            r.raise_for_status()
            data = r.json()
            achs = data.get("Achievements") or {}
            out = []
            for a in achs.values():
                badge = str(a.get("BadgeName", ""))
                earned = bool(a.get("DateEarned") or a.get("DateEarnedHardcore"))
                icon = ""
                if badge:
                    suffix = "" if earned else "_lock"
                    dest = RA_ICON_DIR / f"{badge}{suffix}.png"
                    if not dest.exists():
                        download_image(f"{RA_MEDIA}/Badge/{badge}{suffix}.png", dest)
                    if dest.exists():
                        icon = str(dest)
                out.append({
                    "title": a.get("Title", ""),
                    "desc": a.get("Description", ""),
                    "points": a.get("Points", 0),
                    "earned": earned,
                    "order": a.get("DisplayOrder") or 0,
                    "icon": icon,
                })
            out.sort(key=lambda x: (x["order"], str(x["title"])))
            self.finished.emit(self.lib_id, {
                "ra_id": rid,
                "game_title": data.get("Title", "") or self.title,
                "total": int(data.get("NumAchievements") or len(out)),
                "earned": int(data.get("NumAwardedToUser") or 0),
                "completion": str(data.get("UserCompletion", "") or "").strip(),
                "achievements": out,
            })
        except Exception as e:
            self.failed.emit(self.lib_id, str(e))


# ======================================================================
# XInput controller support (Windows, zero extra dependencies)
# ======================================================================

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _XINPUT_GAMEPAD(ctypes.Structure):
        _fields_ = [("wButtons", wintypes.WORD),
                    ("bLeftTrigger", ctypes.c_ubyte),
                    ("bRightTrigger", ctypes.c_ubyte),
                    ("sThumbLX", ctypes.c_short),
                    ("sThumbLY", ctypes.c_short),
                    ("sThumbRX", ctypes.c_short),
                    ("sThumbRY", ctypes.c_short)]

    class _XINPUT_STATE(ctypes.Structure):
        _fields_ = [("dwPacketNumber", wintypes.DWORD),
                    ("Gamepad", _XINPUT_GAMEPAD)]

    def _load_xinput():
        for name in ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"):
            try:
                return ctypes.WinDLL(name)
            except OSError:
                continue
        return None
else:  # non-Windows: poller simply reports unavailable
    def _load_xinput():
        return None

# XInput wButtons bit flags -> logical names
_XI_BUTTONS = {
    0x0001: "up", 0x0002: "down", 0x0004: "left", 0x0008: "right",
    0x0010: "start", 0x0020: "back",
    0x0100: "lb", 0x0200: "rb",
    0x1000: "a", 0x2000: "b", 0x4000: "x", 0x8000: "y",
}


# ----- PlayStation controllers (DualSense / DualShock 4) -----------------
# Windows exposes Sony pads as raw HID devices, not XInput, so we read their
# input reports directly and translate them into the same XInput-style button
# mask ControllerPoller understands. Face buttons map by position:
# Cross->A, Circle->B, Square->X, Triangle->Y; Options->start, Create->back.

_SONY_PIDS = (0x0CE6, 0x0DF2, 0x05C4, 0x09CC, 0x0BA0)  # DualSense, Edge, DS4 v1/v2, dongle

# d-pad hat nibble (0=N .. 7=NW, 8+=released) -> direction bits
_HAT_TO_MASK = [0x0001, 0x0009, 0x0008, 0x000A, 0x0002, 0x0006, 0x0004, 0x0005,
                0, 0, 0, 0, 0, 0, 0, 0]


def _sony_pid_from_path(path: str) -> int | None:
    """Extract a known Sony product id from a HID device path, else None.

    USB paths look like  hid#vid_054c&pid_0ce6#...  while Bluetooth paths
    look like  hid#{...}_vid&0002054c_pid&0ce6#...  — match both.
    """
    lp = path.lower()
    if not re.search(r"vid(?:_|&[0-9a-f]{4})054c", lp):
        return None
    m = re.search(r"pid[_&]([0-9a-f]{4})", lp)
    if m:
        pid = int(m.group(1), 16)
        if pid in _SONY_PIDS:
            return pid
    return None


def _parse_sony_report(d: bytes, dualsense: bool, bluetooth: bool = False):
    """Translate a Sony HID input report to (buttons_mask, lx, ly), or None.

    Layouts: DualSense USB report 0x01 (buttons at 8/9), DualSense Bluetooth
    enhanced 0x31 (offset +1), DS4 BT enhanced 0x11 (offset +2), and the
    shared DS4-style compatibility report 0x01 (buttons at 5/6).

    Transport matters: over Bluetooth the DualSense's compat report is ALSO
    id 0x01 but padded to 78 bytes, so report length alone cannot pick the
    layout — the caller tells us which transport the device is on.
    """
    n = len(d)
    if n < 10:
        return None
    rid = d[0]
    if dualsense and rid == 0x01 and not bluetooth and n >= 30:  # DualSense USB
        lx, ly, b0, b1 = d[1], d[2], d[8], d[9]
    elif dualsense and rid == 0x31 and n >= 12:      # DualSense BT (enhanced)
        lx, ly, b0, b1 = d[2], d[3], d[9], d[10]
    elif not dualsense and rid == 0x11 and n >= 10:  # DS4 BT (enhanced)
        lx, ly, b0, b1 = d[3], d[4], d[7], d[8]
    elif rid == 0x01:            # DS4 USB / any BT-compat report (DS4 layout)
        lx, ly, b0, b1 = d[1], d[2], d[5], d[6]
    else:
        return None
    buttons = _HAT_TO_MASK[b0 & 0x0F]
    if b0 & 0x10:
        buttons |= 0x4000   # Square   -> X
    if b0 & 0x20:
        buttons |= 0x1000   # Cross    -> A
    if b0 & 0x40:
        buttons |= 0x2000   # Circle   -> B
    if b0 & 0x80:
        buttons |= 0x8000   # Triangle -> Y
    if b1 & 0x01:
        buttons |= 0x0100   # L1 -> LB
    if b1 & 0x02:
        buttons |= 0x0200   # R1 -> RB
    if b1 & 0x10:
        buttons |= 0x0020   # Create/Share -> back
    if b1 & 0x20:
        buttons |= 0x0010   # Options -> start
    # HID sticks are 0..255 with Y-down; rescale to XInput's signed Y-up range
    return buttons, (lx - 128) * 257, (128 - ly) * 257


if sys.platform == "win32":
    SETUPAPI = ctypes.WinDLL("setupapi")
    HIDDLL = ctypes.WinDLL("hid")
    KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class _SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", _GUID),
                    ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_void_p)]

    SETUPAPI.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    SETUPAPI.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                              ctypes.c_void_p, wintypes.DWORD]
    SETUPAPI.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
    SETUPAPI.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                     ctypes.c_void_p, wintypes.DWORD,
                                                     ctypes.c_void_p]
    SETUPAPI.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
    SETUPAPI.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                          ctypes.c_void_p, wintypes.DWORD,
                                                          ctypes.c_void_p, ctypes.c_void_p]
    SETUPAPI.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
    KERNEL32.CreateFileW.restype = ctypes.c_void_p
    KERNEL32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                     ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                     ctypes.c_void_p]
    KERNEL32.ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                                  ctypes.c_void_p, ctypes.c_void_p]
    KERNEL32.CloseHandle.argtypes = [ctypes.c_void_p]

    _INVALID_HANDLE = ctypes.c_void_p(-1).value

    class _SonyHidReader(threading.Thread):
        """Blocking-read loop for PlayStation pads; keeps `state` up to date.

        `state` is the latest (buttons_mask, lx, ly) or None while nothing is
        connected. Runs as a daemon thread; reconnects automatically every
        couple of seconds when a pad appears/disappears.
        """

        def __init__(self):
            super().__init__(daemon=True)
            self.state = None
            self.opened_path: str | None = None   # diagnostic: device in use
            self._stop = False

        def stop(self):
            self._stop = True

        @staticmethod
        def _find() -> str | None:
            try:
                guid = _GUID()
                HIDDLL.HidD_GetHidGuid(ctypes.byref(guid))
                h = SETUPAPI.SetupDiGetClassDevsW(ctypes.byref(guid), None, None,
                                                  0x12)  # PRESENT | DEVICEINTERFACE
                if not h or h == _INVALID_HANDLE:
                    return None
                try:
                    ifd = _SP_DEVICE_INTERFACE_DATA()
                    ifd.cbSize = ctypes.sizeof(ifd)
                    i = 0
                    while SETUPAPI.SetupDiEnumDeviceInterfaces(
                            h, None, ctypes.byref(guid), i, ctypes.byref(ifd)):
                        i += 1
                        need = wintypes.DWORD(0)
                        SETUPAPI.SetupDiGetDeviceInterfaceDetailW(
                            h, ctypes.byref(ifd), None, 0, ctypes.byref(need), None)
                        buf = ctypes.create_string_buffer(need.value + 8)
                        ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = (
                            8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6)
                        if SETUPAPI.SetupDiGetDeviceInterfaceDetailW(
                                h, ctypes.byref(ifd), buf, need.value + 8, None, None):
                            path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
                            if _sony_pid_from_path(path) is not None:
                                return path
                finally:
                    SETUPAPI.SetupDiDestroyDeviceInfoList(h)
            except Exception:
                pass
            return None

        def run(self):
            while not self._stop:
                path = self._find()
                if not path:
                    self.state = None
                    time.sleep(2.0)
                    continue
                pid = _sony_pid_from_path(path)
                dualsense = pid in (0x0CE6, 0x0DF2)
                lp = path.lower()
                bluetooth = "{00001124" in lp or "vid&" in lp
                handle = KERNEL32.CreateFileW(path, 0xC0000000, 3, None, 3, 0, None)
                if not handle or handle == _INVALID_HANDLE:
                    handle = KERNEL32.CreateFileW(path, 0x80000000, 3, None, 3, 0, None)
                if not handle or handle == _INVALID_HANDLE:
                    self.state = None
                    time.sleep(2.0)
                    continue
                self.opened_path = path
                buf = ctypes.create_string_buffer(1024)
                got = wintypes.DWORD(0)
                while not self._stop:
                    if (not KERNEL32.ReadFile(handle, buf, 1024, ctypes.byref(got), None)
                            or got.value == 0):
                        break
                    parsed = _parse_sony_report(buf.raw[:got.value], dualsense, bluetooth)
                    if parsed:
                        self.state = parsed
                KERNEL32.CloseHandle(handle)
                self.opened_path = None
                self.state = None
else:
    _SonyHidReader = None


class ControllerPoller(QObject):
    """Polls XInput (Xbox) and PlayStation (DualSense / DualShock 4) gamepads.

    Emits `pressed` with one of: up/down/left/right/a/b/x/y/start/back/lb/rb.
    D-pad and left stick are merged into one direction that auto-repeats
    while held (350 ms delay, then every 130 ms) so browsing feels natural.
    XInput pads take priority, so mappers like DS4Windows/Steam Input that
    present a Sony pad as XInput never cause double input.
    """
    pressed = pyqtSignal(str)
    connected = pyqtSignal()
    disconnected = pyqtSignal()

    DEADZONE = 16000
    REPEAT_DELAY = 0.35
    REPEAT_RATE = 0.13

    def __init__(self, parent=None):
        super().__init__(parent)
        self.xi = _load_xinput()
        self.sony = None
        if _SonyHidReader is not None:
            try:
                self.sony = _SonyHidReader()
                self.sony.start()
            except Exception:
                self.sony = None
        self.available = self.xi is not None or self.sony is not None
        self.pad: int | None = None
        self._src: str | None = None      # 'xinput' | 'sony' | None
        self._prev_buttons = 0
        self._dir: str | None = None
        self._dir_since = 0.0
        self._dir_last = 0.0
        if self.available:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._poll)
            self._timer.start(33)

    def _read(self):
        """Return (buttons, lx, ly) from whichever pad is talking, else None."""
        if self.xi:
            state = _XINPUT_STATE()
            pads = [self.pad] if self.pad is not None else range(4)
            for i in pads:
                if self.xi.XInputGetState(i, ctypes.byref(state)) == 0:
                    self.pad = i
                    self._set_src("xinput")
                    gp = state.Gamepad
                    return gp.wButtons, gp.sThumbLX, gp.sThumbLY
            self.pad = None
        s = self.sony.state if self.sony else None
        if s is not None:
            self._set_src("sony")
            return s
        self._set_src(None)
        return None

    def _set_src(self, src: str | None):
        if src != self._src:
            old, self._src = self._src, src
            if src is not None and old is None:
                self.connected.emit()
            elif src is None and old is not None:
                self.disconnected.emit()

    def _step(self, buttons: int, lx: int, ly: int, now: float) -> list[str]:
        """Pure input-translation step (separated out for testability)."""
        out = []
        newly = buttons & ~self._prev_buttons
        self._prev_buttons = buttons
        for bit, name in _XI_BUTTONS.items():
            if newly & bit and name not in ("up", "down", "left", "right"):
                out.append(name)
        # merge d-pad + left stick into one auto-repeating direction
        d = None
        if buttons & 0x0001:
            d = "up"
        elif buttons & 0x0002:
            d = "down"
        elif buttons & 0x0004:
            d = "left"
        elif buttons & 0x0008:
            d = "right"
        elif abs(lx) > self.DEADZONE or abs(ly) > self.DEADZONE:
            if abs(lx) >= abs(ly):
                d = "right" if lx > 0 else "left"
            else:
                d = "up" if ly > 0 else "down"
        if d != self._dir:
            self._dir = d
            self._dir_since = now
            self._dir_last = now
            if d:
                out.append(d)
        elif d and (now - self._dir_since >= self.REPEAT_DELAY
                    and now - self._dir_last >= self.REPEAT_RATE):
            self._dir_last = now
            out.append(d)
        return out

    def _poll(self):
        r = self._read()
        if r is None:
            self._prev_buttons = 0
            self._dir = None
            return
        buttons, lx, ly = r
        for name in self._step(buttons, lx, ly, time.monotonic()):
            self.pressed.emit(name)


# ======================================================================
# Grid model + delegate
# ======================================================================

class GameModel(QAbstractListModel):
    """Holds the full library plus the currently-visible (filtered) subset.

    Drag-drop reordering operates on the visible list and is only enabled when
    no filter is active (so the persisted order is unambiguous).
    """
    reordered = pyqtSignal(str)       # game id that moved (to reselect)

    MIME = "application/x-recomp-rows"

    def __init__(self, games: list[dict]):
        super().__init__()
        self._all = games
        self._visible = list(games)
        self._search = ""
        self._tag = None
        self._fav_only = False
        self.on_change = None         # callable() -> persist

    # ----- filter -----
    @property
    def is_filtered(self) -> bool:
        return bool(self._search) or self._tag is not None or self._fav_only

    def set_filter(self, search: str = None, tag=..., fav_only: bool = None):
        if search is not None:
            self._search = search.strip().lower()
        if tag is not ...:
            self._tag = tag
        if fav_only is not None:
            self._fav_only = fav_only
        self.beginResetModel()
        self._recompute()
        self.endResetModel()

    def _recompute(self):
        out = []
        for g in self._all:
            if self._fav_only and not g.get("favorite"):
                continue
            if self._tag is not None and self._tag not in g.get("tags", []):
                continue
            if self._search and self._search not in g.get("title", "").lower():
                continue
            out.append(g)
        self._visible = out

    # ----- data -----
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._visible)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        g = self._visible[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return g.get("title", "")
        if role == ROLE_GAME:
            return g
        return None

    def game_at(self, row: int) -> dict | None:
        return self._visible[row] if 0 <= row < len(self._visible) else None

    def row_of_id(self, gid: str) -> int:
        for i, g in enumerate(self._visible):
            if g["id"] == gid:
                return i
        return -1

    def all_games(self) -> list[dict]:
        return self._all

    def refresh_all(self):
        """Re-apply current filter and repaint (after external edits)."""
        self.set_filter()

    def add_game(self, g: dict):
        self._all.append(g)
        self.set_filter()
        if self.on_change:
            self.on_change()

    def remove_id(self, gid: str):
        self._all = [g for g in self._all if g["id"] != gid]
        self.set_filter()
        if self.on_change:
            self.on_change()

    # ----- drag & drop reordering -----
    def flags(self, index):
        base = super().flags(index)
        if index.isValid():
            return base | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled
        return base | Qt.ItemFlag.ItemIsDropEnabled

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction

    def mimeTypes(self):
        return [self.MIME]

    def mimeData(self, indexes):
        rows = sorted({i.row() for i in indexes if i.isValid()})
        md = QMimeData()
        md.setData(self.MIME, QByteArray(",".join(str(r) for r in rows).encode()))
        return md

    def canDropMimeData(self, data, action, row, column, parent):
        return data.hasFormat(self.MIME) and not self.is_filtered

    def dropMimeData(self, data, action, row, column, parent):
        if not data.hasFormat(self.MIME) or self.is_filtered:
            return False
        rows = [int(x) for x in bytes(data.data(self.MIME)).decode().split(",") if x != ""]
        if not rows:
            return False
        if row < 0:
            row = parent.row() if parent.isValid() else len(self._all)
        moving = [self._all[r] for r in rows]
        moved_id = moving[0]["id"]
        for r in sorted(rows, reverse=True):
            del self._all[r]
        insert_at = row - sum(1 for r in rows if r < row)
        insert_at = max(0, min(insert_at, len(self._all)))
        for i, g in enumerate(moving):
            self._all.insert(insert_at + i, g)
        self.beginResetModel()
        self._recompute()
        self.endResetModel()
        if self.on_change:
            self.on_change()
        self.reordered.emit(moved_id)
        return False   # we handled the move; suppress default row removal


class GameDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scale = 1.0
        self.now_playing: set[str] = set()
        self.theme = THEMES["Dracula"]

    def card_size(self) -> tuple[int, int]:
        return int(BASE_CARD_W * self.scale), int(BASE_CARD_H * self.scale)

    def sizeHint(self, option, index):
        w, h = self.card_size()
        return QSize(w + 16, h + 16)

    def paint(self, painter, option, index):
        g = index.data(ROLE_GAME)
        if not g:
            return
        t = self.theme
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(8, 8, -8, -8)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # card background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t["surface"]))
        painter.drawRoundedRect(QRectF(rect), 10, 10)

        cw, ch = self.card_size()
        title_h = int(34 * self.scale)
        art_rect = QRect(rect.left() + 6, rect.top() + 6,
                         rect.width() - 12, rect.height() - title_h - 12)
        pm = art_for(g, art_rect.width(), art_rect.height())
        painter.drawPixmap(art_rect.topLeft(), pm)

        # title
        painter.setPen(QColor(t["text"]))
        f = QFont("Segoe UI", max(8, int(9 * self.scale))); f.setBold(True)
        painter.setFont(f)
        title_rect = QRect(rect.left() + 6, rect.bottom() - title_h,
                           rect.width() - 12, title_h)
        painter.drawText(title_rect, int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
                         | int(Qt.TextFlag.TextWordWrap), g.get("title", ""))

        # favorite star
        if g.get("favorite"):
            painter.setPen(QColor("#ffd43b"))
            sf = QFont("Segoe UI", int(13 * self.scale))
            painter.setFont(sf)
            painter.drawText(art_rect.adjusted(0, 2, -4, 0),
                             int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight), "★")

        # now-playing badge
        if g["id"] in self.now_playing:
            badge = QRect(art_rect.left() + 4, art_rect.top() + 4, int(74 * self.scale), int(20 * self.scale))
            painter.setBrush(QColor(t["play"]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(badge, 6, 6)
            painter.setPen(QColor(t["play_text"]))
            bf = QFont("Segoe UI", int(7 * self.scale)); bf.setBold(True)
            painter.setFont(bf)
            painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), "● PLAYING")

        # playtime badge (bottom-left of art) if any playtime
        elif g.get("playtime_seconds", 0) >= 60:
            txt = fmt_playtime(g["playtime_seconds"])
            bf = QFont("Segoe UI", int(7 * self.scale)); bf.setBold(True)
            fm2 = QFontMetrics(bf)
            bw = fm2.horizontalAdvance(txt) + 12
            badge = QRect(art_rect.left() + 4, art_rect.bottom() - int(20 * self.scale) - 2,
                          bw, int(18 * self.scale))
            painter.setBrush(QColor(0, 0, 0, 150))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(badge, 6, 6)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(bf)
            painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), txt)

        # update-available badge (top-right of art)
        inst = g.get("installed_version", "")
        latest = g.get("latest_version", "")
        if inst and latest and inst != latest:
            bf = QFont("Segoe UI", int(7 * self.scale)); bf.setBold(True)
            fm3 = QFontMetrics(bf)
            txt = "⬆ UPDATE"
            bw = fm3.horizontalAdvance(txt) + 12
            badge = QRect(art_rect.right() - bw - 4, art_rect.top() + 4,
                          bw, int(18 * self.scale))
            painter.setBrush(QColor(t["accent"]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(badge, 6, 6)
            painter.setPen(QColor(t["accent_text"]))
            painter.setFont(bf)
            painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), txt)

        # border (selected / hover)
        if selected:
            painter.setPen(QPen(QColor(t["accent"]), 2))
        elif hover:
            painter.setPen(QPen(QColor(t["subtext"]), 2))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        if selected or hover:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(rect.adjusted(1, 1, -1, -1)), 10, 10)
        painter.restore()


class GameGrid(QListView):
    """Icon-mode list view with reordering + Enter-to-activate."""
    activateGame = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("grid")
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setMovement(QListView.Movement.Static)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setSpacing(6)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.activateGame.emit()
            return
        super().keyPressEvent(e)


# ======================================================================
# Custom widgets
# ======================================================================

class HeroBanner(QWidget):
    """Wide banner painting cover-cropped art behind a gradient + title."""
    def __init__(self):
        super().__init__()
        self.setFixedHeight(190)
        self._pm = QPixmap()
        self._title = ""
        self._sub = ""
        self.theme = THEMES["Dracula"]

    def set_game(self, game: dict | None):
        if not game:
            self._pm = QPixmap(); self._title = ""; self._sub = ""
        else:
            banner = game.get("banner_path", "")
            src = QPixmap(banner) if banner and Path(banner).exists() else raw_art(game)
            self._pm = src
            self._title = game.get("title", "")
            bits = [b for b in (game.get("platform", ""),
                                str(game.get("released", ""))[:4],
                                game.get("genres", "")) if b]
            self._sub = "   •   ".join(bits)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.theme
        r = self.rect()
        p.fillRect(r, QColor(t["surface2"]))
        if not self._pm.isNull():
            scaled = self._pm.scaled(r.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                     Qt.TransformationMode.SmoothTransformation)
            x = (r.width() - scaled.width()) // 2
            y = (r.height() - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
        # gradient overlay (transparent top -> opaque bottom)
        grad = QLinearGradient(0, 0, 0, r.height())
        c = QColor(t["surface"])
        c0 = QColor(c); c0.setAlpha(40)
        c1 = QColor(c); c1.setAlpha(140)
        c2 = QColor(c); c2.setAlpha(245)
        grad.setColorAt(0.0, c0); grad.setColorAt(0.55, c1); grad.setColorAt(1.0, c2)
        p.fillRect(r, QBrush(grad))
        # title
        p.setPen(QColor(t["text"]))
        tf = QFont("Segoe UI", 17); tf.setBold(True)
        p.setFont(tf)
        p.drawText(r.adjusted(16, 0, -16, -34),
                   int(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft)
                   | int(Qt.TextFlag.TextWordWrap), self._title or "—")
        p.setPen(QColor(t["accent"]))
        sf = QFont("Segoe UI", 10)
        p.setFont(sf)
        p.drawText(r.adjusted(16, 0, -16, -12),
                   int(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft), self._sub)
        p.end()


class Toast(QFrame):
    """Transient bottom-right notification with slide+fade."""
    def __init__(self, parent, text: str, accent: str):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setStyleSheet(
            f"#toast {{ background: {accent}; border-radius: 10px; }}"
            f"QLabel {{ color: #1e1f29; font-weight: 600; background: transparent; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        self.adjustSize()
        self.setFixedWidth(300)
        self.adjustSize()

    def show_at(self, parent_rect: QRect):
        margin = 24
        end_x = parent_rect.width() - self.width() - margin
        end_y = parent_rect.height() - self.height() - margin
        self.move(end_x, end_y + 40)
        self.show()
        self.raise_()
        self._anim_in = QPropertyAnimation(self, b"pos")
        self._anim_in.setDuration(280)
        self._anim_in.setStartValue(QPoint(end_x, end_y + 40))
        self._anim_in.setEndValue(QPoint(end_x, end_y))
        self._anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_in.start()
        QTimer.singleShot(3200, self._fade_out)

    def _fade_out(self):
        eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        self._anim_out = QPropertyAnimation(eff, b"opacity")
        self._anim_out.setDuration(400)
        self._anim_out.setStartValue(1.0)
        self._anim_out.setEndValue(0.0)
        self._anim_out.finished.connect(self.deleteLater)
        self._anim_out.start()


class ScreenshotStrip(QScrollArea):
    """Horizontal strip of screenshot thumbnails; click opens full-size."""
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFixedHeight(110)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._inner = QWidget()
        self._lay = QHBoxLayout(self._inner)
        self._lay.setContentsMargins(4, 4, 4, 4)
        self._lay.setSpacing(8)
        self._lay.addStretch()
        self.setWidget(self._inner)
        self._empty = QLabel("No screenshots yet. Use “Add Screenshot…”.")

    def set_shots(self, paths: list[str]):
        while self._lay.count():
            it = self._lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        valid = [p for p in paths if Path(p).exists()]
        if not valid:
            lbl = QLabel("No screenshots yet — use “Add Screenshot…”.")
            lbl.setStyleSheet("color: #6272a4;")
            self._lay.addWidget(lbl)
            self._lay.addStretch()
            return
        for p in valid:
            thumb = QLabel()
            pm = QPixmap(p).scaled(160, 90, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            thumb.setPixmap(pm)
            thumb.setCursor(Qt.CursorShape.PointingHandCursor)
            thumb.mousePressEvent = (lambda e, path=p: self._open(path))
            self._lay.addWidget(thumb)
        self._lay.addStretch()

    def _open(self, path: str):
        dlg = QDialog(self)
        dlg.setWindowTitle("Screenshot")
        v = QVBoxLayout(dlg)
        lbl = QLabel()
        pm = QPixmap(path).scaled(1100, 700, Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
        lbl.setPixmap(pm)
        v.addWidget(lbl)
        dlg.exec()


# ======================================================================
# Dialogs
# ======================================================================

class EditGameDialog(QDialog):
    def __init__(self, parent, game: dict):
        super().__init__(parent)
        self.setWindowTitle("Edit Game")
        self.game = dict(game)
        self.setMinimumWidth(560)

        self.title_edit = QLineEdit(game.get("title", ""))
        self.platform_edit = QLineEdit(game.get("platform", ""))

        self.exe_edit = QLineEdit(game.get("exe_path", ""))
        exe_btn = QPushButton("Browse…"); exe_btn.clicked.connect(self._browse_exe)
        exe_wrap = self._row(self.exe_edit, exe_btn)

        self.args_edit = QLineEdit(game.get("args", ""))
        self.released_edit = QLineEdit(str(game.get("released", "")))
        self.genres_edit = QLineEdit(game.get("genres", ""))
        self.tags_edit = QLineEdit(", ".join(game.get("tags", [])))
        self.repo_edit = QLineEdit(game.get("github_repo", ""))
        self.repo_edit.setPlaceholderText("owner/repo  (for update checks)")
        self.version_edit = QLineEdit(game.get("installed_version", ""))

        self.ra_edit = QLineEdit(str(game.get("ra_game_id", "")))
        self.ra_edit.setPlaceholderText("numeric ID — auto-matched when possible")
        ra_find = QPushButton("Find…")
        ra_find.clicked.connect(self._find_ra)

        self.art_edit = QLineEdit(game.get("art_path", ""))
        art_btn = QPushButton("Browse…"); art_btn.clicked.connect(self._browse_art)
        art_url = QPushButton("URL…"); art_url.clicked.connect(self._art_from_url)
        art_wrap = self._row(self.art_edit, art_btn, art_url)

        self.search_edit = QLineEdit(game.get("search_name") or game.get("title", ""))

        self.profiles_edit = QTextEdit()
        self.profiles_edit.setPlaceholderText("One per line:  Name | --some-flag --other")
        self.profiles_edit.setText(
            "\n".join(f"{p.get('name','')} | {p.get('args','')}" for p in game.get("profiles", [])))
        self.profiles_edit.setFixedHeight(70)

        self.desc_edit = QTextEdit(game.get("description", ""))
        self.desc_edit.setMinimumHeight(110)

        form = QFormLayout()
        form.addRow("Title:", self.title_edit)
        form.addRow("Platform / Port:", self.platform_edit)
        form.addRow("Executable:", exe_wrap)
        form.addRow("Arguments:", self.args_edit)
        form.addRow("Launch profiles:", self.profiles_edit)
        form.addRow("Release year:", self.released_edit)
        form.addRow("Genres:", self.genres_edit)
        form.addRow("Tags (comma sep):", self.tags_edit)
        form.addRow("GitHub repo:", self.repo_edit)
        form.addRow("Installed version:", self.version_edit)
        form.addRow("RetroAchievements ID:", self._row(self.ra_edit, ra_find))
        form.addRow("Box art file:", art_wrap)
        form.addRow("Search name:", self.search_edit)
        form.addRow("Description:", self.desc_edit)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        v = QVBoxLayout(self)
        v.addLayout(form)
        v.addWidget(btns)

    @staticmethod
    def _row(*widgets) -> QWidget:
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0)
        for x in widgets:
            h.addWidget(x)
        return w

    def _browse_exe(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select game executable", "",
                                              "Executables (*.exe);;All files (*.*)")
        if path:
            self.exe_edit.setText(path)

    def _browse_art(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select box art", "",
                                              "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*.*)")
        if path:
            self.art_edit.setText(path)

    def _art_from_url(self):
        url, ok = QInputDialog.getText(self, "Box art from URL", "Direct image URL:")
        url = url.strip()
        if not ok or not url:
            return
        dest = ART_DIR / f"{self.game['id']}_url{_img_ext(url)}"
        if download_image(url, dest):
            self.art_edit.setText(str(dest))
        else:
            QMessageBox.warning(self, "Download failed", "Could not download that URL.")

    def _find_ra(self):
        q = urllib.parse.quote(self.search_edit.text().strip()
                               or self.title_edit.text().strip())
        webbrowser.open(f"https://retroachievements.org/searchresults.php?s={q}&t=1")

    def result_game(self) -> dict:
        profiles = []
        for line in self.profiles_edit.toPlainText().splitlines():
            line = line.strip()
            if not line:
                continue
            if "|" in line:
                name, args = line.split("|", 1)
            else:
                name, args = line, ""
            profiles.append({"name": name.strip(), "args": args.strip()})
        tags = [t.strip() for t in self.tags_edit.text().split(",") if t.strip()]
        self.game.update({
            "title": self.title_edit.text().strip(),
            "platform": self.platform_edit.text().strip(),
            "exe_path": self.exe_edit.text().strip(),
            "args": self.args_edit.text().strip(),
            "released": self.released_edit.text().strip(),
            "genres": self.genres_edit.text().strip(),
            "tags": tags,
            "github_repo": self.repo_edit.text().strip(),
            "installed_version": self.version_edit.text().strip(),
            "ra_game_id": self.ra_edit.text().strip(),
            "art_path": self.art_edit.text().strip(),
            "search_name": self.search_edit.text().strip(),
            "description": self.desc_edit.toPlainText().strip(),
            "profiles": profiles,
        })
        return self.game


class SettingsDialog(QDialog):
    def __init__(self, parent, settings: dict):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.settings = dict(settings)
        self.setMinimumWidth(540)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list(THEMES.keys()))
        self.theme_combo.setCurrentText(settings.get("theme", "Dracula"))

        self.sgdb_edit = QLineEdit(settings.get("sgdb_api_key", ""))
        self.sgdb_edit.setPlaceholderText("Optional — premium hand-picked covers")

        self.tray_check = QCheckBox("Minimize to system tray instead of quitting")
        self.tray_check.setChecked(settings.get("minimize_to_tray", False))

        self.launch_check = QCheckBox("Check for updates on launch")
        self.launch_check.setChecked(settings.get("check_updates_on_launch", True))

        self.ra_user_edit = QLineEdit(settings.get("ra_username", ""))
        self.ra_user_edit.setPlaceholderText("RetroAchievements username")
        self.ra_key_edit = QLineEdit(settings.get("ra_api_key", ""))
        self.ra_key_edit.setPlaceholderText("Web API key — see link above")

        info = QLabel(
            "<b>Fetch Info</b> uses <a href='https://en.wikipedia.org'>Wikipedia</a> "
            "for descriptions and box art — no setup needed.<br>"
            "For curated cover art, paste a free "
            "<a href='https://www.steamgriddb.com/profile/preferences/api'>SteamGridDB API key</a>.<br>"
            "<b>RetroAchievements</b> (optional): shows each game's official RA set and "
            "your unlocks in the 🏆 tab. Get your Web API key at "
            "<a href='https://retroachievements.org/settings'>retroachievements.org/settings</a>.")
        info.setOpenExternalLinks(True)
        info.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Theme:", self.theme_combo)
        form.addRow("SteamGridDB key:", self.sgdb_edit)
        form.addRow("RA username:", self.ra_user_edit)
        form.addRow("RA API key:", self.ra_key_edit)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        v = QVBoxLayout(self)
        v.addWidget(info)
        v.addLayout(form)
        v.addWidget(self.tray_check)
        v.addWidget(self.launch_check)
        v.addWidget(btns)

    def result_settings(self) -> dict:
        self.settings["theme"] = self.theme_combo.currentText()
        self.settings["sgdb_api_key"] = self.sgdb_edit.text().strip()
        self.settings["minimize_to_tray"] = self.tray_check.isChecked()
        self.settings["check_updates_on_launch"] = self.launch_check.isChecked()
        self.settings["ra_username"] = self.ra_user_edit.text().strip()
        self.settings["ra_api_key"] = self.ra_key_edit.text().strip()
        return self.settings


class ScanDialog(QDialog):
    """Pick a folder; show found .exe files as a checklist to import."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Scan folder for games")
        self.setMinimumSize(560, 460)
        self.found: list[tuple[str, str]] = []   # (display_name, exe_path)

        top = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Choose a folder containing your recomp games…")
        browse = QPushButton("Browse…"); browse.clicked.connect(self._browse)
        scan = QPushButton("Scan"); scan.clicked.connect(self._scan)
        top.addWidget(self.path_edit); top.addWidget(browse); top.addWidget(scan)

        self.list = QListWidget()
        self.status = QLabel("")
        self.fetch_check = QCheckBox("Fetch art && info for recognized games after import")
        self.fetch_check.setChecked(True)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Add selected")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        v = QVBoxLayout(self)
        v.addLayout(top)
        v.addWidget(self.list, 1)
        v.addWidget(self.status)
        v.addWidget(self.fetch_check)
        v.addWidget(btns)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select games folder")
        if d:
            self.path_edit.setText(d)
            self._scan()

    def _scan(self):
        root = Path(self.path_edit.text().strip())
        self.list.clear()
        if not root.exists():
            self.status.setText("Folder not found.")
            return
        exes = []
        for pattern in ("*.exe", "*.AppImage"):   # AppImage covers Linux libraries
            for p in root.rglob(pattern):
                if SCAN_BLACKLIST.search(p.name):
                    continue
                exes.append(p)
        recognized = 0
        for p in sorted(exes):
            match = identify_exe(str(p))
            if match:
                recognized += 1
                name = match["title"]
                label = f"✓  {match['title']}   ·   {match['platform']}   —   {p.name}"
            else:
                # heuristic name: prefer parent folder name, else exe stem
                name = p.parent.name if p.parent != root else p.stem
                label = f"?  {name}   —   {p}"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, (name, str(p), match))
            self.list.addItem(item)
        self.status.setText(
            f"Found {len(exes)} executable(s) — {recognized} auto-recognized, "
            f"{len(exes) - recognized} unknown.")

    def selected(self) -> list[tuple]:
        """Return [(name, exe_path, match_or_None), ...] for checked rows."""
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(it.data(Qt.ItemDataRole.UserRole))
        return out


class IdentifyDialog(QDialog):
    """Review proposed auto-identifications for existing library games."""
    def __init__(self, parent, candidates: list[tuple[dict, dict]]):
        super().__init__(parent)
        self.setWindowTitle("Identify games")
        self.setMinimumSize(560, 420)

        intro = QLabel(
            "These games match known recomps by their executable. "
            "Check the ones you want to relabel:")
        intro.setWordWrap(True)

        self.list = QListWidget()
        for g, match in candidates:
            cur = g.get("title") or Path(g.get("exe_path", "")).name
            item = QListWidgetItem(f"{cur}   →   {match['title']}   ·   {match['platform']}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, (g, match))
            self.list.addItem(item)

        self.fetch_check = QCheckBox("Fetch art && info for identified games")
        self.fetch_check.setChecked(True)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Apply")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        v = QVBoxLayout(self)
        v.addWidget(intro)
        v.addWidget(self.list, 1)
        v.addWidget(self.fetch_check)
        v.addWidget(btns)

    def selected(self) -> list[tuple[dict, dict]]:
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(it.data(Qt.ItemDataRole.UserRole))
        return out


# ======================================================================
# Big Picture mode
# ======================================================================

class BigPictureWindow(QWidget):
    """Fullscreen, controller-first library view (Steam Big Picture style).

    A/Enter launches, B/Esc exits, left-right (d-pad, stick, LB/RB or arrow
    keys) browses, Y/Space toggles favorite. Painted directly for a clean
    10-foot look: giant center cover, dimmed neighbours, hint bar.
    """

    def __init__(self, main: "LauncherWindow", games: list[dict], start_index: int = 0):
        super().__init__()
        self.main = main
        self.games = games
        self.idx = max(0, min(start_index, len(games) - 1)) if games else 0
        self.flash_text = ""
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._clear_flash)
        self.setWindowTitle(f"{APP_NAME} — Big Picture")
        self.setCursor(Qt.CursorShape.BlankCursor)
        bg = find_bp_background()
        self._bg = QPixmap(bg) if bg else QPixmap()
        self._bg_cache: dict[tuple, QPixmap] = {}

    # ----- input -----
    def handle(self, btn: str):
        if btn in ("left", "lb"):
            self.move_sel(-1)
        elif btn in ("right", "rb"):
            self.move_sel(1)
        elif btn == "a":
            self.launch()
        elif btn in ("b", "back"):
            self.close()
        elif btn == "y":
            self.toggle_fav()

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Left:
            self.move_sel(-1)
        elif k == Qt.Key.Key_Right:
            self.move_sel(1)
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.launch()
        elif k in (Qt.Key.Key_Escape, Qt.Key.Key_F11):
            self.close()
        elif k == Qt.Key.Key_Space:
            self.toggle_fav()
        else:
            super().keyPressEvent(e)

    # ----- actions -----
    def game(self) -> dict | None:
        return self.games[self.idx] if self.games else None

    def move_sel(self, delta: int):
        if self.games:
            self.idx = (self.idx + delta) % len(self.games)
            self.update()

    def launch(self):
        g = self.game()
        if not g:
            return
        if g["id"] in self.main.running:
            self.flash("Already running")
            return
        exe = g.get("exe_path", "")
        if not exe or not Path(exe).exists():
            self.flash("No executable set — press B and use Edit")
            return
        self.main._select_id(g["id"])
        self.main.play_selected()
        self.flash(f"Launching {g['title']}…")

    def toggle_fav(self):
        g = self.game()
        if not g:
            return
        g["favorite"] = not g.get("favorite")
        self.main._persist()
        self.flash("★ Added to favorites" if g["favorite"] else "☆ Removed from favorites")

    def flash(self, text: str):
        self.flash_text = text
        self._flash_timer.start(2200)
        self.update()

    def _clear_flash(self):
        self.flash_text = ""
        self.update()

    def closeEvent(self, e):
        self.main.bp_window = None
        e.accept()

    # ----- painting -----
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        t = self.main.theme

        if not self._bg.isNull():
            # custom background art, cover-scaled, dimmed for readability
            key = (r.width(), r.height())
            pm = self._bg_cache.get(key)
            if pm is None:
                pm = self._bg.scaled(r.size(),
                                     Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                     Qt.TransformationMode.SmoothTransformation)
                self._bg_cache.clear()
                self._bg_cache[key] = pm
            p.drawPixmap((r.width() - pm.width()) // 2,
                         (r.height() - pm.height()) // 2, pm)
            p.fillRect(r, QColor(5, 5, 12, 165))
            # extra darkening toward the bottom so title/hints stay crisp
            g2 = QLinearGradient(0, r.height() * 0.55, 0, r.height())
            g2.setColorAt(0.0, QColor(3, 3, 8, 0))
            g2.setColorAt(1.0, QColor(3, 3, 8, 215))
            p.fillRect(r, QBrush(g2))
        else:
            grad = QLinearGradient(0, 0, 0, r.height())
            grad.setColorAt(0.0, QColor("#0d0d18"))
            grad.setColorAt(1.0, QColor("#05050a"))
            p.fillRect(r, QBrush(grad))

        # brand top-left, counter top-right
        p.setPen(QColor(150, 150, 170))
        f = QFont("Segoe UI", max(10, int(r.height() * 0.016)))
        p.setFont(f)
        p.drawText(r.adjusted(30, 20, -30, 0),
                   int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft), APP_NAME)
        if self.games:
            p.drawText(r.adjusted(30, 20, -30, 0),
                       int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight),
                       f"{self.idx + 1} / {len(self.games)}")

        if not self.games:
            p.setPen(QColor(150, 150, 170))
            p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), "Library is empty")
            p.end()
            return

        g = self.games[self.idx]
        cx, cy = r.width() // 2, int(r.height() * 0.44)
        ch = int(r.height() * 0.52)
        cw = int(ch * 0.72)
        sh = int(ch * 0.68)
        sw = int(sh * 0.72)
        gap = int(cw * 0.78)

        # dimmed neighbours (only when there's something different to show)
        if len(self.games) > 1:
            for offset in (-1, 1):
                if len(self.games) == 2 and offset == -1:
                    continue
                ng = self.games[(self.idx + offset) % len(self.games)]
                pm = art_for(ng, sw, sh)
                p.setOpacity(0.30)
                p.drawPixmap(cx + offset * (gap + sw // 2) - sw // 2, cy - sh // 2, pm)
            p.setOpacity(1.0)

        # center cover with soft accent glow + shadow plate + accent frame
        pm = art_for(g, cw, ch)
        x, y = cx - cw // 2, cy - ch // 2
        glow = QColor(t["accent"])
        glow.setAlpha(60)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawRoundedRect(QRectF(x - 16, y - 16, cw + 32, ch + 32), 18, 18)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawRoundedRect(QRectF(x - 10, y - 10, cw + 20, ch + 20), 14, 14)
        p.drawPixmap(x, y, pm)
        p.setPen(QPen(QColor(t["accent"]), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(x - 6, y - 6, cw + 12, ch + 12), 10, 10)

        # title (+ favorite star / now-playing)
        title = g.get("title", "?")
        if g.get("favorite"):
            title = "★ " + title
        p.setPen(QColor("#f2f2f7"))
        tf = QFont("Segoe UI", max(16, int(r.height() * 0.030)))
        tf.setBold(True)
        p.setFont(tf)
        title_rect = QRect(r.left() + 60, y + ch + 24, r.width() - 120,
                           int(r.height() * 0.06))
        p.drawText(title_rect, int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop), title)

        # meta line
        bits = [b for b in (g.get("platform", ""),) if b]
        if g.get("playtime_seconds", 0) >= 60:
            bits.append(f"⏱ {fmt_playtime(g['playtime_seconds'])}")
        if g["id"] in self.main.running:
            bits.append("● PLAYING")
        p.setPen(QColor(t["accent"]))
        mf = QFont("Segoe UI", max(11, int(r.height() * 0.017)))
        p.setFont(mf)
        meta_rect = QRect(title_rect.left(), title_rect.bottom(), title_rect.width(),
                          int(r.height() * 0.05))
        p.drawText(meta_rect, int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                   "   •   ".join(bits))

        # transient flash message
        if self.flash_text:
            p.setPen(QColor("#ffffff"))
            ff = QFont("Segoe UI", max(12, int(r.height() * 0.020)))
            ff.setBold(True)
            p.setFont(ff)
            p.drawText(r.adjusted(0, 0, 0, -int(r.height() * 0.14)),
                       int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom),
                       self.flash_text)

        # hint bar
        p.setPen(QColor(140, 140, 160))
        hf = QFont("Segoe UI", max(10, int(r.height() * 0.016)))
        p.setFont(hf)
        p.drawText(r.adjusted(0, 0, 0, -30),
                   int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom),
                   "Ⓐ Play        Ⓑ Exit        ⬅ ➡ Browse        Ⓨ Favorite")
        p.end()


# ======================================================================
# Main window
# ======================================================================

class LauncherWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1280, 820)

        self.settings = load_settings()
        self.theme = THEMES.get(self.settings["theme"], THEMES["Dracula"])
        self.games = load_library()
        self.model = GameModel(self.games)
        self.model.on_change = self._persist
        self.model.reordered.connect(self._select_id)

        self.selected_id: str | None = None
        self.running: dict[str, tuple] = {}   # id -> (Popen, start_monotonic)
        self._threads = []                    # keep refs alive
        self._ra_cache: dict[str, dict] = {}  # library id -> RA payload (session)

        self._build_ui()
        self._build_tray()
        self._build_shortcuts()
        self.apply_theme()

        self.delegate.scale = self.settings["card_scale"] / 100.0
        self.zoom_slider.setValue(self.settings["card_scale"])

        # process-watch timer
        self._proc_timer = QTimer(self)
        self._proc_timer.timeout.connect(self._poll_processes)
        self._proc_timer.start(1000)

        # big picture + controller
        self.bp_window = None
        self.controller = None
        try:
            poller = ControllerPoller(self)
            if poller.available:
                self.controller = poller
                poller.pressed.connect(self._on_controller)
                poller.connected.connect(lambda: self.toast("🎮 Controller connected"))
                poller.disconnected.connect(lambda: self.toast("🎮 Controller disconnected"))
        except Exception:
            pass

        self.rebuild_sidebar()
        if self.model.rowCount() > 0:
            self.grid.setCurrentIndex(self.model.index(0, 0))
            self._select_row(0)

        if self.settings.get("check_updates_on_launch", True):
            QTimer.singleShot(1500, self.check_updates_quiet)

    # ---------------- UI ----------------
    def _build_ui(self):
        tb = QToolBar(); tb.setMovable(False)
        self.addToolBar(tb)
        self._act(tb, "➕  Add", self.add_game)
        self._act(tb, "📁  Scan Folder", self.scan_folder)
        self._act(tb, "🪄  Identify", self.identify_library)
        self._act(tb, "🌐  Fetch Info", self.fetch_selected)
        self._act(tb, "✎  Edit", self.edit_selected)
        self._act(tb, "🗑  Remove", self.remove_selected)
        tb.addSeparator()
        self._act(tb, "⬆  Check Updates", self.check_updates_all)
        self._act(tb, "🖥  Big Picture", self.toggle_big_picture)
        tb.addSeparator()
        self._act(tb, "⚙  Settings", self.open_settings)
        self._act(tb, "❤  Support", self.open_support)
        self._act(tb, "💬  Get Help", self.open_help)

        # search box on the toolbar (right-aligned)
        spacer = QWidget(); spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search…  (Ctrl+F)")
        self.search_edit.setFixedWidth(220)
        self.search_edit.textChanged.connect(self._on_search)
        tb.addWidget(self.search_edit)

        self.setStatusBar(QStatusBar())

        central = QWidget(); self.setCentralWidget(central)
        root = QHBoxLayout(central); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # sidebar
        self.sidebar = QListWidget(); self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(180)
        self.sidebar.currentRowChanged.connect(self._on_sidebar)
        root.addWidget(self.sidebar)

        # grid
        grid_wrap = QWidget(); gv = QVBoxLayout(grid_wrap)
        gv.setContentsMargins(0, 0, 0, 0); gv.setSpacing(0)
        self.grid = GameGrid()
        self.delegate = GameDelegate(self.grid)
        self.grid.setItemDelegate(self.delegate)
        self.grid.setModel(self.model)
        self.grid.selectionModel().currentChanged.connect(
            lambda cur, prev: self._select_row(cur.row()))
        self.grid.doubleClicked.connect(lambda i: self.play_selected())
        self.grid.activateGame.connect(self.play_selected)
        gv.addWidget(self.grid, 1)

        # zoom bar
        zbar = QWidget(); zl = QHBoxLayout(zbar); zl.setContentsMargins(12, 4, 12, 8)
        zl.addStretch()
        zl.addWidget(QLabel("Card size"))
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(70, 160)
        self.zoom_slider.setFixedWidth(160)
        self.zoom_slider.valueChanged.connect(self._on_zoom)
        zl.addWidget(self.zoom_slider)
        gv.addWidget(zbar)
        root.addWidget(grid_wrap, 1)

        # details panel
        self.details = self._build_details()
        root.addWidget(self.details)

    def _build_details(self) -> QWidget:
        panel = QFrame(); panel.setObjectName("detailsPanel")
        panel.setMinimumWidth(380); panel.setMaximumWidth(460)
        v = QVBoxLayout(panel); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)

        self.hero = HeroBanner()
        v.addWidget(self.hero)

        body = QWidget(); bl = QVBoxLayout(body)
        bl.setContentsMargins(18, 14, 18, 14); bl.setSpacing(10)

        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("color: #6272a4;")
        bl.addWidget(self.stats_label)

        self.tabs = QTabWidget()
        # About
        self.about_text = QTextEdit(); self.about_text.setReadOnly(True)
        self.about_text.setStyleSheet("background: transparent; border: 0;")
        self.tabs.addTab(self.about_text, "About")
        # Screenshots
        shots_tab = QWidget(); sl = QVBoxLayout(shots_tab); sl.setContentsMargins(0, 8, 0, 0)
        self.shots = ScreenshotStrip()
        add_shot = QPushButton("Add Screenshot…"); add_shot.clicked.connect(self.add_screenshot)
        sl.addWidget(self.shots); sl.addWidget(add_shot); sl.addStretch()
        self.tabs.addTab(shots_tab, "Screenshots")
        # Info
        info_tab = QWidget(); il = QFormLayout(info_tab); il.setContentsMargins(4, 10, 4, 4)
        self.info_exe = QLabel("—"); self.info_exe.setWordWrap(True)
        self.info_repo = QLabel("—"); self.info_repo.setOpenExternalLinks(True)
        self.info_update = QLabel("—")
        il.addRow("Executable:", self.info_exe)
        il.addRow("GitHub:", self.info_repo)
        il.addRow("Updates:", self.info_update)
        self.tabs.addTab(info_tab, "Info")
        # RetroAchievements
        ra_tab = QWidget()
        rl = QVBoxLayout(ra_tab)
        rl.setContentsMargins(0, 8, 0, 0)
        ra_head = QHBoxLayout()
        self.ra_status = QLabel("")
        self.ra_status.setWordWrap(True)
        ra_head.addWidget(self.ra_status, 1)
        self.ra_btn = QPushButton("Load")
        self.ra_btn.clicked.connect(self.load_ra_achievements)
        ra_head.addWidget(self.ra_btn)
        rl.addLayout(ra_head)
        self.ra_list = QListWidget()
        self.ra_list.setIconSize(QSize(32, 32))
        self.ra_list.setWordWrap(True)
        rl.addWidget(self.ra_list, 1)
        self.tabs.addTab(ra_tab, "🏆 RA")
        bl.addWidget(self.tabs, 1)

        # profile + play row
        play_row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(110)
        play_row.addWidget(self.profile_combo)
        self.fav_btn = QPushButton("☆")
        self.fav_btn.setFixedWidth(44)
        self.fav_btn.setToolTip("Toggle favorite (Space)")
        self.fav_btn.clicked.connect(self.toggle_favorite)
        play_row.addWidget(self.fav_btn)
        bl.addLayout(play_row)

        self.download_btn = QPushButton("⬇  Get Latest Release")
        self.download_btn.setToolTip("Download the newest build from GitHub")
        self.download_btn.clicked.connect(self.download_latest)
        bl.addWidget(self.download_btn)

        self.play_btn = QPushButton("▶  Play")
        self.play_btn.setObjectName("playButton")
        self.play_btn.setMinimumHeight(46)
        self.play_btn.clicked.connect(self.play_selected)
        bl.addWidget(self.play_btn)

        v.addWidget(body, 1)
        return panel

    def _act(self, tb, text, slot):
        a = QAction(text, self); a.triggered.connect(slot); tb.addAction(a); return a

    def _build_tray(self):
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        show_a = menu.addAction("Show"); show_a.triggered.connect(self._restore)
        menu.addSeparator()
        quit_a = menu.addAction("Quit"); quit_a.triggered.connect(self._quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self._restore() if r == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()

    def _build_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: self.search_edit.setFocus())
        QShortcut(QKeySequence("F2"), self, activated=self.edit_selected)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, activated=self.remove_selected)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=self.open_settings)
        QShortcut(QKeySequence("Space"), self, activated=self.toggle_favorite)
        QShortcut(QKeySequence("Ctrl+="), self, activated=lambda: self.zoom_slider.setValue(self.zoom_slider.value() + 10))
        QShortcut(QKeySequence("Ctrl+-"), self, activated=lambda: self.zoom_slider.setValue(self.zoom_slider.value() - 10))
        QShortcut(QKeySequence("F11"), self, activated=self.toggle_big_picture)

    # ---------------- theme ----------------
    def apply_theme(self):
        self.theme = THEMES.get(self.settings["theme"], THEMES["Dracula"])
        self.setStyleSheet(build_stylesheet(self.theme))
        self.delegate.theme = self.theme
        self.hero.theme = self.theme
        self.grid.viewport().update()

    # ---------------- sidebar ----------------
    def rebuild_sidebar(self):
        cur = self.sidebar.currentRow()
        self.sidebar.blockSignals(True)
        self.sidebar.clear()
        QListWidgetItem("🎮  All Games", self.sidebar).setData(Qt.ItemDataRole.UserRole, ("all", None))
        QListWidgetItem("★  Favorites", self.sidebar).setData(Qt.ItemDataRole.UserRole, ("fav", None))
        tags = sorted({t for g in self.games for t in g.get("tags", [])})
        if tags:
            hdr = QListWidgetItem("— Tags —", self.sidebar)
            hdr.setFlags(Qt.ItemFlag.NoItemFlags)
            for t in tags:
                QListWidgetItem(f"🏷  {t}", self.sidebar).setData(Qt.ItemDataRole.UserRole, ("tag", t))
        self.sidebar.blockSignals(False)
        if cur < 0:
            cur = 0
        self.sidebar.setCurrentRow(min(cur, self.sidebar.count() - 1))

    def _on_sidebar(self, row: int):
        item = self.sidebar.item(row)
        if not item:
            return
        kind, val = item.data(Qt.ItemDataRole.UserRole) or ("all", None)
        if kind == "all":
            self.model.set_filter(tag=None, fav_only=False)
        elif kind == "fav":
            self.model.set_filter(tag=None, fav_only=True)
        elif kind == "tag":
            self.model.set_filter(tag=val, fav_only=False)
        self._update_drag_state()
        if self.model.rowCount() > 0:
            self.grid.setCurrentIndex(self.model.index(0, 0))

    def _on_search(self, text: str):
        self.model.set_filter(search=text)
        self._update_drag_state()

    def _update_drag_state(self):
        draggable = not self.model.is_filtered
        self.grid.setDragEnabled(draggable)
        self.grid.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove
                                  if draggable else QAbstractItemView.DragDropMode.NoDragDrop)

    # ---------------- zoom ----------------
    def _on_zoom(self, value: int):
        self.delegate.scale = value / 100.0
        self.settings["card_scale"] = value
        save_settings(self.settings)
        self.grid.reset()
        self.grid.scheduleDelayedItemsLayout()
        if self.selected_id:
            self._select_id(self.selected_id)

    # ---------------- selection / details ----------------
    def _select_row(self, row: int):
        g = self.model.game_at(row)
        if g:
            self.selected_id = g["id"]
            self._render_details(g)

    def _select_id(self, gid: str):
        row = self.model.row_of_id(gid)
        if row >= 0:
            self.grid.setCurrentIndex(self.model.index(row, 0))
            self._select_row(row)

    def _game(self, gid: str) -> dict | None:
        for g in self.games:
            if g["id"] == gid:
                return g
        return None

    def _render_details(self, g: dict):
        self.hero.set_game(g)
        # stats
        bits = []
        if g.get("playtime_seconds", 0) >= 1:
            bits.append(f"⏱ {fmt_playtime(g['playtime_seconds'])}")
        if g.get("launch_count"):
            bits.append(f"▶ {g['launch_count']} launches")
        if g.get("last_played"):
            bits.append(f"Last: {g['last_played']}")
        self.stats_label.setText("    ".join(bits) or "Never played")
        # about
        self.about_text.setPlainText(
            g.get("description") or "No description yet. Click “Fetch Info” to pull from Wikipedia.")
        # screenshots
        self.shots.set_shots(g.get("screenshots", []))
        # info tab
        self.info_exe.setText(g.get("exe_path") or "— not set —")
        repo = g.get("github_repo", "")
        if repo:
            self.info_repo.setText(f"<a href='https://github.com/{repo}'>{repo}</a>")
        else:
            self.info_repo.setText("—")
        self._render_update_label(g)
        self._render_ra(g)
        # profiles
        self.profile_combo.clear()
        self.profile_combo.addItem("Default")
        for p in g.get("profiles", []):
            self.profile_combo.addItem(p.get("name", "?"))
        # favorite button
        self.fav_btn.setText("★" if g.get("favorite") else "☆")
        # download button (needs a repo)
        self.download_btn.setEnabled(bool(g.get("github_repo")))
        # play / stop button
        self._update_play_button(g)

    def _render_update_label(self, g: dict):
        latest = g.get("latest_version", "")
        installed = g.get("installed_version", "")
        if not g.get("github_repo"):
            self.info_update.setText("— (no repo set)")
        elif not latest:
            self.info_update.setText("Not checked yet")
        elif installed and latest != installed:
            self.info_update.setText(f"⬆ Update available: {latest} (you have {installed})")
        elif installed:
            self.info_update.setText(f"✓ Up to date ({installed})")
        else:
            self.info_update.setText(f"Latest release: {latest}")

    def _update_play_button(self, g: dict):
        if g["id"] in self.running:
            self.play_btn.setText("■  Stop")
            self.play_btn.setObjectName("stopButton")
            self.play_btn.setEnabled(True)
        else:
            playable = bool(g.get("exe_path") and Path(g["exe_path"]).exists())
            self.play_btn.setText("▶  Play" if playable else "▶  Set executable to play")
            self.play_btn.setObjectName("playButton")
            self.play_btn.setEnabled(playable)
        self.play_btn.style().unpolish(self.play_btn)
        self.play_btn.style().polish(self.play_btn)

    # ---------------- actions ----------------
    def add_game(self):
        title, ok = QInputDialog.getText(self, "Add Game", "Game title:")
        if not ok or not title.strip():
            return
        g = blank_game(title.strip())
        self.model.add_game(g)
        self.rebuild_sidebar()
        self._select_id(g["id"])
        self.edit_selected()

    @staticmethod
    def _apply_match(g: dict, match: dict):
        """Fill a game's metadata from a KNOWN_RECOMPS entry."""
        g["title"] = match["title"]
        g["platform"] = match["platform"]
        g["search_name"] = match["search"]
        g["github_repo"] = match.get("github_repo", "")
        g["tags"] = list(match.get("tags", []))

    def scan_folder(self):
        dlg = ScanDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        added = 0
        recognized_ids = []
        for name, exe, match in dlg.selected():
            # skip if exe already in library
            if any(x.get("exe_path") == exe for x in self.games):
                continue
            g = blank_game(name)
            g["exe_path"] = exe
            if match:
                self._apply_match(g, match)
                recognized_ids.append(g["id"])
            self.games.append(g)
            added += 1
        if added:
            self.model.refresh_all()
            self._persist()
            self.rebuild_sidebar()
            self.toast(f"Added {added} game(s) — {len(recognized_ids)} auto-recognized.")
            if recognized_ids and dlg.fetch_check.isChecked():
                self._queue_fetches(recognized_ids)
        else:
            self.toast("No new games added.")

    def identify_library(self):
        """Run the fingerprint DB over existing games and offer to apply fixes."""
        candidates = []
        for g in self.games:
            exe = g.get("exe_path", "")
            if not exe:
                continue
            match = identify_exe(exe)
            if match and match["title"] != g.get("title"):
                candidates.append((g, match))
        if not candidates:
            self.toast("Nothing to identify — every game with an exe is already labeled.")
            return
        dlg = IdentifyDialog(self, candidates)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        changed_ids = []
        for g, match in dlg.selected():
            self._apply_match(g, match)
            changed_ids.append(g["id"])
        if changed_ids:
            _PIX_CACHE.clear()
            self.model.refresh_all()
            self._persist()
            self.rebuild_sidebar()
            if self.selected_id:
                self._select_id(self.selected_id)
            self.toast(f"Identified {len(changed_ids)} game(s).")
            if dlg.fetch_check.isChecked():
                self._queue_fetches(changed_ids)

    def edit_selected(self):
        if not self.selected_id:
            return
        g = self._game(self.selected_id)
        if not g:
            return
        dlg = EditGameDialog(self, g)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated = dlg.result_game()
            for i, x in enumerate(self.games):
                if x["id"] == updated["id"]:
                    self.games[i] = updated
                    break
            _PIX_CACHE.clear()
            self.model.refresh_all()
            self._persist()
            self.rebuild_sidebar()
            self._select_id(updated["id"])

    def remove_selected(self):
        if not self.selected_id:
            return
        g = self._game(self.selected_id)
        if not g:
            return
        if QMessageBox.question(
                self, "Remove game",
                f"Remove '{g['title']}' from the launcher?\n(The game files are NOT deleted.)"
        ) != QMessageBox.StandardButton.Yes:
            return
        self.model.remove_id(self.selected_id)
        self.games = self.model.all_games()
        self.rebuild_sidebar()
        if self.model.rowCount() > 0:
            self.grid.setCurrentIndex(self.model.index(0, 0))
            self._select_row(0)
        else:
            self.selected_id = None
            self.hero.set_game(None)
            self.about_text.clear()
            self.stats_label.setText("")
            self.play_btn.setEnabled(False)

    def toggle_favorite(self):
        if not self.selected_id:
            return
        g = self._game(self.selected_id)
        if not g:
            return
        g["favorite"] = not g.get("favorite")
        self.fav_btn.setText("★" if g["favorite"] else "☆")
        self._persist()
        self.model.refresh_all()
        self._select_id(self.selected_id)

    def add_screenshot(self):
        if not self.selected_id:
            return
        g = self._game(self.selected_id)
        if not g:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add screenshots", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not paths:
            return
        dest_dir = SHOTS_DIR / g["id"]
        dest_dir.mkdir(exist_ok=True)
        for p in paths:
            src = Path(p)
            dest = dest_dir / src.name
            try:
                shutil.copy2(src, dest)
                g.setdefault("screenshots", []).append(str(dest))
            except Exception:
                pass
        self._persist()
        self.shots.set_shots(g.get("screenshots", []))

    # ---------------- launching ----------------
    def play_selected(self):
        if not self.selected_id:
            return
        g = self._game(self.selected_id)
        if not g:
            return
        if g["id"] in self.running:
            self._stop_game(g)
            return
        exe = g.get("exe_path", "")
        if not exe or not Path(exe).exists():
            QMessageBox.warning(self, "Cannot launch", "Set the executable path first (Edit / F2).")
            return
        # resolve profile args
        args_str = g.get("args", "")
        idx = self.profile_combo.currentIndex()
        if idx > 0:
            prof = g.get("profiles", [])[idx - 1]
            args_str = prof.get("args", "")
        args = args_str.split() if args_str else []
        try:
            proc = subprocess.Popen([exe, *args], cwd=str(Path(exe).parent))
        except Exception as e:
            QMessageBox.critical(self, "Launch failed", str(e))
            return
        self.running[g["id"]] = (proc, time.monotonic())
        self.delegate.now_playing.add(g["id"])
        g["launch_count"] = g.get("launch_count", 0) + 1
        g["last_played"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._persist()
        self.grid.viewport().update()
        self._update_play_button(g)
        self.tray.setToolTip(f"{APP_NAME} — Playing {g['title']}")
        self.statusBar().showMessage(f"Launched: {g['title']}", 4000)

    def _stop_game(self, g: dict):
        entry = self.running.get(g["id"])
        if not entry:
            return
        proc, _ = entry
        try:
            proc.terminate()
        except Exception:
            pass

    def _poll_processes(self):
        finished = []
        for gid, (proc, start) in list(self.running.items()):
            if proc.poll() is not None:
                finished.append((gid, time.monotonic() - start))
        for gid, elapsed in finished:
            self.running.pop(gid, None)
            self.delegate.now_playing.discard(gid)
            g = self._game(gid)
            if g:
                g["playtime_seconds"] = int(g.get("playtime_seconds", 0) + elapsed)
                self._persist()
                if gid == self.selected_id:
                    self._render_details(g)
                self.toast(f"Played {g['title']} for {fmt_playtime(elapsed)}")
        if finished:
            self.grid.viewport().update()
            self.tray.setToolTip(APP_NAME)

    # ---------------- fetch / updates ----------------
    def _queue_fetches(self, game_ids: list[str]):
        """Fetch art + info for several games, one at a time."""
        self._fetch_queue = [gid for gid in game_ids if self._game(gid)]
        self._fetch_total = len(self._fetch_queue)
        if self._fetch_queue:
            self._fetch_next()

    def _fetch_next(self):
        if not getattr(self, "_fetch_queue", None):
            _PIX_CACHE.clear()
            self.model.refresh_all()
            if self.selected_id:
                self._select_id(self.selected_id)
            self.statusBar().clearMessage()
            self.toast("Finished fetching art & info.")
            return
        gid = self._fetch_queue.pop(0)
        g = self._game(gid)
        if not g:
            self._fetch_next()
            return
        done = self._fetch_total - len(self._fetch_queue)
        query = g.get("search_name") or g.get("title")
        sgdb = self.settings.get("sgdb_api_key", "").strip()
        self.statusBar().showMessage(
            f"Fetching info ({done}/{self._fetch_total}): {g.get('title')}…")
        thread = QThread()
        worker = FetchWorker(query, gid, sgdb_key=sgdb)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def apply(data, gid=gid):
            gg = self._game(gid)
            if gg:
                if not gg.get("description"):
                    gg["description"] = data.get("description", "")
                if data.get("art_path"):
                    gg["art_path"] = data["art_path"]
                self._persist()

        worker.finished.connect(apply)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._fetch_next)   # chain to next game
        self._threads.append((thread, worker))
        thread.start()

    def fetch_selected(self):
        if not self.selected_id:
            return
        g = self._game(self.selected_id)
        if not g:
            return
        query = g.get("search_name") or g.get("title")
        sgdb = self.settings.get("sgdb_api_key", "").strip()
        self.statusBar().showMessage(
            f"Fetching {'Wikipedia + SteamGridDB' if sgdb else 'Wikipedia'} info for '{query}'…")
        thread = QThread()
        worker = FetchWorker(query, g["id"], sgdb_key=sgdb)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_fetched)
        worker.failed.connect(self._on_fetch_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(lambda: self._threads.remove((thread, worker))
                                if (thread, worker) in self._threads else None)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._threads.append((thread, worker))
        thread.start()

    def _on_fetched(self, data: dict):
        if not self.selected_id:
            return
        g = self._game(self.selected_id)
        if not g:
            return
        if not g.get("description"):
            g["description"] = data.get("description", "")
        if data.get("art_path"):
            g["art_path"] = data["art_path"]
        _PIX_CACHE.clear()
        self._persist()
        self.model.refresh_all()
        self._select_id(g["id"])
        self.toast(f"Fetched info from {data.get('source') or 'online'} ✓")

    def _on_fetch_failed(self, msg: str):
        self.statusBar().showMessage("Fetch failed", 4000)
        QMessageBox.warning(self, "Fetch failed", msg)

    def download_latest(self):
        if not self.selected_id:
            return
        g = self._game(self.selected_id)
        if not g:
            return
        repo = g.get("github_repo", "").strip()
        if not repo:
            self.toast("Set a GitHub repo first (Edit → GitHub repo).")
            return
        dest = QFileDialog.getExistingDirectory(
            self, f"Download '{g['title']}' to which folder?")
        if not dest:
            return
        gid = g["id"]
        self.download_btn.setEnabled(False)
        self.statusBar().showMessage(f"Downloading latest {g['title']}…")
        thread = QThread()
        worker = DownloadWorker(repo, dest)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def on_progress(pct):
            if pct >= 0:
                self.statusBar().showMessage(f"Downloading {g['title']}… {pct}%")

        def on_finished(path, tag, gid=gid):
            gg = self._game(gid)
            if gg:
                if tag:
                    gg["installed_version"] = tag
                    gg["latest_version"] = tag
                self._persist()
                self.model.refresh_all()
                if gid == self.selected_id:
                    self._render_details(gg)
            self.statusBar().clearMessage()
            self.toast(f"Downloaded {tag or 'latest'} → {Path(path).name}")
            reveal_in_file_manager(Path(path).parent)
            self.download_btn.setEnabled(True)

        def on_no_asset(url, tag):
            self.statusBar().clearMessage()
            webbrowser.open(url)
            self.toast("No build for this OS in the release — opened the downloads page.")
            self.download_btn.setEnabled(True)

        def on_failed(msg):
            self.statusBar().clearMessage()
            QMessageBox.warning(self, "Download failed", msg)
            self.download_btn.setEnabled(True)

        worker.progress.connect(on_progress)
        worker.finished.connect(on_finished)
        worker.no_asset.connect(on_no_asset)
        worker.failed.connect(on_failed)
        for sig in (worker.finished, worker.no_asset, worker.failed):
            sig.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._threads.append((thread, worker))
        thread.start()

    def check_updates_quiet(self):
        """Background update check on launch — no modal, toast only if updates exist."""
        jobs = [(g["id"], g["github_repo"]) for g in self.games if g.get("github_repo")]
        if not jobs:
            return
        thread = QThread()
        worker = UpdateWorker(jobs)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.one.connect(self._on_update_one)
        worker.done.connect(self._on_updates_quiet_done)
        worker.done.connect(thread.quit)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._threads.append((thread, worker))
        thread.start()

    def _on_updates_quiet_done(self, n: int):
        self._persist()
        self.model.refresh_all()
        if self.selected_id:
            g = self._game(self.selected_id)
            if g:
                self._render_update_label(g)
        updates = [g for g in self.games
                   if g.get("latest_version") and g.get("installed_version")
                   and g["latest_version"] != g["installed_version"]]
        if updates:
            names = ", ".join(g["title"] for g in updates[:3])
            extra = f" +{len(updates) - 3} more" if len(updates) > 3 else ""
            self.toast(f"Updates available: {names}{extra}")

    def check_updates_all(self):
        jobs = [(g["id"], g["github_repo"]) for g in self.games if g.get("github_repo")]
        if not jobs:
            self.toast("No games have a GitHub repo set (Edit → GitHub repo).")
            return
        self.statusBar().showMessage(f"Checking {len(jobs)} repo(s) for updates…")
        thread = QThread()
        worker = UpdateWorker(jobs)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.one.connect(self._on_update_one)
        worker.done.connect(self._on_updates_done)
        worker.done.connect(thread.quit)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._threads.append((thread, worker))
        thread.start()

    def _on_update_one(self, gid: str, tag: str):
        g = self._game(gid)
        if g:
            g["latest_version"] = tag

    def _on_updates_done(self, n: int):
        self._persist()
        if self.selected_id:
            g = self._game(self.selected_id)
            if g:
                self._render_update_label(g)
        updates = [g for g in self.games
                   if g.get("latest_version") and g.get("installed_version")
                   and g["latest_version"] != g["installed_version"]]
        if updates:
            names = ", ".join(g["title"] for g in updates[:3])
            self.toast(f"Updates available: {names}")
        else:
            self.toast(f"Checked {n} repo(s) — all current / versions unknown.")

    # ---------------- settings ----------------
    def open_settings(self):
        dlg = SettingsDialog(self, self.settings)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.settings = dlg.result_settings()
            save_settings(self.settings)
            self.apply_theme()

    # ---------------- retroachievements ----------------
    def _render_ra(self, g: dict):
        self.ra_list.clear()
        payload = self._ra_cache.get(g["id"])
        if payload:
            self._fill_ra(payload)
            return
        self.ra_btn.setText("Load")
        self.ra_btn.setEnabled(True)
        if self.settings.get("ra_username") and self.settings.get("ra_api_key"):
            self.ra_status.setText("Click Load to fetch this game's RetroAchievements "
                                   "set and your progress.")
        else:
            self.ra_status.setText("Set your RetroAchievements username + Web API key "
                                   "in Settings to use this tab.")

    def _fill_ra(self, payload: dict):
        pct = f"  ({payload['completion']})" if payload.get("completion") else ""
        self.ra_status.setText(
            f"<b>{payload['game_title']}</b> — "
            f"{payload['earned']}/{payload['total']} unlocked{pct}")
        self.ra_btn.setText("Refresh")
        self.ra_btn.setEnabled(True)
        self.ra_list.clear()
        for a in payload["achievements"]:
            mark = "✓" if a["earned"] else "🔒"
            item = QListWidgetItem(f"{mark} {a['title']}  ·  {a['points']} pts\n{a['desc']}")
            if a["icon"]:
                item.setIcon(QIcon(a["icon"]))
            if not a["earned"]:
                item.setForeground(QColor(self.theme["subtext"]))
            self.ra_list.addItem(item)

    def load_ra_achievements(self):
        if not self.selected_id:
            return
        g = self._game(self.selected_id)
        if not g:
            return
        user = self.settings.get("ra_username", "").strip()
        key = self.settings.get("ra_api_key", "").strip()
        if not user or not key:
            self.toast("Set your RetroAchievements username + API key in Settings.")
            return
        self.ra_btn.setEnabled(False)
        self.ra_status.setText("Fetching from RetroAchievements…")
        thread = QThread()
        worker = RAWorker(g["id"], g.get("search_name") or g.get("title", ""),
                          list(g.get("tags", [])), g.get("ra_game_id", ""), user, key)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_ra_done)
        worker.failed.connect(self._on_ra_failed)
        for sig in (worker.finished, worker.failed):
            sig.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._threads.append((thread, worker))
        thread.start()

    def _on_ra_done(self, lib_id: str, payload: dict):
        self._ra_cache[lib_id] = payload
        g = self._game(lib_id)
        if g and payload.get("ra_id") and g.get("ra_game_id") != payload["ra_id"]:
            g["ra_game_id"] = payload["ra_id"]     # remember the auto-match
            self._persist()
        if lib_id == self.selected_id:
            self._fill_ra(payload)

    def _on_ra_failed(self, lib_id: str, msg: str):
        if lib_id == self.selected_id:
            self.ra_btn.setEnabled(True)
            self.ra_btn.setText("Load")
            self.ra_status.setText(f"RetroAchievements: {msg}")

    # ---------------- big picture / controller ----------------
    def toggle_big_picture(self):
        if self.bp_window:
            self.bp_window.close()
            return
        games = list(self.model._visible) or list(self.games)
        if not games:
            self.toast("Library is empty — add a game first.")
            return
        start = 0
        if self.selected_id:
            for i, g in enumerate(games):
                if g["id"] == self.selected_id:
                    start = i
                    break
        self.bp_window = BigPictureWindow(self, games, start)
        self.bp_window.showFullScreen()

    def _on_controller(self, btn: str):
        bp = self.bp_window
        if bp and bp.isVisible():
            if bp.isActiveWindow():
                bp.handle(btn)
            return
        if not self.isActiveWindow():
            return  # a game (or another app) has focus — don't steal input
        if btn in ("left", "right", "up", "down"):
            self._controller_move(btn)
        elif btn == "a":
            self.play_selected()
        elif btn == "y":
            self.toggle_favorite()
        elif btn == "start":
            self.toggle_big_picture()

    def _controller_move(self, direction: str):
        count = self.model.rowCount()
        if not count:
            return
        cur = self.grid.currentIndex().row()
        if cur < 0:
            cur = 0
        w, _ = self.delegate.card_size()
        cell = w + 16 + self.grid.spacing()
        cols = max(1, self.grid.viewport().width() // cell)
        delta = {"left": -1, "right": 1, "up": -cols, "down": cols}[direction]
        new = max(0, min(count - 1, cur + delta))
        self.grid.setCurrentIndex(self.model.index(new, 0))

    def open_support(self):
        webbrowser.open(SUPPORT_URL)

    def open_help(self):
        webbrowser.open(DISCORD_URL)

    # ---------------- misc ----------------
    def toast(self, text: str):
        t = Toast(self, text, self.theme["accent"])
        t.show_at(self.rect())

    def _persist(self):
        save_library(self.games)

    def resizeEvent(self, e):
        super().resizeEvent(e)

    def _restore(self):
        self.showNormal(); self.raise_(); self.activateWindow()

    def _quit(self):
        self._really_quit = True
        QApplication.instance().quit()

    def closeEvent(self, e):
        if self.settings.get("minimize_to_tray") and not getattr(self, "_really_quit", False):
            e.ignore()
            self.hide()
            self.tray.showMessage(APP_NAME, "Still running in the tray.",
                                  QSystemTrayIcon.MessageIcon.Information, 2000)
        else:
            self.tray.hide()
            e.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    QApplication.setQuitOnLastWindowClosed(False)
    w = LauncherWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
