from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import time
import threading
import urllib.error
import urllib.request
import hashlib
import shutil
from urllib.parse import urlparse
from PIL import Image, ImageOps
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk
import pygame
from mutagen import File as MutagenFile

APP_NAME = "Sanistra"
APP_VERSION = "2.2.0"
SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".mid", ".midi", ".opus", ".aiff", ".aif", ".m4a", ".mp4", ".wma"}

# Palette values can be changed from Settings; user preferences live outside the app folder.
BG = "#0B0D12"
SIDEBAR = "#10131B"
SURFACE = "#151925"
SURFACE_2 = "#1C2130"
SURFACE_3 = "#252B3D"
TEXT = "#F4F5FA"
MUTED = "#9099AD"
ACCENT = "#A99AFF"
ACCENT_HOVER = "#BEB2FF"
GREEN = "#7DDBB0"
RED = "#FF7E91"
BORDER = "#282E40"
FONT = "Segoe UI"


def app_data_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", str(Path.home()))) / "LumenPlayer"  # Legacy path: preserve existing library and settings after renaming.
    else:
        root = Path.home() / ".lumen-player"  # Legacy path for compatibility.
    root.mkdir(parents=True, exist_ok=True)
    return root


DATA_DIR = app_data_dir()
STATE_FILE = DATA_DIR / "library.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
UPDATE_CONFIG_FILE = DATA_DIR / "update_config.json"
# Maintainer: set this once before building/publishing the app, e.g. "yourname/Sanistra".
# End users will not need to enter a repository in the app settings.
UPDATE_REPOSITORY = "yasikami/Sanistra"

DEFAULT_APP_SETTINGS = {
    "theme": "Midnight",
    "accent": "#A99AFF",
    "scale": 100,
    "compact_rows": False,
    "show_album": True,
    "background_image": "",
    "background_dim": 48,
}
THEMES = {
    "Midnight": {
        "BG": "#0B0D12", "SIDEBAR": "#10131B", "SURFACE": "#151925",
        "SURFACE_2": "#1C2130", "SURFACE_3": "#252B3D", "TEXT": "#F4F5FA",
        "MUTED": "#9099AD", "BORDER": "#282E40", "GREEN": "#7DDBB0", "RED": "#FF7E91",
    },
    "AMOLED": {
        "BG": "#050507", "SIDEBAR": "#09090D", "SURFACE": "#101014",
        "SURFACE_2": "#191920", "SURFACE_3": "#282832", "TEXT": "#F8F8FC",
        "MUTED": "#A1A1B1", "BORDER": "#262630", "GREEN": "#77E6B2", "RED": "#FF7D98",
    },
    "Graphite": {
        "BG": "#111318", "SIDEBAR": "#171A21", "SURFACE": "#1E222A",
        "SURFACE_2": "#282D37", "SURFACE_3": "#353C49", "TEXT": "#F2F4F8",
        "MUTED": "#A1A9B8", "BORDER": "#343A46", "GREEN": "#7DDBB0", "RED": "#FF8798",
    },
}
ACCENT_PRESETS = {
    "Фиолетовый": "#A99AFF",
    "Голубой": "#66D9EF",
    "Мятный": "#7DDBB0",
    "Розовый": "#FF86B7",
    "Оранжевый": "#FFB86B",
    "Синий": "#75A7FF",
}


def _ensure_update_config() -> None:
    """Create an editable GitHub release source config without overwriting user settings."""
    if UPDATE_CONFIG_FILE.exists():
        return
    default = {
        "github_owner": "",
        "github_repo": "",
        "asset_name": "Sanistra.exe",
    }
    try:
        UPDATE_CONFIG_FILE.write_text(json.dumps(default, indent=2), encoding="utf-8")
    except OSError:
        pass


def _version_tuple(value: str) -> tuple[int, ...]:
    numbers = [int(part) for part in re.findall(r"\d+", str(value))]
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers.pop()
    return tuple(numbers or [0])


def _read_update_config() -> dict[str, str]:
    _ensure_update_config()
    try:
        raw = json.loads(UPDATE_CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "github_owner": str(raw.get("github_owner", "")).strip(),
        "github_repo": str(raw.get("github_repo", "")).strip(),
        "asset_name": str(raw.get("asset_name", "Sanistra.exe")).strip() or "Sanistra.exe",
    }


def _resolve_update_source() -> tuple[str, str, str]:
    """Prefer a source baked into the release build; keep legacy config as a fallback."""
    bundled = str(UPDATE_REPOSITORY or "").strip()
    if bundled and not bundled.startswith("YOUR_GITHUB_") and "/" in bundled:
        owner, repo = bundled.split("/", 1)
        if re.fullmatch(r"[A-Za-z0-9_.-]+", owner) and re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
            return owner, repo, "Sanistra.exe"
    # Compatibility with a previously configured installation. Not required for normal users.
    config = _read_update_config()
    if config["github_owner"] and config["github_repo"]:
        return config["github_owner"], config["github_repo"], config["asset_name"]
    return "", "", "Sanistra.exe"


def _fetch_latest_github_release(owner: str, repo: str, asset_name: str) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
        raise ValueError("В update_config.json нужно указать корректные github_owner и github_repo.")
    api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    request = urllib.request.Request(
        api_url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Sanistra-Updater/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            release = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ValueError(
                "В репозитории yasikami/Sanistra пока нет опубликованных релизов. "
                "Когда появится первый GitHub Release с файлом Sanistra.exe, "
                "проверка и установка обновлений заработают автоматически."
            ) from exc
        if exc.code == 403 or exc.code == 429:
            raise ValueError(
                "GitHub временно ограничил запросы к API. Попробуй проверить обновления позже."
            ) from exc
        raise ValueError(f"GitHub API вернул HTTP {exc.code} при проверке обновлений.") from exc
    if not isinstance(release, dict) or not release.get("tag_name"):
        raise ValueError("GitHub не вернул информацию о последнем релизе.")
    assets = release.get("assets", [])
    asset = next((item for item in assets if str(item.get("name", "")).casefold() == asset_name.casefold()), None)
    if not asset:
        raise ValueError(f"В последнем релизе не найден файл {asset_name}. При публикации добавь его в Assets.")
    download_url = str(asset.get("browser_download_url", ""))
    parsed = urlparse(download_url)
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}:
        raise ValueError("GitHub вернул неожиданную ссылку на файл обновления. Загрузка отменена.")
    return {
        "version": str(release["tag_name"]).lstrip("vV"),
        "name": str(release.get("name") or release["tag_name"]),
        "body": str(release.get("body") or ""),
        "url": download_url,
        "digest": str(asset.get("digest") or ""),
        "size": int(asset.get("size") or 0),
    }


def _load_app_settings() -> dict[str, Any]:
    settings = dict(DEFAULT_APP_SETTINGS)
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            settings.update({key: raw[key] for key in DEFAULT_APP_SETTINGS if key in raw})
    except (OSError, ValueError, TypeError):
        pass
    if settings.get("theme") not in THEMES:
        settings["theme"] = DEFAULT_APP_SETTINGS["theme"]
    if not isinstance(settings.get("accent"), str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", settings["accent"]):
        settings["accent"] = DEFAULT_APP_SETTINGS["accent"]
    try:
        settings["scale"] = min(125, max(85, int(settings.get("scale", 100))))
    except (ValueError, TypeError):
        settings["scale"] = 100
    settings["compact_rows"] = bool(settings.get("compact_rows", False))
    settings["show_album"] = bool(settings.get("show_album", True))
    background = settings.get("background_image", "")
    settings["background_image"] = str(background) if isinstance(background, str) and background and Path(background).is_file() else ""
    try:
        settings["background_dim"] = min(85, max(0, int(settings.get("background_dim", 48))))
    except (ValueError, TypeError):
        settings["background_dim"] = 48
    return settings


def _brighten(hex_color: str, amount: float = 0.15) -> str:
    value = hex_color.lstrip("#")
    rgb = [int(value[i:i + 2], 16) for i in (0, 2, 4)]
    rgb = [round(c + (255 - c) * amount) for c in rgb]
    return "#%02X%02X%02X" % tuple(rgb)


def _apply_palette(settings: dict[str, Any]) -> None:
    global BG, SIDEBAR, SURFACE, SURFACE_2, SURFACE_3, TEXT, MUTED, ACCENT, ACCENT_HOVER, GREEN, RED, BORDER
    palette = THEMES.get(settings.get("theme", "Midnight"), THEMES["Midnight"])
    BG = palette["BG"]
    SIDEBAR = palette["SIDEBAR"]
    SURFACE = palette["SURFACE"]
    SURFACE_2 = palette["SURFACE_2"]
    SURFACE_3 = palette["SURFACE_3"]
    TEXT = palette["TEXT"]
    MUTED = palette["MUTED"]
    BORDER = palette["BORDER"]
    GREEN = palette["GREEN"]
    RED = palette["RED"]
    ACCENT = settings.get("accent", DEFAULT_APP_SETTINGS["accent"])
    ACCENT_HOVER = _brighten(ACCENT)


APP_SETTINGS = _load_app_settings()
_apply_palette(APP_SETTINGS)


def fmt_time(seconds: float | int | None) -> str:
    if not seconds or seconds < 0:
        return "0:00"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02}:{sec:02}" if h else f"{m}:{sec:02}"


def tags_for(path: str) -> dict[str, Any]:
    title = Path(path).stem
    artist = "Unknown artist"
    album = "Unknown album"
    duration = 0.0
    try:
        audio = MutagenFile(path, easy=True)
        if audio:
            def pick(tag: str, fallback: str) -> str:
                raw = audio.get(tag)
                if isinstance(raw, (list, tuple)) and raw:
                    return str(raw[0])
                return str(raw) if raw else fallback
            title = pick("title", title)
            artist = pick("artist", artist)
            album = pick("album", album)
            if audio.info and getattr(audio.info, "length", None):
                duration = float(audio.info.length)
    except Exception:
        pass
    return {"path": os.path.abspath(path), "title": title, "artist": artist, "album": album, "duration": duration}


class SanistraApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} · {APP_VERSION}")
        self.geometry("1220x790")
        self.minsize(960, 650)
        self.configure(fg_color=BG)
        self.ui_settings = dict(APP_SETTINGS)
        self.pending_accent = self.ui_settings["accent"]
        _ensure_update_config()
        self._update_check_running = False
        self._update_download_running = False
        self.update_status_label = None
        ctk.set_appearance_mode("dark")
        # PyInstaller builds must bundle customtkinter/assets. Keep a fallback so an
        # older/broken one-file build does not crash when dark-blue.json is absent.
        try:
            ctk.set_default_color_theme("dark-blue")
        except FileNotFoundError:
            try:
                ctk.set_default_color_theme("blue")
            except FileNotFoundError:
                # Custom widgets below have their own colours; CustomTkinter may already
                # have its default theme loaded during import.
                pass
        ctk.set_widget_scaling(self.ui_settings["scale"] / 100)
        ctk.set_window_scaling(self.ui_settings["scale"] / 100)

        try:
            pygame.mixer.init()
        except pygame.error as exc:
            messagebox.showerror("Ошибка аудиоустройства", f"Не удалось инициализировать аудиоустройство.\n\n{exc}")
            raise

        self.library: list[dict[str, Any]] = []
        self.favorites: set[str] = set()
        self.history: list[str] = []
        self.up_next: list[str] = []
        self.playlists: dict[str, list[str]] = {"My playlist": []}
        self.active_playlist = "My playlist"
        self.current_path: str | None = None
        self.current_duration = 0.0
        self.original_duration = 0.0
        self.duration_was_corrected = False
        self.duration_overrides: dict[str, float] = {}
        self.last_busy_position = 0.0
        self.position_base = 0.0
        self.started_at = 0.0
        self.playing = False
        self.paused = False
        self.shuffle = False
        self.repeat_mode = "all"  # all, one, off
        self.current_view = "Home"
        self.search_text = ""
        self.seek_dragging = False
        self.last_end_check = 0.0
        self.row_widgets: list[ctk.CTkFrame] = []
        self._loading_state = True
        self._search_after_id = None
        self._background_resize_after = None
        self._wallpaper_ctk_image = None
        self._mixer_position_anchor = 0.0
        self._last_valid_mixer_pos = 0.0
        self._use_mixer_clock = True

        self._load_state()
        self._build_layout()
        self.volume_var.set(self.volume)
        self._apply_volume(self.volume)
        self._render_view()
        self._refresh_player_bar()
        self._loading_state = False
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind_all("<space>", self._hotkey_space)
        self.bind_all("<Control-o>", lambda _e: self.add_files())
        self.bind_all("<Control-Shift-O>", lambda _e: self.add_folder())
        self.bind_all("<Control-f>", lambda _e: self.search_entry.focus_set())
        self.bind_all("<Control-Right>", lambda _e: self.next_track())
        self.bind_all("<Control-Left>", lambda _e: self.previous_track())
        self.bind_all("<Delete>", lambda _e: self.remove_current_from_library())
        self.after(250, self._tick)
        # Silently check for releases on startup when a repository is baked into the build.
        self.after(2400, lambda: self._check_for_updates(silent=True))

    # ---------- persistence ----------
    def _load_state(self):
        self.volume = 0.72
        if not STATE_FILE.exists():
            return
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            self.volume = float(data.get("volume", 0.72))
            raw_overrides = data.get("duration_overrides", {})
            if isinstance(raw_overrides, dict):
                for saved_path, saved_duration in raw_overrides.items():
                    try:
                        duration_value = float(saved_duration)
                        if duration_value > 0:
                            key = os.path.normcase(os.path.abspath(str(saved_path)))
                            self.duration_overrides[key] = duration_value
                    except (TypeError, ValueError, OSError):
                        continue
            self.shuffle = bool(data.get("shuffle", False))
            self.repeat_mode = data.get("repeat_mode", "all") if data.get("repeat_mode") in {"all", "one", "off"} else "all"
            self.favorites = set(data.get("favorites", []))
            self.history = list(data.get("history", []))[:100]
            self.playlists = {str(k): list(v) for k, v in data.get("playlists", {"My playlist": []}).items()}
            if not self.playlists:
                self.playlists = {"My playlist": []}
            self.active_playlist = data.get("active_playlist", next(iter(self.playlists)))
            if self.active_playlist not in self.playlists:
                self.active_playlist = next(iter(self.playlists))
            seen = set()
            for item in data.get("library", []):
                path = item.get("path", "")
                key = os.path.normcase(os.path.abspath(path)) if path else ""
                if path and os.path.isfile(path) and key not in seen and Path(path).suffix.lower() in SUPPORTED_EXTENSIONS:
                    seen.add(key)
                    track = tags_for(path)
                    override = self.duration_overrides.get(os.path.normcase(track["path"]))
                    if override is not None:
                        track["duration"] = override
                    self.library.append(track)
            valid = {x["path"] for x in self.library}
            self.duration_overrides = {k: v for k, v in self.duration_overrides.items() if k in {os.path.normcase(p) for p in valid}}
            self.favorites.intersection_update(valid)
            self.history = [p for p in self.history if p in valid]
            for name in list(self.playlists):
                self.playlists[name] = [p for p in self.playlists[name] if p in valid]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # Preserve the app launch even if a saved state file is malformed.
            self.library = []
            self.favorites = set()
            self.history = []
            self.playlists = {"My playlist": []}
            self.active_playlist = "My playlist"

    def _save_state(self):
        data = {
            "library": self.library,
            "favorites": sorted(self.favorites),
            "history": self.history[:100],
            "playlists": self.playlists,
            "active_playlist": self.active_playlist,
            "volume": self.volume,
            "shuffle": self.shuffle,
            "repeat_mode": self.repeat_mode,
            "duration_overrides": self.duration_overrides,
        }
        try:
            STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ---------- layout ----------
    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color=SIDEBAR, border_width=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_rowconfigure(10, weight=1)

        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=22, pady=(25, 31))
        logo = ctk.CTkFrame(brand, width=42, height=42, corner_radius=14, fg_color=ACCENT)
        logo.pack(side="left", padx=(0, 11))
        logo.pack_propagate(False)
        ctk.CTkLabel(logo, text="♫", text_color=BG, font=(FONT, 26, "bold")).pack(expand=True)
        ctk.CTkLabel(brand, text="SANISTRA", text_color=TEXT, font=(FONT, 20, "bold")).pack(anchor="w", pady=(2, 0))
        ctk.CTkLabel(brand, text=f"МУЗЫКАЛЬНЫЙ ПЛЕЕР · {APP_VERSION}", text_color=MUTED, font=(FONT, 9, "bold")).pack(anchor="w")

        ctk.CTkLabel(self.sidebar, text="БИБЛИОТЕКА", text_color="#70798D", font=(FONT, 10, "bold")).pack(anchor="w", padx=24, pady=(0, 8))
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for key, label, icon in [
            ("Home", "Главная", "⌂"),
            ("All songs", "Все треки", "♫"),
            ("Favorites", "Избранное", "♡"),
            ("Recently played", "Недавно прослушано", "◷"),
            ("Settings", "Настройки", "⚙"),
        ]:
            btn = ctk.CTkButton(self.sidebar, text=f"{icon}    {label}", anchor="w", height=42, corner_radius=10,
                                fg_color="transparent", hover_color=SURFACE_2, text_color=MUTED,
                                font=(FONT, 13), command=lambda v=key: self.navigate(v))
            btn.pack(fill="x", padx=12, pady=2)
            self.nav_buttons[key] = btn

        ctk.CTkLabel(self.sidebar, text="МОИ ПЛЕЙЛИСТЫ", text_color="#70798D", font=(FONT, 10, "bold")).pack(anchor="w", padx=24, pady=(27, 8))
        self.playlist_nav = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.playlist_nav.pack(fill="x", padx=12)
        self._draw_playlist_nav()
        ctk.CTkButton(self.sidebar, text="＋   Новый плейлист", anchor="w", height=38, corner_radius=9,
                      fg_color="transparent", hover_color=SURFACE_2, text_color=ACCENT,
                      font=(FONT, 12, "bold"), command=self.create_playlist).pack(fill="x", padx=12, pady=(8, 4))

        side_bottom = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        side_bottom.pack(side="bottom", fill="x", padx=17, pady=18)
        ctk.CTkFrame(side_bottom, height=1, fg_color=BORDER).pack(fill="x", pady=(0, 15))
        ctk.CTkLabel(side_bottom, text="ТВОЯ МУЗЫКА — ТВОЁ ПРОСТРАНСТВО", text_color="#6F788C", font=(FONT, 9, "bold")).pack(anchor="w")
        ctk.CTkLabel(side_bottom, text="Локальная музыка · Без аккаунта", text_color=MUTED, font=(FONT, 10)).pack(anchor="w", pady=(4, 0))

        self.main = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_rowconfigure(2, weight=1)
        self.main.grid_columnconfigure(0, weight=1)
        # Wallpaper is placed first, behind the interface; its image is resized after the window settles.
        self.main_bg_label = ctk.CTkLabel(self.main, text="", fg_color="transparent")
        self.main_bg_label.place(x=0, y=0, relwidth=1, relheight=1)
        self.main_bg_label.lower()
        self.main.bind("<Configure>", self._schedule_background_refresh, add="+")

        topbar = ctk.CTkFrame(self.main, fg_color="transparent")
        topbar.grid(row=0, column=0, sticky="ew", padx=30, pady=(23, 15))
        topbar.grid_columnconfigure(1, weight=1)
        self.view_title = ctk.CTkLabel(topbar, text="Привет!", font=(FONT, 22, "bold"), text_color=TEXT)
        self.view_title.grid(row=0, column=0, sticky="w")
        self.search_entry = ctk.CTkEntry(topbar, width=280, height=38, corner_radius=12,
                                         placeholder_text="⌕   Поиск треков, исполнителей, альбомов…",
                                         fg_color=SURFACE, border_color=BORDER, text_color=TEXT,
                                         placeholder_text_color=MUTED, font=(FONT, 12))
        self.search_entry.grid(row=0, column=2, sticky="e", padx=(20, 0))
        self.search_entry.bind("<KeyRelease>", self._on_search)
        self.add_top_button = ctk.CTkButton(topbar, text="＋  Добавить музыку", height=38, corner_radius=11,
                                            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=BG,
                                            font=(FONT, 12, "bold"), command=self.add_files)
        self.add_top_button.grid(row=0, column=3, sticky="e", padx=(10, 0))

        self.content = ctk.CTkScrollableFrame(self.main, fg_color="transparent", corner_radius=0,
                                              scrollbar_button_color=SURFACE_3, scrollbar_button_hover_color=ACCENT)
        self.content.grid(row=2, column=0, sticky="nsew", padx=25, pady=(0, 10))

        self.player_bar = ctk.CTkFrame(self.main, fg_color=SURFACE, corner_radius=0, border_width=1, border_color=BORDER, height=105)
        self.player_bar.grid(row=3, column=0, sticky="ew")
        self.player_bar.grid_columnconfigure(1, weight=1)
        self._build_player_bar()

    def _draw_playlist_nav(self):
        for child in self.playlist_nav.winfo_children():
            child.destroy()
        for name in self.playlists:
            btn = ctk.CTkButton(self.playlist_nav, text=f"▤    {name}", anchor="w", height=36, corner_radius=9,
                                fg_color=SURFACE_2 if self.current_view == f"Playlist:{name}" else "transparent",
                                hover_color=SURFACE_2, text_color=TEXT if self.current_view == f"Playlist:{name}" else MUTED,
                                font=(FONT, 12), command=lambda n=name: self.navigate(f"Playlist:{n}"))
            btn.pack(fill="x", pady=1)

    def _build_player_bar(self):
        left = ctk.CTkFrame(self.player_bar, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w", padx=(22, 13), pady=12)
        self.mini_cover = ctk.CTkFrame(left, width=58, height=58, corner_radius=11, fg_color="#302A4A")
        self.mini_cover.pack(side="left", padx=(0, 11))
        self.mini_cover.pack_propagate(False)
        ctk.CTkLabel(self.mini_cover, text="♫", text_color=ACCENT, font=(FONT, 26, "bold")).pack(expand=True)
        meta = ctk.CTkFrame(left, fg_color="transparent", width=170)
        meta.pack(side="left", fill="y")
        meta.pack_propagate(False)
        self.bar_title = ctk.CTkLabel(meta, text="Ничего не играет", text_color=TEXT, font=(FONT, 12, "bold"), anchor="w")
        self.bar_title.pack(fill="x", pady=(9, 1))
        self.bar_artist = ctk.CTkLabel(meta, text="Выбери песню для начала", text_color=MUTED, font=(FONT, 10), anchor="w")
        self.bar_artist.pack(fill="x")

        center = ctk.CTkFrame(self.player_bar, fg_color="transparent")
        center.grid(row=0, column=1, sticky="ew", padx=12, pady=(10, 7))
        center.grid_columnconfigure(0, weight=1)
        controls = ctk.CTkFrame(center, fg_color="transparent")
        controls.grid(row=0, column=0, pady=(0, 3))
        self.shuffle_btn = ctk.CTkButton(controls, text="⤨", width=34, height=30, fg_color="transparent", hover_color=SURFACE_2,
                                         text_color=ACCENT if self.shuffle else MUTED, font=(FONT, 18), command=self.toggle_shuffle)
        self.shuffle_btn.grid(row=0, column=0, padx=5)
        ctk.CTkButton(controls, text="⏮", width=36, height=31, fg_color="transparent", hover_color=SURFACE_2,
                      text_color=TEXT, font=(FONT, 17), command=self.previous_track).grid(row=0, column=1, padx=3)
        self.play_btn = ctk.CTkButton(controls, text="▶", width=43, height=43, corner_radius=22, fg_color=ACCENT,
                                      hover_color=ACCENT_HOVER, text_color=BG, font=(FONT, 17, "bold"), command=self.toggle_play)
        self.play_btn.grid(row=0, column=2, padx=8)
        ctk.CTkButton(controls, text="⏭", width=36, height=31, fg_color="transparent", hover_color=SURFACE_2,
                      text_color=TEXT, font=(FONT, 17), command=self.next_track).grid(row=0, column=3, padx=3)
        self.repeat_btn = ctk.CTkButton(controls, text="⟳", width=34, height=30, fg_color="transparent", hover_color=SURFACE_2,
                                        text_color=ACCENT if self.repeat_mode != "off" else MUTED, font=(FONT, 18), command=self.toggle_repeat)
        self.repeat_btn.grid(row=0, column=4, padx=5)

        seek_row = ctk.CTkFrame(center, fg_color="transparent")
        seek_row.grid(row=1, column=0, sticky="ew")
        self.elapsed = ctk.CTkLabel(seek_row, text="0:00", width=42, text_color=MUTED, font=(FONT, 9))
        self.elapsed.pack(side="left")
        self.seek_var = tk.DoubleVar(value=0)
        self.seek = ctk.CTkSlider(seek_row, from_=0, to=100, variable=self.seek_var, height=14,
                                  progress_color=ACCENT, button_color=ACCENT, button_hover_color=ACCENT_HOVER,
                                  fg_color=SURFACE_3, command=self._seek_changed)
        self.seek.pack(side="left", fill="x", expand=True, padx=8)
        self.seek.bind("<ButtonPress-1>", self._seek_press)
        self.seek.bind("<ButtonRelease-1>", self._seek_release)
        self.total = ctk.CTkLabel(seek_row, text="0:00", width=42, text_color=MUTED, font=(FONT, 9))
        self.total.pack(side="right")

        right = ctk.CTkFrame(self.player_bar, fg_color="transparent")
        right.grid(row=0, column=2, sticky="e", padx=(10, 23), pady=15)
        self.like_btn = ctk.CTkButton(right, text="♡", width=32, height=32, fg_color="transparent", hover_color=SURFACE_2,
                                      text_color=MUTED, font=(FONT, 21), command=self.toggle_current_favorite)
        self.like_btn.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(right, text="ГРОМКОСТЬ", text_color=MUTED, font=(FONT, 9, "bold")).pack(anchor="w")
        self.volume_var = tk.DoubleVar(value=72)
        self.volume_slider = ctk.CTkSlider(right, from_=0, to=100, width=100, height=14, variable=self.volume_var,
                                            progress_color=ACCENT, button_color=ACCENT, button_hover_color=ACCENT_HOVER,
                                            fg_color=SURFACE_3, command=self._on_volume)
        self.volume_slider.pack()

    # ---------- view navigation and rendering ----------
    def navigate(self, view: str):
        self.current_view = view
        self._draw_playlist_nav()
        for name, btn in self.nav_buttons.items():
            active = name == view
            btn.configure(fg_color=SURFACE_2 if active else "transparent", text_color=TEXT if active else MUTED)
        self._render_view()

    def _on_search(self, _event=None):
        # Debounce typing to avoid rebuilding the whole view for every keystroke.
        if self._search_after_id is not None:
            try:
                self.after_cancel(self._search_after_id)
            except tk.TclError:
                pass
        self._search_after_id = self.after(160, self._apply_search)

    def _apply_search(self):
        self._search_after_id = None
        self.search_text = self.search_entry.get().strip().casefold()
        if self.current_view != "Settings":
            self._render_view()

    def _visible_tracks(self) -> list[dict[str, Any]]:
        if self.current_view == "Favorites":
            tracks = [x for x in self.library if x["path"] in self.favorites]
        elif self.current_view == "Recently played":
            recent_paths = list(dict.fromkeys(self.history))
            by_path = {x["path"]: x for x in self.library}
            tracks = [by_path[p] for p in recent_paths if p in by_path]
        elif self.current_view.startswith("Playlist:"):
            name = self.current_view.split(":", 1)[1]
            paths = self.playlists.get(name, [])
            by_path = {x["path"]: x for x in self.library}
            tracks = [by_path[p] for p in paths if p in by_path]
        else:
            tracks = list(self.library)
        if self.search_text:
            tracks = [x for x in tracks if self.search_text in " ".join((x["title"], x["artist"], x["album"], x["path"])).casefold()]
        return tracks

    def _render_view(self):
        if not hasattr(self, "content"):
            return
        for child in self.content.winfo_children():
            child.destroy()
        self.row_widgets.clear()
        view = self.current_view
        if view == "Home":
            self.view_title.configure(text="Главная")
            self._render_hero()
            self._render_quick_actions()
            self._render_track_section(self._home_tracks(), "Твоя музыка", show_all_link=True)
        elif view == "All songs":
            self.view_title.configure(text="Все треки")
            self._render_library_header(f"Треков в медиатеке: {len(self.library)}")
            self._render_track_section(self._visible_tracks(), "Все композиции", show_all_link=False)
        elif view == "Favorites":
            self.view_title.configure(text="Избранное")
            self._render_library_header(f"В избранном: {len(self.favorites)}")
            self._render_track_section(self._visible_tracks(), "Избранные треки", show_all_link=False)
        elif view == "Recently played":
            self.view_title.configure(text="Недавно прослушано")
            self._render_library_header("Треки, которые ты слушал недавно")
            self._render_track_section(self._visible_tracks(), "История прослушивания", show_all_link=False)
        elif view.startswith("Playlist:"):
            name = view.split(":", 1)[1]
            self.view_title.configure(text=name)
            self._render_playlist_header(name)
            self._render_track_section(self._visible_tracks(), name, show_all_link=False)
        elif view == "Settings":
            self.view_title.configure(text="Настройки")
            self._render_settings()
        self._draw_playlist_nav()

    def _render_hero(self):
        has_wallpaper = bool(self.ui_settings.get("background_image")) and Path(str(self.ui_settings.get("background_image"))).is_file()
        hero = ctk.CTkFrame(self.content, fg_color="transparent" if has_wallpaper else "#24203A", corner_radius=22, height=200, border_width=1, border_color="#393151")
        hero.pack(fill="x", pady=(0, 22))
        hero.pack_propagate(False)
        if has_wallpaper:
            try:
                with Image.open(str(self.ui_settings["background_image"])) as source:
                    hero_image = ImageOps.fit(source.convert("RGB"), (900, 200), method=Image.Resampling.LANCZOS)
                dim = int(self.ui_settings.get("background_dim", 48))
                bg_rgb = tuple(int(BG[i:i+2], 16) for i in (1, 3, 5))
                hero_image = Image.blend(hero_image, Image.new("RGB", hero_image.size, bg_rgb), dim / 100.0)
                self._hero_wallpaper_image = ctk.CTkImage(light_image=hero_image, dark_image=hero_image, size=(900, 200))
                hero_bg = ctk.CTkLabel(hero, text="", image=self._hero_wallpaper_image, fg_color="transparent")
                hero_bg.place(x=0, y=0, relwidth=1, relheight=1)
                hero_bg.lower()
            except Exception:
                self._hero_wallpaper_image = None
        left = ctk.CTkFrame(hero, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=27, pady=23)
        ctk.CTkLabel(left, text="ТВОЯ МЕДИАТЕКА", text_color=ACCENT, font=(FONT, 10, "bold")).pack(anchor="w")
        ctk.CTkLabel(left, text="Включай\nсвоё любимое.", text_color=TEXT, font=(FONT, 28, "bold"), justify="left").pack(anchor="w", pady=(8, 7))
        ctk.CTkLabel(left, text="Треки, альбомы и плейлисты.", text_color="#C3BDD9", font=(FONT, 12)).pack(anchor="w")
        actions = ctk.CTkFrame(left, fg_color="transparent")
        actions.pack(anchor="w", pady=(14, 0))
        ctk.CTkButton(actions, text="＋  Добавить музыку", height=34, corner_radius=10, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, text_color=BG, font=(FONT, 11, "bold"), command=self.add_files).pack(side="left", padx=(0, 8))
        ctk.CTkButton(actions, text="Открыть библиотеку  →", height=34, corner_radius=10, fg_color="#39334F",
                      hover_color="#48405F", text_color=TEXT, font=(FONT, 11, "bold"), command=lambda: self.navigate("All songs")).pack(side="left")
        art = ctk.CTkCanvas(hero, width=200, height=180, bg="#24203A", highlightthickness=0)
        art.pack(side="right", padx=20, pady=10)
        art.create_oval(29, 18, 180, 169, fill="#413860", outline="")
        art.create_oval(48, 37, 161, 150, fill="#65568B", outline="")
        art.create_oval(67, 56, 142, 131, fill=ACCENT, outline="")
        art.create_oval(90, 79, 119, 108, fill="#302943", outline="")
        art.create_arc(51, 39, 160, 149, start=210, extent=110, style="arc", outline="#E4DDFF", width=4)

    def _render_quick_actions(self):
        actions = ctk.CTkFrame(self.content, fg_color="transparent")
        actions.pack(fill="x", pady=(0, 19))
        cards = [
            ("♡", "Favorites", "Треки, которые нравятся", "#30243A", lambda: self.navigate("Favorites")),
            ("◷", "Recently played", "Вернись к прослушиванию", "#1C3440", lambda: self.navigate("Recently played")),
            ("▤", "Твои плейлисты", "Собери музыку под настроение", "#26334B", self.create_playlist),
        ]
        for icon, title, subtitle, color, command in cards:
            card = ctk.CTkFrame(actions, fg_color=SURFACE, corner_radius=15, border_width=1, border_color=BORDER)
            card.pack(side="left", fill="x", expand=True, padx=(0, 10))
            ctk.CTkButton(card, text=icon, width=40, height=40, corner_radius=12, fg_color=color,
                          hover_color=color, text_color=ACCENT, font=(FONT, 22), command=command).pack(anchor="w", padx=14, pady=(14, 9))
            ctk.CTkLabel(card, text=title, text_color=TEXT, font=(FONT, 13, "bold")).pack(anchor="w", padx=15)
            ctk.CTkLabel(card, text=subtitle, text_color=MUTED, font=(FONT, 10)).pack(anchor="w", padx=15, pady=(4, 15))

    def _render_library_header(self, subtitle: str):
        frame = ctk.CTkFrame(self.content, fg_color=SURFACE, corner_radius=16, border_width=1, border_color=BORDER)
        frame.pack(fill="x", pady=(0, 18))
        ctk.CTkLabel(frame, text=subtitle, text_color=MUTED, font=(FONT, 12)).pack(side="left", padx=18, pady=15)
        ctk.CTkButton(frame, text="＋ Добавить папку", height=32, corner_radius=9, fg_color=SURFACE_2,
                      hover_color=SURFACE_3, text_color=TEXT, font=(FONT, 11), command=self.add_folder).pack(side="right", padx=10, pady=9)
        ctk.CTkButton(frame, text="Открыть M3U", height=32, corner_radius=9, fg_color=SURFACE_2,
                      hover_color=SURFACE_3, text_color=TEXT, font=(FONT, 11), command=self.open_m3u).pack(side="right", pady=9)

    def _render_playlist_header(self, name: str):
        frame = ctk.CTkFrame(self.content, fg_color="#24203A", corner_radius=16, border_width=1, border_color="#393151")
        frame.pack(fill="x", pady=(0, 18))
        ctk.CTkLabel(frame, text="▤", text_color=ACCENT, font=(FONT, 32, "bold")).pack(side="left", padx=(19, 12), pady=12)
        details = ctk.CTkFrame(frame, fg_color="transparent")
        details.pack(side="left", pady=12)
        ctk.CTkLabel(details, text=name, text_color=TEXT, font=(FONT, 16, "bold")).pack(anchor="w")
        ctk.CTkLabel(details, text=f"{len(self.playlists.get(name, []))} треков · Твоя коллекция", text_color="#C3BDD9", font=(FONT, 10)).pack(anchor="w", pady=(3, 0))
        ctk.CTkButton(frame, text="Экспорт M3U", height=32, corner_radius=9, fg_color="#39334F", hover_color="#48405F",
                      text_color=TEXT, font=(FONT, 11), command=lambda: self.save_m3u(name)).pack(side="right", padx=15)
        ctk.CTkButton(frame, text="Переименовать", height=32, corner_radius=9, fg_color="#39334F", hover_color="#48405F",
                      text_color=TEXT, font=(FONT, 11), command=lambda: self.rename_playlist(name)).pack(side="right", padx=(0, 0))

    # ---------- wallpaper customization ----------
    def _schedule_background_refresh(self, _event=None):
        if self._background_resize_after is not None:
            try:
                self.after_cancel(self._background_resize_after)
            except tk.TclError:
                pass
        self._background_resize_after = self.after(180, self._refresh_background_image)

    def _refresh_background_image(self):
        self._background_resize_after = None
        if not hasattr(self, "main_bg_label") or not self.main_bg_label.winfo_exists():
            return
        path = str(self.ui_settings.get("background_image", "") or "")
        if not path or not Path(path).is_file():
            self._wallpaper_ctk_image = None
            try:
                self.main_bg_label.configure(image=None, text="")
            except (tk.TclError, AttributeError):
                pass
            return
        try:
            width = max(500, self.main.winfo_width())
            height = max(400, self.main.winfo_height())
            with Image.open(path) as source:
                image = ImageOps.fit(source.convert("RGB"), (width, height), method=Image.Resampling.LANCZOS)
            # Blend the chosen image with the current theme background for readable controls.
            dim = int(self.ui_settings.get("background_dim", 48))
            bg_rgb = tuple(int(BG[i:i+2], 16) for i in (1, 3, 5))
            shade = Image.new("RGB", image.size, bg_rgb)
            image = Image.blend(image, shade, dim / 100.0)
            self._wallpaper_ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=(width, height))
            self.main_bg_label.configure(image=self._wallpaper_ctk_image, text="")
            self.main_bg_label.lower()
        except Exception as exc:
            try:
                self.main_bg_label.configure(image=None, text="")
            except Exception:
                pass
            self._wallpaper_ctk_image = None
            self._set_update_status(f"Фон не удалось загрузить: {exc}")

    def _choose_background_image(self):
        selected = filedialog.askopenfilename(
            parent=self,
            title="Выбери фоновое изображение",
            filetypes=[("Изображения", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Все файлы", "*.*")],
        )
        if not selected:
            return
        try:
            # Copy into persistent app data so the wallpaper won't break if the original is moved.
            with Image.open(selected) as check:
                check.verify()
            suffix = Path(selected).suffix.lower()
            if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                suffix = ".png"
            destination = DATA_DIR / ("custom_background" + suffix)
            if Path(selected).resolve() != destination.resolve():
                shutil.copy2(selected, destination)
            self.background_var.set(str(destination))
            self.background_status.configure(text=f"Выбрано: {destination.name}")
        except Exception as exc:
            messagebox.showerror("Фоновое изображение", f"Не удалось открыть или скопировать изображение.\n\n{exc}", parent=self)

    def _clear_background_image(self):
        self.background_var.set("")
        self.background_status.configure(text="Используется фон выбранной темы")

    def _render_settings(self):
        intro = ctk.CTkFrame(self.content, fg_color=SURFACE, corner_radius=18, border_width=1, border_color=BORDER)
        intro.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(intro, text="Персонализация", text_color=TEXT, font=(FONT, 20, "bold")).pack(anchor="w", padx=22, pady=(18, 4))
        ctk.CTkLabel(intro, text="Настрой цвета, фон и плотность интерфейса. Настройки применяются сразу — перезапуск не нужен.",
                     text_color=MUTED, font=(FONT, 11), wraplength=680, justify="left").pack(anchor="w", padx=22, pady=(0, 18))

        appearance = ctk.CTkFrame(self.content, fg_color=SURFACE, corner_radius=16, border_width=1, border_color=BORDER)
        appearance.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(appearance, text="Внешний вид", text_color=TEXT, font=(FONT, 15, "bold")).pack(anchor="w", padx=20, pady=(17, 13))

        theme_row = ctk.CTkFrame(appearance, fg_color="transparent")
        theme_row.pack(fill="x", padx=20, pady=(0, 12))
        ctk.CTkLabel(theme_row, text="Цветовая тема", text_color=TEXT, font=(FONT, 12)).pack(side="left")
        self.theme_var = tk.StringVar(value=self.ui_settings.get("theme", "Midnight"))
        ctk.CTkOptionMenu(theme_row, values=list(THEMES.keys()), variable=self.theme_var, width=170,
                          fg_color=SURFACE_2, button_color=ACCENT, button_hover_color=ACCENT_HOVER,
                          text_color=TEXT, dropdown_fg_color=SURFACE, dropdown_text_color=TEXT).pack(side="right")

        ctk.CTkLabel(appearance, text="Цвет акцента", text_color=TEXT, font=(FONT, 12)).pack(anchor="w", padx=20, pady=(4, 8))
        self.accent_swatch_frame = ctk.CTkFrame(appearance, fg_color="transparent")
        self.accent_swatch_frame.pack(fill="x", padx=16, pady=(0, 8))
        self.accent_buttons = {}
        for color_name, color_value in ACCENT_PRESETS.items():
            selected = self.pending_accent.upper() == color_value.upper()
            button = ctk.CTkButton(self.accent_swatch_frame, text="●", width=35, height=34, corner_radius=12,
                                   fg_color=color_value, hover_color=_brighten(color_value, 0.22),
                                   text_color=BG, border_width=3 if selected else 0,
                                   border_color=TEXT, command=lambda c=color_value: self._choose_accent(c))
            button.pack(side="left", padx=4, pady=3)
            self.accent_buttons[color_value] = button
        custom_row = ctk.CTkFrame(appearance, fg_color="transparent")
        custom_row.pack(fill="x", padx=20, pady=(0, 17))
        self.accent_preview = ctk.CTkFrame(custom_row, width=22, height=22, corner_radius=7, fg_color=self.pending_accent)
        self.accent_preview.pack(side="left", padx=(0, 9))
        self.accent_preview.pack_propagate(False)
        self.accent_status = ctk.CTkLabel(custom_row, text=f"Выбран: {self.pending_accent.upper()}", text_color=MUTED, font=(FONT, 10))
        self.accent_status.pack(side="left")
        ctk.CTkButton(custom_row, text="Свой цвет…", width=112, height=31, corner_radius=9, fg_color=SURFACE_2,
                      hover_color=SURFACE_3, text_color=TEXT, font=(FONT, 11), command=self._choose_custom_accent).pack(side="right")

        wallpaper = ctk.CTkFrame(self.content, fg_color=SURFACE, corner_radius=16, border_width=1, border_color=BORDER)
        wallpaper.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(wallpaper, text="Фоновое изображение", text_color=TEXT, font=(FONT, 15, "bold")).pack(anchor="w", padx=20, pady=(17, 6))
        ctk.CTkLabel(wallpaper, text="Выбери собственную картинку для основной области приложения. Она копируется в папку настроек, поэтому исходный файл можно переместить.",
                     text_color=MUTED, font=(FONT, 10), wraplength=760, justify="left").pack(anchor="w", padx=20, pady=(0, 10))
        self.background_var = tk.StringVar(value=str(self.ui_settings.get("background_image", "") or ""))
        background_actions = ctk.CTkFrame(wallpaper, fg_color="transparent")
        background_actions.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkButton(background_actions, text="Выбрать изображение…", height=34, corner_radius=9,
                      fg_color=SURFACE_2, hover_color=SURFACE_3, text_color=TEXT, font=(FONT, 11),
                      command=self._choose_background_image).pack(side="left", padx=4)
        ctk.CTkButton(background_actions, text="Убрать фон", height=34, corner_radius=9,
                      fg_color=SURFACE_2, hover_color=SURFACE_3, text_color=TEXT, font=(FONT, 11),
                      command=self._clear_background_image).pack(side="left", padx=4)
        background_path = self.background_var.get()
        background_label = Path(background_path).name if background_path else "Используется фон выбранной темы"
        self.background_status = ctk.CTkLabel(wallpaper, text=background_label, text_color=MUTED, font=(FONT, 10), anchor="w")
        self.background_status.pack(fill="x", padx=20, pady=(0, 10))
        dim_row = ctk.CTkFrame(wallpaper, fg_color="transparent")
        dim_row.pack(fill="x", padx=20, pady=(0, 17))
        ctk.CTkLabel(dim_row, text="Затемнение картинки для читаемости", text_color=TEXT, font=(FONT, 12)).pack(side="left")
        self.background_dim_var = tk.IntVar(value=int(self.ui_settings.get("background_dim", 48)))
        ctk.CTkSlider(dim_row, from_=0, to=85, number_of_steps=17, variable=self.background_dim_var,
                      width=180, height=14, progress_color=ACCENT, button_color=ACCENT,
                      button_hover_color=ACCENT_HOVER, fg_color=SURFACE_3).pack(side="right", padx=(10, 0))

        layout = ctk.CTkFrame(self.content, fg_color=SURFACE, corner_radius=16, border_width=1, border_color=BORDER)
        layout.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(layout, text="Интерфейс", text_color=TEXT, font=(FONT, 15, "bold")).pack(anchor="w", padx=20, pady=(17, 13))

        scale_row = ctk.CTkFrame(layout, fg_color="transparent")
        scale_row.pack(fill="x", padx=20, pady=(0, 13))
        ctk.CTkLabel(scale_row, text="Масштаб интерфейса", text_color=TEXT, font=(FONT, 12)).pack(side="left")
        self.scale_var = tk.StringVar(value=f"{self.ui_settings.get('scale', 100)}%")
        ctk.CTkOptionMenu(scale_row, values=["85%", "90%", "100%", "110%", "115%", "120%", "125%"],
                          variable=self.scale_var, width=110, fg_color=SURFACE_2, button_color=ACCENT,
                          button_hover_color=ACCENT_HOVER, text_color=TEXT, dropdown_fg_color=SURFACE,
                          dropdown_text_color=TEXT).pack(side="right")

        self.compact_var = tk.BooleanVar(value=self.ui_settings.get("compact_rows", False))
        compact_row = ctk.CTkFrame(layout, fg_color="transparent")
        compact_row.pack(fill="x", padx=20, pady=(0, 13))
        ctk.CTkLabel(compact_row, text="Компактный список треков", text_color=TEXT, font=(FONT, 12)).pack(side="left")
        ctk.CTkSwitch(compact_row, text="", variable=self.compact_var, onvalue=True, offvalue=False,
                      progress_color=ACCENT, button_color=TEXT, button_hover_color=ACCENT_HOVER).pack(side="right")

        self.album_var = tk.BooleanVar(value=self.ui_settings.get("show_album", True))
        album_row = ctk.CTkFrame(layout, fg_color="transparent")
        album_row.pack(fill="x", padx=20, pady=(0, 17))
        ctk.CTkLabel(album_row, text="Показывать колонку альбома", text_color=TEXT, font=(FONT, 12)).pack(side="left")
        ctk.CTkSwitch(album_row, text="", variable=self.album_var, onvalue=True, offvalue=False,
                      progress_color=ACCENT, button_color=TEXT, button_hover_color=ACCENT_HOVER).pack(side="right")

        shortcuts = ctk.CTkFrame(self.content, fg_color=SURFACE, corner_radius=16, border_width=1, border_color=BORDER)
        shortcuts.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(shortcuts, text="Горячие клавиши", text_color=TEXT, font=(FONT, 15, "bold")).pack(anchor="w", padx=20, pady=(16, 8))
        ctk.CTkLabel(shortcuts, text="Пробел — пауза/воспроизведение     Ctrl+O — добавить файлы     Ctrl+F — поиск\nCtrl+← / Ctrl+→ — предыдущий / следующий трек     Delete — убрать текущий трек из медиатеки",
                     text_color=MUTED, font=(FONT, 10), justify="left", wraplength=760).pack(anchor="w", padx=20, pady=(0, 16))

        updates = ctk.CTkFrame(self.content, fg_color=SURFACE, corner_radius=16, border_width=1, border_color=BORDER)
        updates.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(updates, text="Онлайн-обновления", text_color=TEXT, font=(FONT, 15, "bold")).pack(anchor="w", padx=20, pady=(16, 5))
        ctk.CTkLabel(updates, text="Sanistra может сама проверять GitHub Releases при запуске. Адрес источника встраивается разработчиком в сборку — пользователю не нужно указывать репозиторий в настройках.",
                     text_color=MUTED, font=(FONT, 10), wraplength=760, justify="left").pack(anchor="w", padx=20, pady=(0, 10))
        update_actions = ctk.CTkFrame(updates, fg_color="transparent")
        update_actions.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkButton(update_actions, text="Проверить сейчас", height=34, corner_radius=9,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=BG, font=(FONT, 11, "bold"),
                      command=self._check_for_updates).pack(side="left", padx=4)
        self.update_status_label = ctk.CTkLabel(updates, text=f"Текущая версия: {APP_VERSION}", text_color=MUTED, font=(FONT, 10), anchor="w")
        self.update_status_label.pack(anchor="w", padx=20, pady=(0, 14))

        actions = ctk.CTkFrame(self.content, fg_color="transparent")
        actions.pack(fill="x", pady=(0, 20))
        ctk.CTkButton(actions, text="Применить настройки", height=40, corner_radius=11,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=BG, font=(FONT, 12, "bold"),
                      command=self._save_settings_and_restart).pack(side="left")
        ctk.CTkButton(actions, text="Сбросить настройки", height=40, corner_radius=11,
                      fg_color=SURFACE_2, hover_color=SURFACE_3, text_color=TEXT, font=(FONT, 11),
                      command=self._reset_settings_form).pack(side="left", padx=10)
        ctk.CTkLabel(actions, text="Библиотека и плейлисты хранятся отдельно от программы.", text_color=MUTED,
                     font=(FONT, 10), wraplength=250, justify="right").pack(side="right", padx=(8, 0))

    def _set_update_status(self, text: str):
        if self.update_status_label is not None and self.update_status_label.winfo_exists():
            self.update_status_label.configure(text=text)

    def _configure_update_source(self):
        _ensure_update_config()
        try:
            if os.name == "nt":
                subprocess.Popen(["notepad.exe", str(UPDATE_CONFIG_FILE)])
            else:
                subprocess.Popen(["xdg-open", str(UPDATE_CONFIG_FILE)])
            messagebox.showinfo(
                "Источник обновлений",
                "В открывшемся JSON-файле укажи github_owner (имя пользователя/организации GitHub) и github_repo (название публичного репозитория).\n\n"
                "В опубликованный GitHub Release загружай Sanistra.exe как файл Assets.\n"
                f"Файл настроек: {UPDATE_CONFIG_FILE}", parent=self,
            )
        except OSError as exc:
            messagebox.showerror("Не удалось открыть настройки", f"Открой этот файл вручную:\n{UPDATE_CONFIG_FILE}\n\n{exc}", parent=self)

    def _check_for_updates(self, silent: bool = False):
        if self._update_check_running or self._update_download_running:
            return
        owner, repo, asset_name = _resolve_update_source()
        if not owner or not repo:
            self._set_update_status("Источник обновлений будет встроен в опубликованную сборку.")
            if not silent:
                messagebox.showinfo(
                    "Автообновление пока не подключено",
                    "Чтобы Sanistra сама находила новые версии, разработчик один раз указывает свой публичный GitHub-репозиторий в сборке. Пользователю не потребуется вводить его в приложении.",
                    parent=self,
                )
            return
        self._update_check_running = True
        self._set_update_status("Проверка последнего релиза GitHub…")
        def worker():
            try:
                result = _fetch_latest_github_release(owner, repo, asset_name)
                result["error"] = ""
            except Exception as exc:
                result = {"error": str(exc)}
            try:
                self.after(0, lambda result=result, silent=silent: self._on_update_checked(result, silent=silent))
            except tk.TclError:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _on_update_checked(self, result: dict[str, Any], silent: bool = False):
        self._update_check_running = False
        if result.get("error"):
            self._set_update_status("Не удалось проверить обновления")
            if not silent:
                messagebox.showerror("Ошибка проверки обновлений", str(result["error"]), parent=self)
            return
        remote_version = str(result.get("version", "0"))
        if _version_tuple(remote_version) <= _version_tuple(APP_VERSION):
            self._set_update_status(f"Установлена актуальная версия: {APP_VERSION}")
            if not silent:
                messagebox.showinfo("Обновления", f"У тебя актуальная версия Sanistra {APP_VERSION}. Последний опубликованный релиз: {remote_version}.", parent=self)
            return
        release_notes = str(result.get("body", "")).strip()
        prompt = f"Доступна Sanistra {remote_version}. Установленная версия: {APP_VERSION}.\n\nСкачать и установить обновление?"
        if release_notes:
            prompt += "\n\nПримечания к релизу:\n" + release_notes[:1200]
        if messagebox.askyesno("Доступно обновление", prompt, parent=self):
            if not getattr(sys, "frozen", False):
                messagebox.showinfo("Нужна сборка EXE", "Автоматическая замена поддерживается в собранной версии Sanistra.exe. Сейчас приложение запущено из player.py; собери EXE через build_exe.bat.", parent=self)
                return
            self._download_and_install_update(result)

    def _download_and_install_update(self, release: dict[str, Any]):
        if self._update_download_running:
            return
        self._update_download_running = True
        self._set_update_status(f"Загрузка Sanistra {release.get('version', '')}…")
        def worker():
            result: dict[str, str] = {}
            try:
                size = int(release.get("size", 0) or 0)
                if size and size > 500 * 1024 * 1024:
                    raise ValueError("Файл обновления больше допустимых 500 МБ.")
                updates_dir = DATA_DIR / "updates"
                updates_dir.mkdir(parents=True, exist_ok=True)
                staged = updates_dir / "Sanistra_new.exe"
                request = urllib.request.Request(str(release["url"]), headers={"User-Agent": "Sanistra-Updater/1.0"})
                digest = hashlib.sha256()
                total = 0
                with urllib.request.urlopen(request, timeout=40) as response, staged.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > 500 * 1024 * 1024:
                            raise ValueError("Загрузка превысила предел 500 МБ и была остановлена.")
                        output.write(chunk)
                        digest.update(chunk)
                expected_digest = str(release.get("digest", ""))
                if expected_digest.startswith("sha256:") and digest.hexdigest().lower() != expected_digest.split(":", 1)[1].lower():
                    staged.unlink(missing_ok=True)
                    raise ValueError("Контрольная сумма файла не совпала с данными GitHub. Обновление отменено.")
                if total < 1024 * 1024:
                    staged.unlink(missing_ok=True)
                    raise ValueError("Скачанный файл слишком мал, поэтому он не будет установлен.")
                result = {"staged": str(staged), "error": ""}
            except Exception as exc:
                result = {"error": str(exc)}
            try:
                self.after(0, lambda result=result: self._on_update_downloaded(result, str(release.get("version", ""))))
            except tk.TclError:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _on_update_downloaded(self, result: dict[str, str], version: str):
        self._update_download_running = False
        if result.get("error"):
            self._set_update_status("Загрузка обновления не удалась")
            messagebox.showerror("Не удалось загрузить обновление", result["error"], parent=self)
            return
        try:
            target = Path(sys.executable).resolve()
            staged = Path(result["staged"]).resolve()
            script_path = DATA_DIR / "install_update.ps1"
            backup = target.with_name(target.stem + ".previous" + target.suffix)
            script = r'''param([int]$TargetPid, [string]$SourcePath, [string]$TargetPath, [string]$BackupPath)
$ErrorActionPreference = 'Stop'
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Process -Id $TargetPid -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 400 }
if (Get-Process -Id $TargetPid -ErrorAction SilentlyContinue) { exit 10 }
try {
    if (Test-Path -LiteralPath $TargetPath) { Copy-Item -LiteralPath $TargetPath -Destination $BackupPath -Force }
    Copy-Item -LiteralPath $SourcePath -Destination $TargetPath -Force
    Remove-Item -LiteralPath $SourcePath -Force -ErrorAction SilentlyContinue
    Start-Process -FilePath $TargetPath
} catch {
    if (Test-Path -LiteralPath $BackupPath) { Copy-Item -LiteralPath $BackupPath -Destination $TargetPath -Force }
    if (Test-Path -LiteralPath $TargetPath) { Start-Process -FilePath $TargetPath }
    exit 11
}
'''
            script_path.write_text(script, encoding="utf-8-sig")
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path),
                 "-TargetPid", str(os.getpid()), "-SourcePath", str(staged), "-TargetPath", str(target), "-BackupPath", str(backup)],
                cwd=str(DATA_DIR), creationflags=creationflags,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            messagebox.showinfo("Обновление готово", f"Sanistra {version} загружена. Приложение закроется, файл будет заменён, затем Sanistra откроется снова.", parent=self)
            self.close()
        except Exception as exc:
            self._set_update_status("Не удалось запустить установку")
            messagebox.showerror("Не удалось установить обновление", f"Файл загружен, но автоматическая замена не запустилась. Перезапусти приложение позже.\n\n{exc}", parent=self)

    def _choose_accent(self, color: str):
        self.pending_accent = color.upper()
        self.accent_preview.configure(fg_color=self.pending_accent)
        self.accent_status.configure(text=f"Выбран: {self.pending_accent}")
        for preset_color, button in self.accent_buttons.items():
            button.configure(border_width=3 if preset_color.upper() == self.pending_accent else 0)

    def _choose_custom_accent(self):
        from tkinter import colorchooser
        chosen = colorchooser.askcolor(color=self.pending_accent, parent=self, title="Выбери цвет акцента")
        if chosen and chosen[1]:
            self._choose_accent(chosen[1])

    def _reset_settings_form(self):
        self.theme_var.set(DEFAULT_APP_SETTINGS["theme"])
        self.scale_var.set(f"{DEFAULT_APP_SETTINGS['scale']}%")
        self.compact_var.set(DEFAULT_APP_SETTINGS["compact_rows"])
        self.album_var.set(DEFAULT_APP_SETTINGS["show_album"])
        self.background_dim_var.set(DEFAULT_APP_SETTINGS["background_dim"])
        self._clear_background_image()
        self._choose_accent(DEFAULT_APP_SETTINGS["accent"])

    def _save_settings_and_restart(self):
        """Legacy method name retained for existing callbacks; settings now apply live."""
        settings = {
            "theme": self.theme_var.get(),
            "accent": self.pending_accent,
            "scale": int(self.scale_var.get().rstrip("%")),
            "compact_rows": bool(self.compact_var.get()),
            "show_album": bool(self.album_var.get()),
            "background_image": self.background_var.get().strip(),
            "background_dim": int(self.background_dim_var.get()),
        }
        try:
            temp_file = SETTINGS_FILE.with_suffix(".tmp")
            temp_file.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_file.replace(SETTINGS_FILE)
        except OSError as exc:
            messagebox.showerror("Настройки не сохранены", f"Не удалось сохранить настройки:\n{exc}", parent=self)
            return

        # Keep playback active while recreating widgets with the new colors/layout.
        current_search = self.search_text
        self.ui_settings = settings
        _apply_palette(settings)
        ctk.set_widget_scaling(settings["scale"] / 100)
        ctk.set_window_scaling(settings["scale"] / 100)
        self.configure(fg_color=BG)
        for child in self.winfo_children():
            child.destroy()
        self.row_widgets = []
        self.update_status_label = None
        self._wallpaper_ctk_image = None
        self._build_layout()
        if current_search:
            self.search_entry.insert(0, current_search)
        self.search_text = current_search
        self._apply_volume(self.volume)
        self.volume_var.set(self.volume * 100)
        self.navigate(self.current_view)
        self._refresh_player_bar()
        self._schedule_background_refresh()
        self._save_state()

    def _home_tracks(self) -> list[dict[str, Any]]:
        if self.current_path:
            current = next((x for x in self.library if x["path"] == self.current_path), None)
        else:
            current = None
        base = self._visible_tracks() if self.search_text else list(self.library)
        if current and current in base:
            base.remove(current)
            base.insert(0, current)
        return base[:12]

    def _render_track_section(self, tracks: list[dict[str, Any]], heading: str, show_all_link: bool):
        section = ctk.CTkFrame(self.content, fg_color="transparent")
        section.pack(fill="x", expand=True, pady=(0, 12))
        heading_row = ctk.CTkFrame(section, fg_color="transparent")
        heading_row.pack(fill="x", pady=(0, 9))
        ctk.CTkLabel(heading_row, text=heading, text_color=TEXT, font=(FONT, 17, "bold")).pack(side="left")
        ctk.CTkLabel(heading_row, text=f"{len(tracks)} треков", text_color=MUTED, font=(FONT, 10)).pack(side="left", padx=10, pady=(4, 0))
        if show_all_link:
            ctk.CTkButton(heading_row, text="Вся библиотека  →", width=110, height=28, fg_color="transparent", hover_color=SURFACE_2,
                          text_color=ACCENT, font=(FONT, 11, "bold"), command=lambda: self.navigate("All songs")).pack(side="right")
        header = ctk.CTkFrame(section, fg_color="transparent", height=28)
        header.pack(fill="x", padx=12)
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(header, text="#", width=30, text_color=MUTED, font=(FONT, 10)).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text="НАЗВАНИЕ", text_color=MUTED, font=(FONT, 10, "bold")).grid(row=0, column=1, sticky="w")
        time_column = 3 if self.ui_settings.get("show_album", True) else 2
        if self.ui_settings.get("show_album", True):
            ctk.CTkLabel(header, text="АЛЬБОМ", width=160, text_color=MUTED, font=(FONT, 10, "bold"), anchor="w").grid(row=0, column=2, sticky="w", padx=(8, 0))
        ctk.CTkLabel(header, text="ВРЕМЯ", width=55, text_color=MUTED, font=(FONT, 10, "bold"), anchor="e").grid(row=0, column=time_column, sticky="e")
        ctk.CTkFrame(section, height=1, fg_color=BORDER).pack(fill="x", pady=(5, 2))
        if not tracks:
            empty = ctk.CTkFrame(section, fg_color=SURFACE, corner_radius=14)
            empty.pack(fill="x", pady=12)
            ctk.CTkLabel(empty, text="♫", text_color=ACCENT, font=(FONT, 28)).pack(pady=(18, 4))
            ctk.CTkLabel(empty, text="Здесь появится твоя музыка", text_color=TEXT, font=(FONT, 13, "bold")).pack()
            ctk.CTkLabel(empty, text="Добавь песни или папку, чтобы собрать медиатеку.", text_color=MUTED, font=(FONT, 11)).pack(pady=(4, 17))
            ctk.CTkButton(empty, text="＋ Добавить музыку", height=34, corner_radius=10, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                          text_color=BG, font=(FONT, 11, "bold"), command=self.add_files).pack(pady=(0, 16))
            return
        for number, track in enumerate(tracks, 1):
            self._add_track_row(section, track, number)

    def _add_track_row(self, parent, track: dict[str, Any], number: int):
        path = track["path"]
        is_current = path == self.current_path
        row_height = 45 if self.ui_settings.get("compact_rows", False) else 55
        row = ctk.CTkFrame(parent, fg_color=SURFACE_2 if is_current else "transparent", corner_radius=10, height=row_height)
        row.pack(fill="x", pady=1 if self.ui_settings.get("compact_rows", False) else 2)
        row.grid_columnconfigure(1, weight=1)
        row.pack_propagate(False)
        self.row_widgets.append(row)
        number_text = "♫" if is_current else str(number).zfill(2)
        ctk.CTkLabel(row, text=number_text, width=30, text_color=ACCENT if is_current else MUTED,
                     font=(FONT, 12, "bold" if is_current else "normal")).grid(row=0, column=0, padx=(13, 3), sticky="w")
        title_frame = ctk.CTkFrame(row, fg_color="transparent")
        title_frame.grid(row=0, column=1, sticky="ew", pady=4 if self.ui_settings.get("compact_rows", False) else 7)
        ctk.CTkLabel(title_frame, text=track["title"], text_color=TEXT, font=(FONT, 12, "bold" if is_current else "normal"), anchor="w").pack(fill="x")
        ctk.CTkLabel(title_frame, text=track["artist"], text_color=MUTED, font=(FONT, 10), anchor="w").pack(fill="x", pady=(0, 0) if self.ui_settings.get("compact_rows", False) else (1, 0))
        time_column = 3 if self.ui_settings.get("show_album", True) else 2
        if self.ui_settings.get("show_album", True):
            ctk.CTkLabel(row, text=track["album"], width=160, text_color=MUTED, font=(FONT, 10), anchor="w").grid(row=0, column=2, padx=(8, 0), sticky="w")
        ctk.CTkLabel(row, text=fmt_time(track["duration"]), width=55, text_color=MUTED, font=(FONT, 10), anchor="e").grid(row=0, column=time_column, padx=(0, 7), sticky="e")
        row_playing = path == self.current_path and self.playing and not self.paused
        play_btn = ctk.CTkButton(row, text="Ⅱ" if row_playing else "▶", width=32, height=30,
                                 corner_radius=9, fg_color=ACCENT if row_playing else "transparent",
                                 hover_color=ACCENT_HOVER if row_playing else SURFACE_3,
                                 text_color=BG if row_playing else ACCENT, font=(FONT, 13, "bold"),
                                 command=lambda p=path: self._toggle_track_row_play(p))
        play_btn.grid(row=0, column=time_column + 1, padx=(0, 2))
        like = "♥" if path in self.favorites else "♡"
        like_color = RED if path in self.favorites else MUTED
        like_btn = ctk.CTkButton(row, text=like, width=29, height=30, fg_color="transparent", hover_color=SURFACE_3,
                                 text_color=like_color, font=(FONT, 17), command=lambda p=path: self.toggle_favorite(p))
        like_btn.grid(row=0, column=time_column + 2, padx=(0, 2))
        menu_btn = ctk.CTkButton(row, text="···", width=32, height=30, fg_color="transparent", hover_color=SURFACE_3,
                                 text_color=MUTED, font=(FONT, 16, "bold"), command=lambda t=track: self.open_track_menu(t))
        menu_btn.grid(row=0, column=time_column + 3, padx=(0, 5))
        def bind_row(widget):
            if isinstance(widget, ctk.CTkButton):
                return
            widget.bind("<Double-Button-1>", lambda _e, p=path: self.play_path(p), add="+")
            widget.bind("<Button-1>", lambda _e, p=path: self._select_row(p), add="+")
            for child in widget.winfo_children():
                bind_row(child)
        bind_row(row)

    def _toggle_track_row_play(self, path: str):
        if path == self.current_path and self.playing and not self.paused:
            self.toggle_play()
        elif path == self.current_path and self.paused:
            self.toggle_play()
        else:
            self.play_path(path)

    def _select_row(self, path: str):
        self.selected_path = path

    def open_track_menu(self, track: dict[str, Any]):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Воспроизвести", command=lambda: self.play_path(track["path"]))
        menu.add_command(label="Воспроизвести следующим", command=lambda: self.play_next(track["path"]))
        menu.add_command(label="Добавить в текущий плейлист", command=lambda: self.add_to_playlist(track["path"], self.active_playlist))
        menu.add_command(label="Добавить в плейлист…", command=lambda: self.choose_playlist_for_track(track["path"]))
        menu.add_command(label="Открыть папку с файлом", command=lambda: self.show_in_folder(track["path"]))
        menu.add_separator()
        menu.add_command(label="Удалить из медиатеки", command=lambda: self.remove_from_library(track["path"]))
        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    # ---------- library management ----------
    def add_files(self):
        paths = filedialog.askopenfilenames(title="Добавить музыку", filetypes=[("Аудиофайлы", "*.mp3 *.wav *.ogg *.flac *.m4a *.opus *.aiff *.aif *.mid *.midi *.wma"), ("Все файлы", "*.*")])
        self._add_paths(paths)

    def add_folder(self):
        folder = filedialog.askdirectory(title="Выбери папку с музыкой", mustexist=True)
        if not folder:
            return
        paths = []
        for root, dirs, files in os.walk(folder):
            dirs.sort(key=str.casefold)
            for filename in files:
                if Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS:
                    paths.append(os.path.join(root, filename))
        paths.sort(key=str.casefold)
        self._add_paths(paths)

    def _add_paths(self, paths):
        seen = {os.path.normcase(x["path"]) for x in self.library}
        added = 0
        for path in paths:
            path = os.path.abspath(os.path.expanduser(str(path)))
            if not os.path.isfile(path) or Path(path).suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            key = os.path.normcase(path)
            if key in seen:
                continue
            seen.add(key)
            track = tags_for(path)
            override = self.duration_overrides.get(os.path.normcase(track["path"]))
            if override is not None:
                track["duration"] = override
            self.library.append(track)
            added += 1
        if added:
            self._save_state()
            self._render_view()
            self._draw_playlist_nav()
        elif paths:
            messagebox.showinfo("Sanistra", "Новых поддерживаемых аудиофайлов не найдено.")

    def remove_from_library(self, path: str):
        track = next((x for x in self.library if x["path"] == path), None)
        if not track:
            return
        self.library = [x for x in self.library if x["path"] != path]
        self.favorites.discard(path)
        self.history = [x for x in self.history if x != path]
        for name in self.playlists:
            self.playlists[name] = [x for x in self.playlists[name] if x != path]
        if self.current_path == path:
            self.stop_playback()
            self.current_path = None
            self.current_duration = 0
        self._save_state()
        self._render_view()
        self._refresh_player_bar()

    def remove_current_from_library(self):
        if self.current_path:
            self.remove_from_library(self.current_path)

    def toggle_favorite(self, path: str):
        if path in self.favorites:
            self.favorites.remove(path)
        else:
            self.favorites.add(path)
        self._save_state()
        self._render_view()
        self._refresh_player_bar()

    def toggle_current_favorite(self):
        if self.current_path:
            self.toggle_favorite(self.current_path)

    def create_playlist(self):
        dialog = ctk.CTkInputDialog(text="Введи название плейлиста:", title="Новый плейлист")
        name = dialog.get_input()
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name in self.playlists:
            messagebox.showinfo("Плейлист", "Плейлист с таким названием уже существует.")
            return
        self.playlists[name] = []
        self.active_playlist = name
        self.current_view = f"Playlist:{name}"
        self._save_state()
        self._draw_playlist_nav()
        self._render_view()

    def rename_playlist(self, old: str):
        dialog = ctk.CTkInputDialog(text="Введи новое название плейлиста:", title="Переименовать плейлист")
        new = dialog.get_input()
        if not new or not new.strip():
            return
        new = new.strip()
        if new != old and new in self.playlists:
            messagebox.showinfo("Плейлист", "Плейлист с таким названием уже существует.")
            return
        self.playlists[new] = self.playlists.pop(old)
        if self.active_playlist == old:
            self.active_playlist = new
        self.current_view = f"Playlist:{new}"
        self._save_state()
        self._render_view()

    def add_to_playlist(self, path: str, name: str):
        if name not in self.playlists:
            self.playlists[name] = []
        if path not in self.playlists[name]:
            self.playlists[name].append(path)
        self.active_playlist = name
        self._save_state()
        self._draw_playlist_nav()

    def choose_playlist_for_track(self, path: str):
        names = list(self.playlists)
        if not names:
            self.create_playlist()
            names = list(self.playlists)
        win = ctk.CTkToplevel(self)
        win.title("Добавить в плейлист")
        win.geometry("320x350")
        win.configure(fg_color=BG)
        win.transient(self)
        win.grab_set()
        ctk.CTkLabel(win, text="Выбери плейлист", font=(FONT, 17, "bold"), text_color=TEXT).pack(anchor="w", padx=20, pady=(20, 12))
        for name in names:
            ctk.CTkButton(win, text=name, anchor="w", fg_color=SURFACE, hover_color=SURFACE_2,
                          text_color=TEXT, height=38, command=lambda n=name: (self.add_to_playlist(path, n), win.destroy())).pack(fill="x", padx=18, pady=3)

    def play_next(self, path: str):
        # Queue is separate from the active view, so "Play next" works from every page.
        self.up_next = [item for item in self.up_next if item != path]
        self.up_next.insert(0, path)
        messagebox.showinfo("Очередь обновлена", "Трек добавлен следующим в очередь.")

    def show_in_folder(self, path: str):
        try:
            if os.name == "nt":
                os.startfile(os.path.dirname(path))
            else:
                import subprocess
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except Exception as exc:
            messagebox.showerror("Не удалось открыть папку", str(exc))

    # ---------- M3U playlist support ----------
    def save_m3u(self, playlist_name: str | None = None):
        if playlist_name is None:
            tracks = [x["path"] for x in self.library]
            suggested = "Sanistra Library.m3u8"
        else:
            tracks = self.playlists.get(playlist_name, [])
            suggested = f"{playlist_name}.m3u8"
        if not tracks:
            messagebox.showinfo("Экспорт плейлиста", "В этом плейлисте пока нет треков.")
            return
        dest = filedialog.asksaveasfilename(title="Экспорт плейлиста M3U", defaultextension=".m3u8", initialfile=suggested,
                                             filetypes=[("Плейлисты M3U", "*.m3u8 *.m3u")])
        if not dest:
            return
        by_path = {x["path"]: x for x in self.library}
        try:
            with open(dest, "w", encoding="utf-8-sig") as file:
                file.write("#EXTM3U\n")
                for path in tracks:
                    track = by_path.get(path)
                    if track:
                        file.write(f"#EXTINF:{int(track['duration'])},{track['artist']} - {track['title']}\n{path}\n")
            messagebox.showinfo("Экспорт завершён", f"Сохранено треков: {len(tracks)}.")
        except OSError as exc:
            messagebox.showerror("Ошибка экспорта", str(exc))

    def open_m3u(self):
        path = filedialog.askopenfilename(title="Открыть плейлист M3U", filetypes=[("Плейлисты M3U", "*.m3u *.m3u8"), ("Все файлы", "*.*")])
        if not path:
            return
        try:
            parsed = []
            base = os.path.dirname(os.path.abspath(path))
            with open(path, "r", encoding="utf-8-sig", errors="replace") as file:
                for line in file:
                    item = line.strip()
                    if item and not item.startswith("#"):
                        if not os.path.isabs(item):
                            item = os.path.join(base, item)
                        parsed.append(item)
            self._add_paths(parsed)
            existing = {x["path"] for x in self.library}
            valid = [os.path.abspath(x) for x in parsed if os.path.abspath(x) in existing]
            name = Path(path).stem
            if name in self.playlists:
                name = f"{name} (imported)"
            self.playlists[name] = valid
            self.active_playlist = name
            self.current_view = f"Playlist:{name}"
            self._save_state()
            self._render_view()
        except OSError as exc:
            messagebox.showerror("Ошибка импорта", str(exc))

    # ---------- playback ----------
    def play_path(self, path: str):
        track = next((x for x in self.library if x["path"] == path), None)
        if not track:
            return
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(self.volume)
            pygame.mixer.music.play()
        except (pygame.error, OSError) as exc:
            messagebox.showerror("Ошибка воспроизведения", f"Не удалось воспроизвести файл:\n{path}\n\n{exc}\n\nПопробуй MP3, WAV, OGG или FLAC.")
            return
        self.current_path = path
        self.current_duration = float(track.get("duration", 0) or 0)
        self.original_duration = self.current_duration
        self.duration_was_corrected = False
        self.last_busy_position = 0.0
        self.position_base = 0.0
        self.started_at = time.monotonic()
        self._mixer_position_anchor = 0.0
        self._last_valid_mixer_pos = 0.0
        self._use_mixer_clock = True
        self.playing = True
        self.paused = False
        self.last_end_check = time.monotonic()
        self.history.insert(0, path)
        self.history = list(dict.fromkeys(self.history))[:100]
        self._save_state()
        self.play_btn.configure(text="Ⅱ")
        self._refresh_player_bar()
        self._render_view()

    def _playback_list(self) -> list[str]:
        if self.current_view.startswith("Playlist:"):
            name = self.current_view.split(":", 1)[1]
            paths = [p for p in self.playlists.get(name, []) if any(x["path"] == p for x in self.library)]
            if paths:
                return paths
        return [x["path"] for x in self.library]

    def toggle_play(self):
        if self.paused:
            # After pause, use a monotonic clock anchored at the stored audio position.
            # Some SDL_mixer decoders report get_pos inconsistently across pause/resume.
            self._use_mixer_clock = False
            pygame.mixer.music.unpause()
            self.paused = False
            self.playing = True
            self.started_at = time.monotonic()
            self.play_btn.configure(text="Ⅱ")
            self._render_view()
            return
        if self.playing:
            self.position_base = self._position()
            self._use_mixer_clock = False
            pygame.mixer.music.pause()
            self.paused = True
            self.playing = False
            self.play_btn.configure(text="▶")
            self._render_view()
            return
        if self.current_path:
            self.play_path(self.current_path)
        else:
            paths = self._playback_list()
            if paths:
                self.play_path(paths[0])
            elif self.library:
                self.play_path(self.library[0]["path"])
            else:
                self.add_files()
                if self.library:
                    self.play_path(self.library[0]["path"])

    def stop_playback(self):
        try:
            pygame.mixer.music.stop()
        except pygame.error:
            pass
        self.playing = False
        self.paused = False
        self.position_base = 0.0
        self.play_btn.configure(text="▶")

    def _position(self) -> float:
        """Use SDL_mixer's elapsed audio clock when reliable; fall back after pause/seek."""
        if self.paused:
            return max(0.0, self.position_base)
        if self.playing:
            if self._use_mixer_clock:
                try:
                    mixer_ms = pygame.mixer.music.get_pos()
                    if mixer_ms >= 0:
                        mixer_seconds = mixer_ms / 1000.0
                        # get_pos excludes the seek offset; position_base restores it.
                        delta = mixer_seconds - self._mixer_position_anchor
                        if delta >= -0.30:
                            delta = max(0.0, delta)
                            self._last_valid_mixer_pos = mixer_seconds
                            return max(0.0, self.position_base + delta)
                except pygame.error:
                    pass
            return max(0.0, self.position_base + time.monotonic() - self.started_at)
        return max(0.0, self.position_base)

    def next_track(self, automatic: bool = False):
        # A queued track takes priority over repeat-one, just as it does in music players.
        while self.up_next:
            queued = self.up_next.pop(0)
            if any(item["path"] == queued for item in self.library):
                self.play_path(queued)
                return
        paths = self._playback_list()
        if not paths:
            return
        if self.current_path not in paths:
            self.play_path(paths[0])
            return
        if automatic and self.repeat_mode == "one":
            self.play_path(self.current_path)
            return
        if self.shuffle and len(paths) > 1:
            options = [p for p in paths if p != self.current_path]
            self.play_path(random.choice(options))
            return
        index = paths.index(self.current_path)
        if index + 1 < len(paths):
            self.play_path(paths[index + 1])
        elif self.repeat_mode == "all":
            self.play_path(paths[0])
        else:
            self.stop_playback()
            self.position_base = self.current_duration
            self._refresh_player_bar()

    def previous_track(self):
        paths = self._playback_list()
        if not paths:
            return
        if self._position() > 3 and self.current_path:
            self.play_path(self.current_path)
            return
        if self.current_path not in paths:
            self.play_path(paths[0])
            return
        index = paths.index(self.current_path)
        if index > 0:
            self.play_path(paths[index - 1])
        elif self.repeat_mode == "all":
            self.play_path(paths[-1])
        else:
            self.play_path(paths[0])

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle
        self.shuffle_btn.configure(text_color=ACCENT if self.shuffle else MUTED)
        self._save_state()

    def toggle_repeat(self):
        self.repeat_mode = {"all": "one", "one": "off", "off": "all"}[self.repeat_mode]
        label = {"all": "⟳", "one": "⟳¹", "off": "⟳"}[self.repeat_mode]
        self.repeat_btn.configure(text=label, text_color=ACCENT if self.repeat_mode != "off" else MUTED)
        self._save_state()

    def _seek_press(self, _event=None):
        self.seek_dragging = True

    def _seek_changed(self, value):
        if self.seek_dragging:
            self.elapsed.configure(text=fmt_time(float(value)))

    def _seek_release(self, _event=None):
        self.seek_dragging = False
        if not self.current_path or self.current_duration <= 0:
            return
        target = min(float(self.seek_var.get()), self.current_duration)
        # SDL_mixer supports seeking for several formats; restart at target when possible.
        was_paused = self.paused
        try:
            pygame.mixer.music.play(start=target)
            self.position_base = target
            self.last_busy_position = target
            self.started_at = time.monotonic()
            self._mixer_position_anchor = 0.0
            self._last_valid_mixer_pos = 0.0
            self._use_mixer_clock = not was_paused
            self.playing = True
            self.paused = False
            if was_paused:
                pygame.mixer.music.pause()
                self.position_base = target
                self.playing = False
                self.paused = True
                self.play_btn.configure(text="▶")
            else:
                self.play_btn.configure(text="Ⅱ")
        except (pygame.error, TypeError):
            # For formats without time seeking, continue safely from the beginning.
            self.play_path(self.current_path)

    def _on_volume(self, value):
        self.volume = max(0, min(1, float(value) / 100))
        self._apply_volume(self.volume)
        if not self._loading_state:
            self._save_state()

    def _apply_volume(self, value):
        try:
            pygame.mixer.music.set_volume(float(value))
        except pygame.error:
            pass

    def _refresh_player_bar(self):
        track = next((x for x in self.library if x["path"] == self.current_path), None)
        if not track:
            self.bar_title.configure(text="Ничего не играет")
            self.bar_artist.configure(text="Выбери песню для начала")
            self.like_btn.configure(text="♡", text_color=MUTED)
            self.total.configure(text="0:00")
            self.elapsed.configure(text="0:00")
            self.seek_var.set(0)
            return
        self.bar_title.configure(text=track["title"])
        self.bar_artist.configure(text=track["artist"])
        liked = self.current_path in self.favorites
        self.like_btn.configure(text="♥" if liked else "♡", text_color=RED if liked else MUTED)
        self.total.configure(text=fmt_time(self.current_duration))
        self.seek.configure(to=max(1.0, self.current_duration))

    def _tick(self):
        try:
            if self.current_path:
                now = time.monotonic()
                raw_pos = self._position()
                busy = False
                if self.playing and not self.paused and now - self.last_end_check > 0.20:
                    self.last_end_check = now
                    try:
                        busy = pygame.mixer.music.get_busy()
                    except pygame.error:
                        busy = False

                    if busy:
                        self.last_busy_position = raw_pos
                        # Unknown or inaccurate metadata must not freeze the seek bar at
                        # 100%. Once the stream demonstrably outlives its estimate, extend
                        # the estimate in small steps while the mixer confirms playback.
                        if self.current_duration <= 0:
                            self.current_duration = raw_pos + 8.0
                            self.duration_was_corrected = True
                        elif raw_pos > self.current_duration + 0.45:
                            margin = max(2.0, min(5.0, self.original_duration * 0.025))
                            self.current_duration = raw_pos + margin
                            self.duration_was_corrected = True
                        elif self.duration_was_corrected and raw_pos >= self.current_duration - 0.35:
                            self.current_duration = raw_pos + 1.8
                    elif now - self.started_at > 0.75:
                        # The audio engine, not the tag duration, determines when the
                        # track actually finished. Store observed duration when the tag was
                        # off in either direction so subsequent plays have a better total.
                        observed_end = max(0.0, min(raw_pos, self.last_busy_position + 0.35))
                        if observed_end > 1.0 and (
                            self.original_duration <= 0
                            or abs(observed_end - self.original_duration) > 1.0
                            or self.duration_was_corrected
                        ):
                            self.current_duration = observed_end
                            track = next((x for x in self.library if x["path"] == self.current_path), None)
                            if track:
                                track["duration"] = observed_end
                                self.duration_overrides[os.path.normcase(self.current_path)] = observed_end
                                self._save_state()
                        self.next_track(automatic=True)
                        return

                pos = raw_pos
                if self.current_duration > 0:
                    pos = min(pos, self.current_duration)
                    if not self.seek_dragging:
                        self.seek.configure(to=max(1.0, self.current_duration))
                        self.seek_var.set(pos)
                    self.elapsed.configure(text=fmt_time(pos))
                    self.total.configure(text=fmt_time(self.current_duration))
        finally:
            self.after(250, self._tick)

    def _hotkey_space(self, event):
        # Don't intercept space when the user is typing in a text input.
        if isinstance(event.widget, (ctk.CTkEntry, tk.Entry, tk.Text, ctk.CTkTextbox)):
            return
        self.toggle_play()
        return "break"

    def close(self):
        self._save_state()
        try:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except pygame.error:
            pass
        self.destroy()


def main():
    app = SanistraApp()
    app.mainloop()


if __name__ == "__main__":
    main()
