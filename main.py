"""
WoWra - WeakAura-ähnliches externes Overlay-Tool für WoW mit Buff-Timern, Sound/TTS.
Zeigt ein immer sichtbares Overlay mit Countdown-Balken für konfigurierbare Buffs.
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import json
import os
import threading
import time
import winsound
import sys
import ctypes
import ctypes.wintypes
import logging
from collections import deque

# Konsolenfenster verstecken (wenn mit python.exe statt pythonw.exe gestartet)
def _hide_console():
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass

_hide_console()

# Logging Setup
LOG_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(LOG_DIR, "wowra.log")

logger = logging.getLogger("WoWra")
logger.setLevel(logging.DEBUG)

_file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s  [%(levelname)s]  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
logger.addHandler(_file_handler)

logger.info("=" * 50)
logger.info("WoWra gestartet")

try:
    import keyboard
except ImportError:
    print("FEHLER: 'keyboard' Modul nicht gefunden. Bitte installiere es mit: pip install keyboard")
    sys.exit(1)

try:
    import mouse
    HAS_MOUSE = True
except ImportError:
    HAS_MOUSE = False
    print("WARNUNG: 'mouse' Modul nicht gefunden - Maustasten-Support deaktiviert. pip install mouse")

# Maustasten-Mapping: interner Name -> Anzeigename
MOUSE_BUTTON_MAP = {
    'x': 'M4',
    'x2': 'M5',
    'middle': 'M3',
    'left': 'M1',
    'right': 'M2',
}
MOUSE_DISPLAY_TO_INTERNAL = {v: k for k, v in MOUSE_BUTTON_MAP.items()}

# Virtual Key Codes für GetAsyncKeyState Polling
MOUSE_VK_CODES = {
    'M1': 0x01,   # VK_LBUTTON
    'M2': 0x02,   # VK_RBUTTON
    'M3': 0x04,   # VK_MBUTTON
    'M4': 0x05,   # VK_XBUTTON1
    'M5': 0x06,   # VK_XBUTTON2
}
MODIFIER_VK_CODES = {
    'ctrl': 0x11,   # VK_CONTROL
    'shift': 0x10,  # VK_SHIFT
    'alt': 0x12,    # VK_MENU
}

_GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState
_GetAsyncKeyState.argtypes = [ctypes.c_int]
_GetAsyncKeyState.restype = ctypes.c_short

def is_key_pressed(vk_code):
    """Prüft ob eine Taste gerade gedrückt ist via Windows API."""
    return bool(_GetAsyncKeyState(vk_code) & 0x8000)


# --- WoW-Fenster-Erkennung via Windows API ---
_FindWindowW = ctypes.windll.user32.FindWindowW
_FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
_FindWindowW.restype = ctypes.c_void_p

_GetWindowRect = ctypes.windll.user32.GetWindowRect
_IsWindow = ctypes.windll.user32.IsWindow
_IsWindowVisible = ctypes.windll.user32.IsWindowVisible
_IsIconic = ctypes.windll.user32.IsIconic  # Minimiert?
_GetForegroundWindow = ctypes.windll.user32.GetForegroundWindow
_GetForegroundWindow.restype = ctypes.c_void_p

# Bekannte WoW-Fenstertitel
WOW_WINDOW_NAMES = ["World of Warcraft"]

def find_wow_window():
    """Sucht das WoW-Fenster und gibt (hwnd, x, y, w, h) zurück oder None."""
    for title in WOW_WINDOW_NAMES:
        hwnd = _FindWindowW(None, title)
        if hwnd and _IsWindow(hwnd) and _IsWindowVisible(hwnd):
            rect = ctypes.wintypes.RECT()
            if _GetWindowRect(hwnd, ctypes.byref(rect)):
                return (hwnd, rect.left, rect.top,
                        rect.right - rect.left, rect.bottom - rect.top)
    return None

MODIFIER_KEYS = {'ctrl', 'shift', 'alt', 'left ctrl', 'right ctrl',
                 'left shift', 'right shift', 'left alt', 'right alt',
                 'left windows', 'right windows'}

def normalize_modifier(name):
    """Normalisiert Modifier-Namen."""
    n = name.lower()
    if 'ctrl' in n:
        return 'ctrl'
    if 'shift' in n:
        return 'shift'
    if 'alt' in n:
        return 'alt'
    return n

import subprocess
HAS_TTS = True  # Nutzt Windows SAPI via PowerShell - immer verfügbar

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
SOUNDS_DIR = os.path.join(APP_DIR, "sounds")

# Sounds-Verzeichnis anlegen falls nicht vorhanden
if not os.path.exists(SOUNDS_DIR):
    os.makedirs(SOUNDS_DIR)

# Auto-Updater Konfiguration
GITHUB_REPO = "bySenom/WoWra"
CURRENT_VERSION = "1.1.0"

DEFAULT_BUFF = {
    "name": "Blühendes Leben",
    "hotkey": "F5",
    "duration": 15,
    "max_duration": 20,
    "alert_before": 0,
    "sound": True,
    "tts": True,
    "sound_file": "",
    "depends_on": ""
}

DEFAULT_CONFIG = {
    "overlay": {
        "x": 200,
        "y": 200,
        "opacity": 0.88,
        "font_size": 13,
        "bar_height": 24,
        "width": 320,
        "attach_to_wow": True,
        "wow_offset_x": 50,
        "wow_offset_y": 50
    },
    "active_profile": "Standard",
    "profiles": {
        "Standard": {
            "buffs": [DEFAULT_BUFF.copy()]
        }
    },
    "alert_sound_freq": 880,
    "alert_sound_duration": 400,
    "expired_display_seconds": 4,
    "visual_countdown": True,
    "visual_countdown_size": 72,
    "layout": {
        "grid_size": 20,
        "countdown_offset_x": None,
        "countdown_offset_y": None,
        "elements": []
    }
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # Merge defaults for missing keys
            for key, val in DEFAULT_CONFIG.items():
                if key not in cfg:
                    cfg[key] = val
            if "overlay" in DEFAULT_CONFIG:
                for k, v in DEFAULT_CONFIG["overlay"].items():
                    if k not in cfg.get("overlay", {}):
                        cfg.setdefault("overlay", {})[k] = v
            if "layout" in DEFAULT_CONFIG:
                for k, v in DEFAULT_CONFIG["layout"].items():
                    if k not in cfg.get("layout", {}):
                        cfg.setdefault("layout", {})[k] = v
            # Migration: altes Format (buffs direkt) -> neues Profil-System
            if "buffs" in cfg and "profiles" not in cfg:
                profile_name = cfg.get("active_profile", "Standard")
                cfg["profiles"] = {profile_name: {"buffs": cfg.pop("buffs")}}
                cfg.setdefault("active_profile", profile_name)
            # Defaults für neue Felder in Buffs
            for pname, profile in cfg.get("profiles", {}).items():
                for buff in profile.get("buffs", []):
                    for k, v in DEFAULT_BUFF.items():
                        if k not in buff:
                            buff[k] = v
            return cfg
        except Exception as e:
            print(f"Fehler beim Laden der Config: {e}")
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_active_buffs(config):
    """Gibt die Buff-Liste des aktiven Profils zurück."""
    profile_name = config.get('active_profile', 'Standard')
    profiles = config.get('profiles', {})
    if profile_name in profiles:
        return profiles[profile_name].get('buffs', [])
    # Fallback: erstes Profil
    if profiles:
        first = next(iter(profiles.values()))
        return first.get('buffs', [])
    return []


def set_active_buffs(config, buffs):
    """Setzt die Buff-Liste des aktiven Profils."""
    profile_name = config.get('active_profile', 'Standard')
    config.setdefault('profiles', {}).setdefault(profile_name, {})["buffs"] = buffs


# --- Auto-Updater ---
def check_for_updates():
    """Prüft GitHub auf neue Versionen. Gibt (neue_version, download_url) oder None zurück."""
    if not GITHUB_REPO:
        return None
    try:
        import urllib.request
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={'User-Agent': 'WoWra'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        tag = data.get('tag_name', '').lstrip('v')
        if tag and tag != CURRENT_VERSION:
            assets = data.get('assets', [])
            dl_url = data.get('html_url', '')
            for asset in assets:
                if asset['name'].endswith('.zip') or asset['name'].endswith('.exe'):
                    dl_url = asset['browser_download_url']
                    break
            return (tag, dl_url)
    except Exception as e:
        logger.debug(f"Update-Check fehlgeschlagen: {e}")
    return None


class BuffTimer:
    """Verwaltet den Timer-Zustand für einen einzelnen Buff."""

    def __init__(self, name, duration, max_duration, alert_before=0):
        self.name = name
        self.duration = duration
        self.max_duration = max_duration
        self.alert_before = alert_before
        self.end_time = 0.0
        self.active = False
        self.expired_at = None
        self.early_alert_fired = False  # Früh-Alarm bereits ausgelöst?

    def activate(self):
        now = time.time()
        if self.active:
            remaining = self.end_time - now
            new_remaining = min(remaining + self.duration, self.max_duration)
            self.end_time = now + new_remaining
            logger.info(
                f"REFRESH '{self.name}': {remaining:.1f}s + {self.duration}s "
                f"= {new_remaining:.1f}s (max {self.max_duration}s)"
            )
        else:
            self.end_time = now + self.duration
            self.active = True
            logger.info(f"START '{self.name}': {self.duration}s (max {self.max_duration}s)")
        self.expired_at = None
        self.early_alert_fired = False

    @property
    def remaining(self):
        if not self.active:
            return 0.0
        return max(0.0, self.end_time - time.time())

    def check_early_alert(self):
        """Prüft ob der Früh-Alarm ausgelöst werden soll. Gibt True einmalig zurück."""
        if self.active and self.alert_before > 0 and not self.early_alert_fired:
            if self.remaining <= self.alert_before:
                self.early_alert_fired = True
                logger.info(f"FRÜH-ALARM '{self.name}': {self.remaining:.1f}s verbleibend (alert_before={self.alert_before}s)")
                return True
        return False

    def check_expired(self):
        """Prüft ob der Timer gerade abgelaufen ist. Gibt True einmalig zurück."""
        if self.active and self.remaining <= 0:
            self.active = False
            self.expired_at = time.time()
            logger.warning(f"ABGELAUFEN '{self.name}'")
            return True
        return False

    @property
    def is_showing(self):
        return self.active or self.expired_at is not None

    def clear_expired(self, display_seconds):
        if self.expired_at and (time.time() - self.expired_at) > display_seconds:
            self.expired_at = None


class TTSWorker:
    """Dedizierter TTS-Thread mit Queue - nutzt Windows SAPI via PowerShell."""

    def __init__(self):
        self._queue = []
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def speak(self, text):
        with self._lock:
            self._queue.append(text)

    def _speak_windows(self, text):
        """Spricht Text über Windows SAPI via PowerShell - zuverlässig bei wiederholten Aufrufen."""
        # Einfache Bereinigung: nur erlaubte Zeichen
        safe_text = text.replace("'", "''").replace('"', '')
        ps_script = (
            f"Add-Type -AssemblyName System.Speech; "
            f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.Rate = 2; "
            f"$s.Speak('{safe_text}'); "
            f"$s.Dispose()"
        )
        try:
            subprocess.run(
                ['powershell', '-NoProfile', '-Command', ps_script],
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            logger.debug(f"TTS gesprochen: '{text}'")
        except subprocess.TimeoutExpired:
            logger.error(f"TTS Timeout für: '{text}'")
        except Exception as e:
            logger.error(f"TTS Fehler: {e}")

    def _run(self):
        while self._running:
            text = None
            with self._lock:
                if self._queue:
                    text = self._queue.pop(0)
            if text:
                self._speak_windows(text)
            else:
                time.sleep(0.1)

    def stop(self):
        self._running = False


class WoWraOverlay:
    """Haupt-Overlay-Anwendung."""

    BG_COLOR = "#0d1117"
    BAR_BG = "#21262d"
    TITLE_BG = "#161b22"
    TEXT_COLOR = "#e6edf3"
    ACCENT = "#58a6ff"
    GREEN = "#3fb950"
    YELLOW = "#d29922"
    RED = "#f85149"
    EXPIRED_COLOR = "#da3633"

    def __init__(self):
        self.config = load_config()
        self.timers = {}
        self.timer_widgets = {}
        self.hotkey_hooks = []
        self.tts_worker = TTSWorker() if HAS_TTS else None

        # Thread-sichere Queue für Hotkey-Events
        self._pending_activations = deque()

        # Tracking: welche Keyboard-Tasten sind gerade gedrückt gehalten
        self._keys_held = set()
        self._keys_held_lock = threading.Lock()

        # Maustasten-Polling: vorheriger Zustand pro Button
        self._mouse_poll_bindings = []
        self._mouse_prev_state = {}  # vk_code -> was_pressed

        # WoW-Fenster Tracking
        self._wow_hwnd = None
        self._wow_last_rect = None  # (x, y, w, h) des WoW-Fensters
        self._wow_overlay_hidden = False  # Overlay gerade versteckt?

        # Edit Mode / Layout Manager
        self._edit_mode = False
        self._edit_grid_window = None
        self._edit_toolbar = None
        self._layout_elements = {}
        self._edit_original_positions = {}
        self._edit_original_elements = []

        # Tkinter Root
        self.root = tk.Tk()
        self.root.title("WoWra")
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', self.config['overlay']['opacity'])
        self.root.configure(bg=self.BG_COLOR)

        ov = self.config['overlay']
        # Initiale Position: entweder an WoW anheften oder absolute Position
        if ov.get('attach_to_wow', True):
            wow = find_wow_window()
            if wow:
                self._wow_hwnd = wow[0]
                self._wow_last_rect = wow[1:]
                wx, wy = wow[1], wow[2]
                start_x = wx + ov.get('wow_offset_x', 50)
                start_y = wy + ov.get('wow_offset_y', 50)
                self.root.geometry(f"{ov['width']}x40+{start_x}+{start_y}")
                logger.info(f"An WoW-Fenster angeheftet (Offset: {ov.get('wow_offset_x', 50)}, {ov.get('wow_offset_y', 50)})")
            else:
                self.root.geometry(f"{ov['width']}x40+{ov['x']}+{ov['y']}")
                logger.info("WoW-Fenster nicht gefunden - nutze gespeicherte Position")
        else:
            self.root.geometry(f"{ov['width']}x40+{ov['x']}+{ov['y']}")

        # Drag-Daten
        self._drag_x = 0
        self._drag_y = 0

        self._build_title_bar()

        # Timer-Container
        self.timer_frame = tk.Frame(self.root, bg=self.BG_COLOR)
        self.timer_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        # Status-Label wenn keine Buffs aktiv
        self.idle_label = tk.Label(
            self.timer_frame, text="⏳ Warte auf Hotkey...",
            fg="#484f58", bg=self.BG_COLOR,
            font=("Segoe UI", 9, "italic")
        )
        self.idle_label.pack(pady=4)

        # Visueller Countdown (WeakAura-Style) - separates Fenster
        self._countdown_window = None
        self._countdown_label = None
        self._setup_visual_countdown()

        # Custom Layout-Elemente
        self._create_layout_elements()

        # Setup
        self._setup_buffs()
        self._register_hotkeys()

        # Auto-Updater Check
        self._check_update_async()

        # Update-Loop
        self._update()

        # Window close
        self.root.protocol("WM_DELETE_WINDOW", self._quit)

    def _build_title_bar(self):
        title_frame = tk.Frame(self.root, bg=self.TITLE_BG, cursor="fleur")
        title_frame.pack(fill=tk.X)
        title_frame.bind('<Button-1>', self._drag_start)
        title_frame.bind('<B1-Motion>', self._drag_move)

        icon_label = tk.Label(
            title_frame, text="🛡️",
            fg=self.ACCENT, bg=self.TITLE_BG,
            font=("Segoe UI", 10, "bold")
        )
        icon_label.pack(side=tk.LEFT, padx=(6, 2), pady=3)
        icon_label.bind('<Button-1>', self._drag_start)
        icon_label.bind('<B1-Motion>', self._drag_move)

        # Profil-Anzeige (klickbar zum Wechseln)
        profile_name = self.config.get('active_profile', 'Standard')
        self._profile_label = tk.Label(
            title_frame, text=f"📋 {profile_name}",
            fg="#8b949e", bg=self.TITLE_BG,
            font=("Segoe UI", 9), cursor="hand2"
        )
        self._profile_label.pack(side=tk.LEFT, padx=2, pady=3)
        self._profile_label.bind('<Button-1>', lambda e: self._cycle_profile())
        self._profile_label.bind('<Enter>', lambda e: self._profile_label.configure(fg=self.ACCENT))
        self._profile_label.bind('<Leave>', lambda e: self._profile_label.configure(fg="#8b949e"))

        # Close
        close_btn = tk.Label(
            title_frame, text="✕", fg="#8b949e", bg=self.TITLE_BG,
            font=("Segoe UI", 11), cursor="hand2"
        )
        close_btn.pack(side=tk.RIGHT, padx=6)
        close_btn.bind('<Button-1>', lambda e: self._quit())
        close_btn.bind('<Enter>', lambda e: close_btn.configure(fg=self.RED))
        close_btn.bind('<Leave>', lambda e: close_btn.configure(fg="#8b949e"))

        # Settings
        settings_btn = tk.Label(
            title_frame, text="⚙", fg="#8b949e", bg=self.TITLE_BG,
            font=("Segoe UI", 12), cursor="hand2"
        )
        settings_btn.pack(side=tk.RIGHT, padx=2)
        settings_btn.bind('<Button-1>', lambda e: self._open_config())
        settings_btn.bind('<Enter>', lambda e: settings_btn.configure(fg=self.ACCENT))
        settings_btn.bind('<Leave>', lambda e: settings_btn.configure(fg="#8b949e"))

        # Edit Mode (Layout-Bearbeitung)
        self._edit_btn = tk.Label(
            title_frame, text="\U0001f512", fg="#8b949e", bg=self.TITLE_BG,
            font=("Segoe UI", 11), cursor="hand2"
        )
        self._edit_btn.pack(side=tk.RIGHT, padx=2)
        self._edit_btn.bind('<Button-1>', lambda e: self._toggle_edit_mode())
        self._edit_btn.bind('<Enter>', lambda e: self._edit_btn.configure(fg=self.ACCENT))
        self._edit_btn.bind('<Leave>', lambda e: self._edit_btn.configure(fg="#8b949e"))

    def _drag_start(self, event):
        self._drag_x = event.x_root - self.root.winfo_x()
        self._drag_y = event.y_root - self.root.winfo_y()

    def _drag_move(self, event):
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        if self._edit_mode:
            x, y = self._snap_to_grid(x, y)
        self.root.geometry(f"+{x}+{y}")
        self.config['overlay']['x'] = x
        self.config['overlay']['y'] = y
        # WoW-Offset aktualisieren wenn angeheftet
        if self.config['overlay'].get('attach_to_wow', True) and self._wow_last_rect:
            wx, wy = self._wow_last_rect[0], self._wow_last_rect[1]
            self.config['overlay']['wow_offset_x'] = x - wx
            self.config['overlay']['wow_offset_y'] = y - wy

    def _cycle_profile(self):
        """Wechselt zum nächsten Profil."""
        profiles = list(self.config.get('profiles', {}).keys())
        if len(profiles) <= 1:
            return
        current = self.config.get('active_profile', 'Standard')
        try:
            idx = profiles.index(current)
            next_idx = (idx + 1) % len(profiles)
        except ValueError:
            next_idx = 0
        new_profile = profiles[next_idx]
        self.config['active_profile'] = new_profile
        self._profile_label.configure(text=f"📋 {new_profile}")
        save_config(self.config)
        logger.info(f"Profil gewechselt: '{new_profile}'")
        # Buffs neu laden
        self._reload_buffs()

    def _reload_buffs(self):
        """Lädt Buffs des aktiven Profils neu."""
        for name in list(self.timer_widgets.keys()):
            self._remove_timer_widget(name)
        self.timers.clear()
        self._setup_buffs()
        self._register_hotkeys()

    def _setup_visual_countdown(self):
        """Erstellt das WeakAura-Style Countdown-Fenster (unsichtbar bis benötigt)."""
        if not self.config.get('visual_countdown', True):
            return
        self._countdown_window = tk.Toplevel(self.root)
        self._countdown_window.overrideredirect(True)
        self._countdown_window.attributes('-topmost', True)
        self._countdown_window.attributes('-alpha', 0.85)
        self._countdown_window.configure(bg='black')
        # Transparent-Farbe für durchsichtigen Hintergrund
        self._countdown_window.attributes('-transparentcolor', 'black')

        size = self.config.get('visual_countdown_size', 72)
        self._countdown_label = tk.Label(
            self._countdown_window, text="",
            fg="#ff4444", bg="black",
            font=("Impact", size, "bold")
        )
        self._countdown_label.pack()
        self._countdown_window.withdraw()  # Versteckt bis benötigt

        # Click-through: Mausklicks gehen durch das Fenster hindurch
        self._countdown_window.update_idletasks()
        try:
            hwnd = int(self._countdown_window.frame(), 16)
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            _GetWindowLongW = ctypes.windll.user32.GetWindowLongW
            _SetWindowLongW = ctypes.windll.user32.SetWindowLongW
            style = _GetWindowLongW(hwnd, GWL_EXSTYLE)
            _SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        except Exception:
            pass

    def _update_visual_countdown(self):
        """Aktualisiert den großen Countdown über dem Bildschirm."""
        if not self._countdown_window or not self.config.get('visual_countdown', True):
            return

        # Nicht zeigen wenn Overlay durch WoW-Tracking versteckt
        if self._wow_overlay_hidden:
            self._countdown_window.withdraw()
            return

        # Im Edit-Modus: Countdown wird manuell positioniert
        if self._edit_mode:
            return

        # Finde den Timer der am nächsten am Ablauf ist
        closest_name = None
        closest_remaining = float('inf')
        for name, data in self.timers.items():
            timer = data['timer']
            if timer.active and timer.remaining < closest_remaining:
                closest_remaining = timer.remaining
                closest_name = name

        # Countdown nur zeigen wenn <= 5 Sekunden verbleiben
        if closest_name and closest_remaining <= 5.0:
            countdown_text = f"{closest_remaining:.1f}"
            # Farbe basierend auf verbleibender Zeit
            if closest_remaining <= 2:
                color = "#ff0000"
            elif closest_remaining <= 3:
                color = "#ff4400"
            else:
                color = "#ff8800"

            self._countdown_label.configure(text=countdown_text, fg=color)

            # Position: benutzerdefiniert oder zentriert
            layout = self.config.get('layout', {})
            co_x = layout.get('countdown_offset_x')
            co_y = layout.get('countdown_offset_y')
            if co_x is not None and co_y is not None and self._wow_last_rect:
                cx = self._wow_last_rect[0] + co_x
                cy = self._wow_last_rect[1] + co_y
            elif self.config['overlay'].get('attach_to_wow', True) and self._wow_last_rect:
                wx, wy, ww, wh = self._wow_last_rect
                self._countdown_window.update_idletasks()
                cw = self._countdown_window.winfo_reqwidth()
                ch = self._countdown_window.winfo_reqheight()
                cx = wx + (ww - cw) // 2
                cy = wy + int(wh * 0.35) - ch // 2
            else:
                sw = self.root.winfo_screenwidth()
                sh = self.root.winfo_screenheight()
                self._countdown_window.update_idletasks()
                cw = self._countdown_window.winfo_reqwidth()
                ch = self._countdown_window.winfo_reqheight()
                cx = (sw - cw) // 2
                cy = int(sh * 0.35) - ch // 2

            self._countdown_window.geometry(f"+{cx}+{cy}")
            self._countdown_window.deiconify()
        else:
            self._countdown_window.withdraw()

    # ---- Layout / Edit Mode ----

    def _create_layout_elements(self):
        """Erstellt benutzerdefinierte Text-Elemente aus der Config."""
        for elem_cfg in self.config.get('layout', {}).get('elements', []):
            self._spawn_layout_element(elem_cfg)

    def _spawn_layout_element(self, elem_cfg):
        """Erstellt ein einzelnes Layout-Element als Toplevel-Fenster."""
        eid = elem_cfg.get('id', f"elem_{id(elem_cfg)}")
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.configure(bg='black')
        win.attributes('-transparentcolor', 'black')

        font_family = elem_cfg.get('font_family', 'Segoe UI')
        font_size = elem_cfg.get('font_size', 14)
        font_weight = elem_cfg.get('font_weight', 'bold')
        color = elem_cfg.get('color', '#ffffff')
        text = elem_cfg.get('text', 'Text')

        label = tk.Label(win, text=text, fg=color, bg='black',
                         font=(font_family, font_size, font_weight))
        label.pack()

        x_off = elem_cfg.get('x_offset', 100)
        y_off = elem_cfg.get('y_offset', 100)
        if self._wow_last_rect:
            wx, wy = self._wow_last_rect[0], self._wow_last_rect[1]
            win.geometry(f"+{wx + x_off}+{wy + y_off}")
        else:
            win.geometry(f"+{x_off}+{y_off}")

        if not self._edit_mode:
            self._make_click_through(win)

        self._layout_elements[eid] = {
            'window': win, 'label': label, 'config': elem_cfg
        }
        return eid

    def _make_click_through(self, window):
        """Macht ein Fenster klick-durchlässig via Windows API."""
        window.update_idletasks()
        try:
            hwnd = int(window.frame(), 16)
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        except Exception:
            pass

    def _remove_click_through(self, window):
        """Entfernt Klick-Durchlässigkeit."""
        window.update_idletasks()
        try:
            hwnd = int(window.frame(), 16)
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style & ~WS_EX_TRANSPARENT)
        except Exception:
            pass

    def _toggle_edit_mode(self):
        if self._edit_mode:
            self._exit_edit_mode(save=True)
        else:
            self._enter_edit_mode()

    def _enter_edit_mode(self):
        self._edit_mode = True
        self._edit_btn.configure(text="\U0001f513")
        logger.info("Edit Mode aktiviert")

        # Positionen sichern für Cancel
        self._edit_original_positions = {
            'overlay': (self.config['overlay'].get('wow_offset_x', 50),
                        self.config['overlay'].get('wow_offset_y', 50))
        }
        layout = self.config.get('layout', {})
        self._edit_original_positions['countdown'] = (
            layout.get('countdown_offset_x'),
            layout.get('countdown_offset_y'))
        for eid, elem in self._layout_elements.items():
            self._edit_original_positions[eid] = (
                elem['config']['x_offset'], elem['config']['y_offset'])
        self._edit_original_elements = json.loads(
            json.dumps(self.config.get('layout', {}).get('elements', [])))

        self._create_grid_overlay()
        self._create_edit_toolbar()
        self._enable_element_dragging()

    def _exit_edit_mode(self, save=True):
        if not save:
            # Positionen wiederherstellen
            if 'overlay' in self._edit_original_positions:
                ox, oy = self._edit_original_positions['overlay']
                self.config['overlay']['wow_offset_x'] = ox
                self.config['overlay']['wow_offset_y'] = oy
                if self._wow_last_rect:
                    wx, wy = self._wow_last_rect[0], self._wow_last_rect[1]
                    self.root.geometry(f"+{wx + ox}+{wy + oy}")
            if 'countdown' in self._edit_original_positions:
                co = self._edit_original_positions['countdown']
                self.config.setdefault('layout', {})['countdown_offset_x'] = co[0]
                self.config.setdefault('layout', {})['countdown_offset_y'] = co[1]
            # Layout-Elemente wiederherstellen
            for eid in list(self._layout_elements.keys()):
                self._layout_elements[eid]['window'].destroy()
            self._layout_elements.clear()
            self.config.setdefault('layout', {})['elements'] = self._edit_original_elements
            for elem_cfg in self._edit_original_elements:
                self._spawn_layout_element(elem_cfg)

        self._edit_mode = False
        self._edit_btn.configure(text="\U0001f512")
        logger.info(f"Edit Mode beendet (gespeichert={save})")

        self._destroy_grid_overlay()
        if self._edit_toolbar:
            self._edit_toolbar.destroy()
            self._edit_toolbar = None
        self._disable_element_dragging()

        if save:
            self.config.setdefault('layout', {})['elements'] = [
                elem['config'] for elem in self._layout_elements.values()]
            save_config(self.config)

    def _create_grid_overlay(self):
        """Erstellt Grid-Overlay über dem WoW-Fenster."""
        if self._edit_grid_window:
            return
        if self._wow_last_rect:
            x, y, w, h = self._wow_last_rect
        else:
            x, y = 0, 0
            w = self.root.winfo_screenwidth()
            h = self.root.winfo_screenheight()

        gs = self.config.get('layout', {}).get('grid_size', 20)
        self._edit_grid_window = tk.Toplevel(self.root)
        self._edit_grid_window.overrideredirect(True)
        self._edit_grid_window.attributes('-topmost', True)
        self._edit_grid_window.attributes('-alpha', 0.25)
        self._edit_grid_window.configure(bg='black')
        self._edit_grid_window.geometry(f"{w}x{h}+{x}+{y}")

        canvas = tk.Canvas(self._edit_grid_window, bg='black',
                           highlightthickness=0, width=w, height=h)
        canvas.pack(fill=tk.BOTH, expand=True)

        for gx in range(0, w, gs):
            canvas.create_line(gx, 0, gx, h, fill='#1a3a1a')
        for gy in range(0, h, gs):
            canvas.create_line(0, gy, w, gy, fill='#1a3a1a')

        cx, cy = w // 2, h // 2
        canvas.create_line(cx, 0, cx, h, fill='#2a5a2a', width=2)
        canvas.create_line(0, cy, w, cy, fill='#2a5a2a', width=2)

        self._make_click_through(self._edit_grid_window)
        self._edit_grid_window.lower()

    def _destroy_grid_overlay(self):
        if self._edit_grid_window:
            self._edit_grid_window.destroy()
            self._edit_grid_window = None

    def _update_grid(self):
        """Grid neu zeichnen nach Größenänderung."""
        try:
            self.config.setdefault('layout', {})['grid_size'] = self._grid_size_var.get()
        except (tk.TclError, ValueError):
            return
        self._destroy_grid_overlay()
        self._create_grid_overlay()

    def _create_edit_toolbar(self):
        """Erstellt die Bearbeitungsmodus-Toolbar."""
        if self._edit_toolbar:
            return
        if self._wow_last_rect:
            wx, wy, ww, wh = self._wow_last_rect
        else:
            wx, wy = 0, 0
            ww = self.root.winfo_screenwidth()

        self._edit_toolbar = tk.Toplevel(self.root)
        self._edit_toolbar.overrideredirect(True)
        self._edit_toolbar.attributes('-topmost', True)
        self._edit_toolbar.configure(bg='#1a1a2e',
                                      highlightbackground='#58a6ff', highlightthickness=1)

        tf = tk.Frame(self._edit_toolbar, bg='#1a1a2e')
        tf.pack(fill=tk.X, padx=10, pady=8)

        tk.Label(tf, text="\U0001f527 Bearbeitungsmodus", fg="#58a6ff", bg='#1a1a2e',
                 font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT, padx=(0, 15))

        tk.Label(tf, text="\U0001f4d0 Raster:", fg="#8b949e", bg='#1a1a2e',
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self._grid_size_var = tk.IntVar(
            value=self.config.get('layout', {}).get('grid_size', 20))
        tk.Spinbox(tf, from_=5, to=100, increment=5,
                   textvariable=self._grid_size_var, width=4,
                   bg="#161b22", fg="#e6edf3", font=("Segoe UI", 9),
                   command=self._update_grid, buttonbackground="#21262d"
                   ).pack(side=tk.LEFT, padx=(4, 15))

        tk.Button(tf, text="➕ Text", bg="#238636", fg="white",
                  font=("Segoe UI", 9, "bold"), relief="flat", cursor="hand2",
                  command=self._add_layout_element).pack(side=tk.LEFT, padx=4)

        tk.Button(tf, text="✅ Speichern", bg="#238636", fg="white",
                  font=("Segoe UI", 9, "bold"), relief="flat", cursor="hand2",
                  command=lambda: self._exit_edit_mode(save=True)
                  ).pack(side=tk.LEFT, padx=4)
        tk.Button(tf, text="❌ Abbrechen", bg="#da3633", fg="white",
                  font=("Segoe UI", 9), relief="flat", cursor="hand2",
                  command=lambda: self._exit_edit_mode(save=False)
                  ).pack(side=tk.LEFT, padx=4)

        self._edit_toolbar.update_idletasks()
        tw = self._edit_toolbar.winfo_reqwidth()
        self._edit_toolbar.geometry(f"+{wx + (ww - tw) // 2}+{wy + 5}")

    def _snap_to_grid(self, x, y):
        gs = max(1, self.config.get('layout', {}).get('grid_size', 20))
        return (round(x / gs) * gs, round(y / gs) * gs)

    def _enable_element_dragging(self):
        """Aktiviert Drag-Modus für alle positionierbaren Elemente."""
        self.root.configure(highlightbackground="#58a6ff", highlightthickness=2,
                            highlightcolor="#58a6ff")

        if self._countdown_window:
            self._countdown_label.configure(text="⏱", fg="#58a6ff")
            self._countdown_window.configure(highlightbackground="#58a6ff",
                                              highlightthickness=2,
                                              highlightcolor="#58a6ff")
            self._remove_click_through(self._countdown_window)
            layout = self.config.get('layout', {})
            co_x = layout.get('countdown_offset_x')
            co_y = layout.get('countdown_offset_y')
            if co_x is not None and co_y is not None and self._wow_last_rect:
                wx, wy = self._wow_last_rect[0], self._wow_last_rect[1]
                self._countdown_window.geometry(f"+{wx + co_x}+{wy + co_y}")
            elif self._wow_last_rect:
                wx, wy, ww, wh = self._wow_last_rect
                self._countdown_window.update_idletasks()
                cw = self._countdown_window.winfo_reqwidth()
                ch = self._countdown_window.winfo_reqheight()
                self._countdown_window.geometry(
                    f"+{wx + (ww - cw) // 2}+{wy + int(wh * 0.35)}")
            self._countdown_window.deiconify()
            self._setup_element_drag(self._countdown_window, 'countdown')

        for eid, elem in self._layout_elements.items():
            elem['window'].configure(highlightbackground="#58a6ff",
                                      highlightthickness=2,
                                      highlightcolor="#58a6ff")
            self._remove_click_through(elem['window'])
            self._setup_element_drag(elem['window'], eid)

    def _disable_element_dragging(self):
        """Deaktiviert Drag-Modus."""
        self.root.configure(highlightthickness=0)

        if self._countdown_window:
            self._countdown_window.configure(highlightthickness=0)
            self._countdown_label.configure(text="")
            self._countdown_window.withdraw()
            self._unbind_element_drag(self._countdown_window)
            self._make_click_through(self._countdown_window)

        for eid, elem in self._layout_elements.items():
            elem['window'].configure(highlightthickness=0)
            self._unbind_element_drag(elem['window'])
            self._make_click_through(elem['window'])

    def _setup_element_drag(self, window, element_id):
        """Richtet Drag&Drop für ein Element ein."""
        drag = {'x': 0, 'y': 0, 'id': element_id}

        def start(event):
            drag['x'] = event.x_root - window.winfo_x()
            drag['y'] = event.y_root - window.winfo_y()

        def move(event):
            nx, ny = self._snap_to_grid(
                event.x_root - drag['x'], event.y_root - drag['y'])
            window.geometry(f"+{nx}+{ny}")
            if self._wow_last_rect:
                xo = nx - self._wow_last_rect[0]
                yo = ny - self._wow_last_rect[1]
            else:
                xo, yo = nx, ny
            if drag['id'] == 'countdown':
                self.config.setdefault('layout', {})['countdown_offset_x'] = xo
                self.config.setdefault('layout', {})['countdown_offset_y'] = yo
            elif drag['id'] in self._layout_elements:
                self._layout_elements[drag['id']]['config']['x_offset'] = xo
                self._layout_elements[drag['id']]['config']['y_offset'] = yo

        def context(event):
            if drag['id'] in self._layout_elements:
                self._show_element_menu(event, drag['id'])

        for widget in [window] + list(window.winfo_children()):
            widget.bind('<Button-1>', start)
            widget.bind('<B1-Motion>', move)
            widget.bind('<Button-3>', context)

    def _unbind_element_drag(self, window):
        for ev in ('<Button-1>', '<B1-Motion>', '<Button-3>'):
            try:
                window.unbind(ev)
            except Exception:
                pass
            for child in window.winfo_children():
                try:
                    child.unbind(ev)
                except Exception:
                    pass

    def _show_element_menu(self, event, elem_id):
        """Rechtsklick-Kontextmenü für Layout-Elemente."""
        menu = tk.Menu(self.root, tearoff=0, bg="#21262d", fg="#e6edf3",
                       activebackground="#388bfd", activeforeground="white",
                       font=("Segoe UI", 10))
        menu.add_command(label="✏️ Bearbeiten",
                         command=lambda: self._edit_layout_element(elem_id))
        menu.add_separator()
        menu.add_command(label="🗑️ Entfernen",
                         command=lambda: self._delete_layout_element(elem_id))
        menu.tk_popup(event.x_root, event.y_root)

    def _add_layout_element(self):
        """Dialog zum Hinzufügen eines Text-Elements."""
        TextElementDialog(self.root, None, self._on_element_created)

    def _on_element_created(self, elem_cfg):
        if 'id' not in elem_cfg:
            elem_cfg['id'] = f"elem_{int(time.time() * 1000)}"
        if 'x_offset' not in elem_cfg:
            if self._wow_last_rect:
                elem_cfg['x_offset'] = self._wow_last_rect[2] // 2
                elem_cfg['y_offset'] = self._wow_last_rect[3] // 2
            else:
                elem_cfg['x_offset'] = 400
                elem_cfg['y_offset'] = 300
        eid = self._spawn_layout_element(elem_cfg)
        if self._edit_mode and eid in self._layout_elements:
            elem = self._layout_elements[eid]
            elem['window'].configure(highlightbackground="#58a6ff",
                                      highlightthickness=2, highlightcolor="#58a6ff")
            self._remove_click_through(elem['window'])
            self._setup_element_drag(elem['window'], eid)

    def _edit_layout_element(self, elem_id):
        if elem_id not in self._layout_elements:
            return
        TextElementDialog(self.root, self._layout_elements[elem_id]['config'],
                          lambda cfg: self._on_element_edited(elem_id, cfg))

    def _on_element_edited(self, elem_id, new_cfg):
        if elem_id not in self._layout_elements:
            return
        elem = self._layout_elements[elem_id]
        new_cfg['x_offset'] = elem['config']['x_offset']
        new_cfg['y_offset'] = elem['config']['y_offset']
        new_cfg['id'] = elem_id
        elem['label'].configure(
            text=new_cfg.get('text', 'Text'),
            fg=new_cfg.get('color', '#ffffff'),
            font=(new_cfg.get('font_family', 'Segoe UI'),
                  new_cfg.get('font_size', 14),
                  new_cfg.get('font_weight', 'bold')))
        elem['config'] = new_cfg

    def _delete_layout_element(self, elem_id):
        if elem_id not in self._layout_elements:
            return
        self._layout_elements[elem_id]['window'].destroy()
        del self._layout_elements[elem_id]

    def _check_update_async(self):
        """Startet Update-Check im Hintergrund."""
        def _check():
            result = check_for_updates()
            if result:
                version, url = result
                self.root.after(0, lambda: self._show_update_notification(version, url))
        threading.Thread(target=_check, daemon=True).start()

    def _show_update_notification(self, version, url):
        """Zeigt Update-Benachrichtigung."""
        if messagebox.askyesno(
            "Update verfügbar",
            f"Neue Version {version} verfügbar!\n\n"
            f"Aktuelle Version: {CURRENT_VERSION}\n\n"
            f"Jetzt herunterladen?",
            parent=self.root
        ):
            os.startfile(url)

    def _setup_buffs(self):
        for buff_cfg in get_active_buffs(self.config):
            name = buff_cfg['name']
            alert_before = buff_cfg.get('alert_before', 0)
            timer = BuffTimer(name, buff_cfg['duration'], buff_cfg['max_duration'], alert_before)
            self.timers[name] = {
                'timer': timer,
                'config': buff_cfg
            }

    def _register_hotkeys(self):
        # Alte Keyboard-Hooks entfernen
        for hook_type, hook in self.hotkey_hooks:
            try:
                if hook_type == 'keyboard':
                    keyboard.unhook(hook)
            except Exception:
                pass
        self.hotkey_hooks.clear()

        self._mouse_poll_bindings = []
        self._mouse_prev_state = {}
        self._keyboard_bindings = []

        for name, data in self.timers.items():
            hotkey = data['config']['hotkey']
            try:
                self._register_single_hotkey(name, hotkey)
                logger.info(f"Hotkey registriert: '{hotkey}' -> '{name}'")
            except Exception as ex:
                logger.error(f"Hotkey '{hotkey}' für '{name}' fehlgeschlagen: {ex}")
                print(f"Hotkey '{hotkey}' für '{name}' konnte nicht registriert werden: {ex}")

        # Einen einzigen Keyboard-Hook für alle Tasten-Bindings
        if self._keyboard_bindings:
            def global_keyboard_callback(event):
                key_name = (event.name or '').lower()
                scan = event.scan_code

                # Bei Key-Up: Taste als losgelassen markieren
                if event.event_type == 'up':
                    with self._keys_held_lock:
                        self._keys_held.discard(('kb_scan', scan))
                        self._keys_held.discard(('kb_name', key_name))
                    return

                if event.event_type != 'down':
                    return

                for binding in self._keyboard_bindings:
                    trigger_match = False
                    held_key = None
                    if binding.get('scan_code') and scan == binding['scan_code']:
                        trigger_match = True
                        held_key = ('kb_scan', scan)
                    elif key_name == binding['trigger_lower']:
                        trigger_match = True
                        held_key = ('kb_name', key_name)
                    if trigger_match:
                        # Ignoriere wiederholte Down-Events (Taste gedrückt halten)
                        with self._keys_held_lock:
                            if held_key in self._keys_held:
                                continue
                            self._keys_held.add(held_key)
                        mods_ok = True
                        for mod in binding['modifiers']:
                            try:
                                if not keyboard.is_pressed(mod):
                                    mods_ok = False
                                    break
                            except Exception:
                                mods_ok = False
                                break
                        if mods_ok:
                            self._on_hotkey(binding['name'])
            hook = keyboard.hook(global_keyboard_callback, suppress=False)
            self.hotkey_hooks.append(('keyboard', hook))

        # Maustasten-Polling starten (ersetzt mouse.hook - viel zuverlässiger)
        if self._mouse_poll_bindings:
            logger.info(f"Maustasten-Polling aktiv für {len(self._mouse_poll_bindings)} Binding(s)")
            self._poll_mouse()

    def _register_single_hotkey(self, buff_name, hotkey_str):
        """Registriert einen einzelnen Hotkey (Keyboard, Maus oder Kombi)."""
        parts = [p.strip() for p in hotkey_str.split('+')]
        modifiers = []
        trigger = None
        is_mouse = False

        for part in parts:
            if part.lower() in ('ctrl', 'shift', 'alt'):
                modifiers.append(part.lower())
            elif part.upper() in MOUSE_DISPLAY_TO_INTERNAL:
                trigger = part.upper()
                is_mouse = True
            else:
                trigger = part

        if not trigger:
            return

        if is_mouse and trigger.upper() in MOUSE_VK_CODES:
            vk = MOUSE_VK_CODES[trigger.upper()]
            mod_vks = [MODIFIER_VK_CODES[m] for m in modifiers if m in MODIFIER_VK_CODES]
            self._mouse_poll_bindings.append({
                'name': buff_name,
                'vk': vk,
                'display': trigger.upper(),
                'mod_vks': mod_vks,
                'modifiers': modifiers
            })
            self._mouse_prev_state[vk] = False
        elif not is_mouse:
            # Scan-Code ermitteln für zuverlässigere Erkennung
            scan_code = None
            try:
                scan_code = keyboard.key_to_scan_codes(trigger)[0]
            except Exception:
                pass
            self._keyboard_bindings.append({
                'name': buff_name,
                'trigger_lower': trigger.lower(),
                'scan_code': scan_code,
                'modifiers': modifiers
            })

    def _on_hotkey(self, buff_name):
        """Thread-sicher: Event in Queue legen, wird im Main-Thread verarbeitet."""
        logger.debug(f"TASTE erkannt für '{buff_name}'")
        self._pending_activations.append(buff_name)

    def _poll_mouse(self):
        """Pollt Maustasten via GetAsyncKeyState - läuft im Tkinter Main-Thread."""
        for binding in self._mouse_poll_bindings:
            vk = binding['vk']
            pressed = is_key_pressed(vk)
            was_pressed = self._mouse_prev_state.get(vk, False)

            if pressed and not was_pressed:
                # Flanke: nicht gedrückt -> gedrückt = neuer Klick
                mods_ok = True
                for mod_vk in binding['mod_vks']:
                    if not is_key_pressed(mod_vk):
                        mods_ok = False
                        break
                if mods_ok:
                    logger.debug(f"MOUSE-POLL: {binding['display']} erkannt für '{binding['name']}'")
                    if binding['name'] in self.timers:
                        self.timers[binding['name']]['timer'].activate()

            self._mouse_prev_state[vk] = pressed

        # Alle 20ms erneut pollen (schnell genug für Spam-Klicks)
        self.root.after(20, self._poll_mouse)

    def _get_bar_color(self, ratio):
        if ratio > 0.5:
            return self.GREEN
        elif ratio > 0.25:
            return self.YELLOW
        else:
            return self.RED

    def _ensure_timer_widget(self, name, timer, config):
        """Erstellt oder aktualisiert Widgets für einen Timer."""
        bar_h = self.config['overlay']['bar_height']
        font_size = self.config['overlay']['font_size']

        if name not in self.timer_widgets:
            frame = tk.Frame(self.timer_frame, bg=self.BG_COLOR)
            frame.pack(fill=tk.X, pady=2)

            name_label = tk.Label(
                frame, text=name, fg=self.TEXT_COLOR, bg=self.BG_COLOR,
                font=("Segoe UI", font_size, "bold"), anchor="w"
            )
            name_label.pack(fill=tk.X)

            bar_outer = tk.Frame(frame, bg=self.BAR_BG, height=bar_h)
            bar_outer.pack(fill=tk.X, pady=(1, 0))
            bar_outer.pack_propagate(False)

            bar_fill = tk.Frame(bar_outer, bg=self.GREEN, height=bar_h)
            bar_fill.place(relx=0, rely=0, relwidth=1, relheight=1)

            time_label = tk.Label(
                bar_outer, text="", fg="white", bg=self.GREEN,
                font=("Segoe UI", 10, "bold")
            )
            time_label.place(relx=0.5, rely=0.5, anchor="center")

            self.timer_widgets[name] = {
                'frame': frame,
                'name_label': name_label,
                'bar_outer': bar_outer,
                'bar_fill': bar_fill,
                'time_label': time_label
            }

        # Update
        w = self.timer_widgets[name]
        if timer.active:
            remaining = timer.remaining
            ratio = remaining / timer.max_duration if timer.max_duration > 0 else 0
            color = self._get_bar_color(ratio)

            w['bar_fill'].configure(bg=color)
            w['bar_fill'].place(relwidth=max(ratio, 0.01))
            w['time_label'].configure(
                text=f"{remaining:.1f}s",
                bg=color, fg="white"
            )
            w['name_label'].configure(fg=self.TEXT_COLOR)
        elif timer.expired_at is not None:
            # Blinken
            flash = int((time.time() - timer.expired_at) * 4) % 2
            color = self.EXPIRED_COLOR if flash == 0 else "#8b0000"
            w['bar_fill'].configure(bg=color)
            w['bar_fill'].place(relwidth=1)
            w['time_label'].configure(text="⚠ ERNEUERN!", bg=color, fg="white")
            w['name_label'].configure(fg=self.EXPIRED_COLOR)

    def _remove_timer_widget(self, name):
        if name in self.timer_widgets:
            self.timer_widgets[name]['frame'].destroy()
            del self.timer_widgets[name]

    def _update(self):
        # Verarbeite ausstehende Hotkey-Aktivierungen (thread-sicher)
        while self._pending_activations:
            try:
                buff_name = self._pending_activations.popleft()
                if buff_name in self.timers:
                    data = self.timers[buff_name]
                    cfg = data['config']
                    # Dependency-Check: abhängiger Buff muss aktiv sein
                    depends_on = cfg.get('depends_on', '')
                    if depends_on and depends_on in self.timers:
                        dep_timer = self.timers[depends_on]['timer']
                        if not dep_timer.active:
                            logger.debug(f"BLOCKIERT '{buff_name}': Abhängigkeit '{depends_on}' nicht aktiv")
                            continue
                    data['timer'].activate()
            except IndexError:
                break

        expired_display = self.config.get('expired_display_seconds', 4)
        any_showing = False

        for name, data in list(self.timers.items()):
            timer = data['timer']
            cfg = data['config']

            # Prüfe auf Früh-Alarm (X Sek. vor Ablauf)
            early_alert = timer.check_early_alert()
            if early_alert:
                self._alert(name, cfg)

            # Prüfe auf Expiration
            just_expired = timer.check_expired()
            if just_expired:
                # Nur alarmieren wenn kein Früh-Alarm konfiguriert
                if cfg.get('alert_before', 0) <= 0:
                    self._alert(name, cfg)

            # Expired-Anzeige aufräumen
            timer.clear_expired(expired_display)

            if timer.is_showing:
                any_showing = True
                self._ensure_timer_widget(name, timer, cfg)
            else:
                self._remove_timer_widget(name)

        # Idle-Label
        if any_showing:
            self.idle_label.pack_forget()
        else:
            if not self.idle_label.winfo_ismapped():
                self.idle_label.pack(pady=4)

        # Fenstergröße anpassen
        self._resize_window(any_showing)

        # Visueller Countdown aktualisieren
        self._update_visual_countdown()

        # WoW-Fenster Tracking: Overlay mitbewegen
        self._track_wow_window()

        self.root.after(50, self._update)

    def _resize_window(self, has_active):
        w = self.config['overlay']['width']
        if has_active:
            count = sum(1 for d in self.timers.values() if d['timer'].is_showing)
            bar_h = self.config['overlay']['bar_height']
            font_h = self.config['overlay']['font_size'] + 6
            h = 34 + count * (bar_h + font_h + 12) + 8
        else:
            h = 64
        self.root.geometry(f"{w}x{h}")

    def _get_own_hwnds(self):
        """Gibt eine Menge aller eigenen Fenster-HWNDs zurück (Overlay, Countdown, Dialoge, Layout-Elemente)."""
        hwnds = set()
        try:
            hwnds.add(int(self.root.frame(), 16))
        except Exception:
            pass
        if self._countdown_window:
            try:
                hwnds.add(int(self._countdown_window.frame(), 16))
            except Exception:
                pass
        # Alle offenen Toplevel-Fenster erfassen (ConfigDialog, BuffEditDialog, etc.)
        for w in self.root.winfo_children():
            if isinstance(w, tk.Toplevel):
                try:
                    hwnds.add(int(w.frame(), 16))
                except Exception:
                    pass
        # Layout-Elemente (können von root losgelöst sein)
        for elem in self._layout_elements.values():
            try:
                hwnds.add(int(elem['window'].frame(), 16))
            except Exception:
                pass
        # Edit-Mode Fenster
        if self._edit_grid_window:
            try:
                hwnds.add(int(self._edit_grid_window.frame(), 16))
            except Exception:
                pass
        if self._edit_toolbar:
            try:
                hwnds.add(int(self._edit_toolbar.frame(), 16))
            except Exception:
                pass
        return hwnds

    def _hide_all_ui(self):
        """Versteckt ALLE UI-Elemente (Overlay, Countdown, offene Dialoge, Layout-Elemente)."""
        if self._wow_overlay_hidden:
            return
        self.root.withdraw()
        if self._countdown_window:
            self._countdown_window.withdraw()
        for w in self.root.winfo_children():
            if isinstance(w, tk.Toplevel):
                w.withdraw()
        for elem in self._layout_elements.values():
            try:
                elem['window'].withdraw()
            except Exception:
                pass
        self._wow_overlay_hidden = True

    def _show_all_ui(self):
        """Zeigt ALLE UI-Elemente wieder an."""
        if not self._wow_overlay_hidden:
            return
        self.root.deiconify()
        self.root.attributes('-topmost', True)
        for w in self.root.winfo_children():
            if isinstance(w, tk.Toplevel) and w != self._countdown_window:
                w.deiconify()
                w.attributes('-topmost', True)
        # Layout-Elemente wieder zeigen
        for elem in self._layout_elements.values():
            try:
                elem['window'].deiconify()
                elem['window'].attributes('-topmost', True)
            except Exception:
                pass
        # Countdown wird von _update_visual_countdown() gesteuert
        self._wow_overlay_hidden = False

    def _track_wow_window(self):
        """Prüft ob sich das WoW-Fenster bewegt hat und zieht das Overlay mit.
        Versteckt das Overlay wenn WoW minimiert oder verdeckt ist."""
        # Im Edit-Mode kein Fokus-Tracking - sonst verschwindet alles beim Klick
        if self._edit_mode:
            return

        if not self.config['overlay'].get('attach_to_wow', True):
            # Wenn abgekoppelt, sicherstellen dass es sichtbar ist
            if self._wow_overlay_hidden:
                self._show_all_ui()
            return

        wow = find_wow_window()
        if not wow:
            # WoW nicht (mehr) gefunden -> alles verstecken
            if self._wow_hwnd is not None:
                logger.info("WoW-Fenster verloren - UI wird ausgeblendet")
                self._wow_hwnd = None
                self._wow_last_rect = None
            self._hide_all_ui()
            return

        hwnd, wx, wy, ww, wh = wow

        # Prüfe ob WoW minimiert ist
        if _IsIconic(hwnd):
            self._hide_all_ui()
            return

        # Prüfe ob WoW im Vordergrund ist
        fg_hwnd = _GetForegroundWindow()
        own_hwnds = self._get_own_hwnds()
        wow_is_active = (fg_hwnd == hwnd) or (fg_hwnd in own_hwnds)

        if not wow_is_active:
            # Anderes Fenster ist im Vordergrund -> alles verstecken
            self._hide_all_ui()
            return

        # WoW ist sichtbar und aktiv -> alles zeigen
        if self._wow_overlay_hidden:
            self._show_all_ui()

        if self._wow_hwnd is None:
            # WoW gerade erst gefunden
            self._wow_hwnd = hwnd
            self._wow_last_rect = (wx, wy, ww, wh)
            # Overlay an WoW-Position setzen
            ox = wx + self.config['overlay'].get('wow_offset_x', 50)
            oy = wy + self.config['overlay'].get('wow_offset_y', 50)
            self.root.geometry(f"+{ox}+{oy}")
            # Layout-Elemente positionieren
            for eid, elem in self._layout_elements.items():
                ex = wx + elem['config']['x_offset']
                ey = wy + elem['config']['y_offset']
                elem['window'].geometry(f"+{ex}+{ey}")
            logger.info(f"WoW-Fenster gefunden, Overlay angeheftet")
            return

        new_rect = (wx, wy, ww, wh)
        if self._wow_last_rect and (new_rect[0] != self._wow_last_rect[0] or
                                     new_rect[1] != self._wow_last_rect[1]):
            # WoW hat sich bewegt -> Overlay mitziehen
            dx = wx - self._wow_last_rect[0]
            dy = wy - self._wow_last_rect[1]
            cur_x = self.root.winfo_x()
            cur_y = self.root.winfo_y()
            new_x = cur_x + dx
            new_y = cur_y + dy
            self.root.geometry(f"+{new_x}+{new_y}")
            self.config['overlay']['x'] = new_x
            self.config['overlay']['y'] = new_y
            # Layout-Elemente mitziehen
            for eid, elem in self._layout_elements.items():
                ex = elem['window'].winfo_x() + dx
                ey = elem['window'].winfo_y() + dy
                elem['window'].geometry(f"+{ex}+{ey}")

        self._wow_last_rect = new_rect
        self._wow_hwnd = hwnd

    def _alert(self, buff_name, config):
        if config.get('sound', True):
            sound_file = config.get('sound_file', '')
            if sound_file and os.path.isfile(sound_file):
                # Eigene .wav-Datei abspielen
                threading.Thread(
                    target=lambda sf=sound_file: winsound.PlaySound(
                        sf, winsound.SND_FILENAME
                    ),
                    daemon=True
                ).start()
            else:
                freq = self.config.get('alert_sound_freq', 880)
                dur = self.config.get('alert_sound_duration', 400)
                threading.Thread(
                    target=lambda: winsound.Beep(freq, dur),
                    daemon=True
                ).start()

        if config.get('tts', True) and self.tts_worker:
            self.tts_worker.speak(f"{buff_name} erneuern!")

    # ---- Config-Dialog ----

    def _open_config(self):
        ConfigDialog(self.root, self.config, self._apply_config)

    def _apply_config(self, new_config):
        self.config = new_config
        save_config(self.config)

        # Alte Widgets und Timer aufräumen
        for name in list(self.timer_widgets.keys()):
            self._remove_timer_widget(name)
        self.timers.clear()

        # Neu aufsetzen
        self._setup_buffs()
        self._register_hotkeys()

        # Overlay anpassen
        self.root.attributes('-alpha', self.config['overlay']['opacity'])

        # Profil-Label aktualisieren
        profile_name = self.config.get('active_profile', 'Standard')
        self._profile_label.configure(text=f"📋 {profile_name}")

    def _quit(self):
        save_config(self.config)
        for hook_type, hook in self.hotkey_hooks:
            try:
                if hook_type == 'keyboard':
                    keyboard.unhook(hook)
            except Exception:
                pass
        if self.tts_worker:
            self.tts_worker.stop()
        if self._countdown_window:
            try:
                self._countdown_window.destroy()
            except Exception:
                pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


class ConfigDialog:
    """Konfigurations-Fenster für Buff-Einstellungen mit Profil-Support."""

    def __init__(self, parent, config, on_save):
        self.config = json.loads(json.dumps(config))  # Deep copy
        self.on_save = on_save

        self.win = tk.Toplevel(parent)
        self.win.title(f"⚙ WoWra - Einstellungen  v{CURRENT_VERSION}")
        self.win.geometry("540x700")
        self.win.configure(bg="#0d1117")
        self.win.attributes('-topmost', True)
        self.win.resizable(False, False)

        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Dark.TFrame", background="#0d1117")
        style.configure("Dark.TLabel", background="#0d1117", foreground="#e6edf3",
                         font=("Segoe UI", 10))
        style.configure("Dark.TButton", background="#21262d", foreground="#e6edf3",
                         font=("Segoe UI", 10))
        style.configure("Accent.TButton", background="#238636", foreground="white",
                         font=("Segoe UI", 10, "bold"))

        # Scrollbarer Hauptbereich
        canvas = tk.Canvas(self.win, bg="#0d1117", highlightthickness=0)
        scrollbar = tk.Scrollbar(self.win, orient="vertical", command=canvas.yview)
        main_frame = tk.Frame(canvas, bg="#0d1117")
        main_frame.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=main_frame, anchor="nw", width=510)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=15, pady=10)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        # Mausrad-Scroll
        canvas.bind_all('<MouseWheel>', lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        # === PROFIL-SEKTION ===
        tk.Label(main_frame, text="📋 Profile:", fg="#58a6ff",
                 bg="#0d1117", font=("Segoe UI", 12, "bold")).pack(anchor="w")

        profile_row = tk.Frame(main_frame, bg="#0d1117")
        profile_row.pack(fill=tk.X, pady=(5, 5))

        tk.Label(profile_row, text="Aktiv:", fg="#e6edf3",
                 bg="#0d1117", font=("Segoe UI", 10)).pack(side=tk.LEFT)

        self.profile_var = tk.StringVar(value=self.config.get('active_profile', 'Standard'))
        profile_names = list(self.config.get('profiles', {}).keys())
        self.profile_menu = ttk.Combobox(
            profile_row, textvariable=self.profile_var,
            values=profile_names, state="readonly", width=20
        )
        self.profile_menu.pack(side=tk.LEFT, padx=8)
        self.profile_menu.bind('<<ComboboxSelected>>', lambda e: self._on_profile_changed())

        tk.Button(profile_row, text="➕ Neu", bg="#238636", fg="white",
                  font=("Segoe UI", 8, "bold"), relief="flat", cursor="hand2",
                  command=self._new_profile).pack(side=tk.LEFT, padx=2)
        tk.Button(profile_row, text="📋 Kopie", bg="#21262d", fg="#e6edf3",
                  font=("Segoe UI", 8), relief="flat", cursor="hand2",
                  command=self._copy_profile).pack(side=tk.LEFT, padx=2)
        tk.Button(profile_row, text="🗑️", bg="#da3633", fg="white",
                  font=("Segoe UI", 8), relief="flat", cursor="hand2",
                  command=self._delete_profile).pack(side=tk.LEFT, padx=2)

        tk.Frame(main_frame, bg="#30363d", height=1).pack(fill=tk.X, pady=8)

        # === BUFF-LISTE ===
        tk.Label(main_frame, text="Konfigurierte Buffs:", fg="#58a6ff",
                 bg="#0d1117", font=("Segoe UI", 12, "bold")).pack(anchor="w")

        self.buff_listbox = tk.Listbox(
            main_frame, bg="#161b22", fg="#e6edf3",
            selectbackground="#388bfd", selectforeground="white",
            font=("Segoe UI", 11), height=6, relief="flat", bd=0
        )
        self.buff_listbox.pack(fill=tk.X, pady=(5, 5))
        self._refresh_list()

        btn_row = tk.Frame(main_frame, bg="#0d1117")
        btn_row.pack(fill=tk.X, pady=(0, 10))

        tk.Button(btn_row, text="➕ Hinzufügen", bg="#238636", fg="white",
                  font=("Segoe UI", 9, "bold"), relief="flat", cursor="hand2",
                  command=self._add_buff).pack(side=tk.LEFT, padx=(0, 5))
        tk.Button(btn_row, text="✏️ Bearbeiten", bg="#21262d", fg="#e6edf3",
                  font=("Segoe UI", 9), relief="flat", cursor="hand2",
                  command=self._edit_buff).pack(side=tk.LEFT, padx=(0, 5))
        tk.Button(btn_row, text="🗑️ Entfernen", bg="#da3633", fg="white",
                  font=("Segoe UI", 9), relief="flat", cursor="hand2",
                  command=self._remove_buff).pack(side=tk.LEFT)

        # Separator
        tk.Frame(main_frame, bg="#30363d", height=1).pack(fill=tk.X, pady=8)

        # Allgemeine Einstellungen
        tk.Label(main_frame, text="Allgemeine Einstellungen:", fg="#58a6ff",
                 bg="#0d1117", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 5))

        settings_grid = tk.Frame(main_frame, bg="#0d1117")
        settings_grid.pack(fill=tk.X)

        # Opacity
        row = 0
        tk.Label(settings_grid, text="Overlay Transparenz:", fg="#e6edf3",
                 bg="#0d1117", font=("Segoe UI", 10)).grid(row=row, column=0, sticky="w", pady=3)
        self.opacity_var = tk.DoubleVar(value=self.config['overlay']['opacity'])
        opacity_scale = tk.Scale(
            settings_grid, from_=0.3, to=1.0, resolution=0.05,
            orient=tk.HORIZONTAL, variable=self.opacity_var,
            bg="#0d1117", fg="#e6edf3", troughcolor="#21262d",
            highlightthickness=0, length=200
        )
        opacity_scale.grid(row=row, column=1, sticky="w", padx=10)

        # Sound Frequenz
        row += 1
        tk.Label(settings_grid, text="Alert Sound (Hz):", fg="#e6edf3",
                 bg="#0d1117", font=("Segoe UI", 10)).grid(row=row, column=0, sticky="w", pady=3)
        self.freq_var = tk.IntVar(value=self.config.get('alert_sound_freq', 880))
        tk.Entry(settings_grid, textvariable=self.freq_var, bg="#161b22", fg="#e6edf3",
                 font=("Segoe UI", 10), relief="flat", width=8, insertbackground="#e6edf3"
                 ).grid(row=row, column=1, sticky="w", padx=10)

        # An WoW anheften
        row += 1
        tk.Label(settings_grid, text="An WoW-Fenster anheften:", fg="#e6edf3",
                 bg="#0d1117", font=("Segoe UI", 10)).grid(row=row, column=0, sticky="w", pady=3)
        self.attach_wow_var = tk.BooleanVar(value=self.config['overlay'].get('attach_to_wow', True))
        tk.Checkbutton(
            settings_grid, variable=self.attach_wow_var,
            bg="#0d1117", fg="#e6edf3", selectcolor="#161b22",
            activebackground="#0d1117", activeforeground="#e6edf3"
        ).grid(row=row, column=1, sticky="w", padx=10)

        # Expired Display
        row += 1
        tk.Label(settings_grid, text="Ablauf-Anzeige (Sek.):", fg="#e6edf3",
                 bg="#0d1117", font=("Segoe UI", 10)).grid(row=row, column=0, sticky="w", pady=3)
        self.expired_var = tk.IntVar(value=self.config.get('expired_display_seconds', 4))
        tk.Entry(settings_grid, textvariable=self.expired_var, bg="#161b22", fg="#e6edf3",
                 font=("Segoe UI", 10), relief="flat", width=8, insertbackground="#e6edf3"
                 ).grid(row=row, column=1, sticky="w", padx=10)

        # Visueller Countdown
        row += 1
        tk.Label(settings_grid, text="Visueller Countdown:", fg="#e6edf3",
                 bg="#0d1117", font=("Segoe UI", 10)).grid(row=row, column=0, sticky="w", pady=3)
        self.visual_cd_var = tk.BooleanVar(value=self.config.get('visual_countdown', True))
        tk.Checkbutton(
            settings_grid, variable=self.visual_cd_var,
            bg="#0d1117", fg="#e6edf3", selectcolor="#161b22",
            activebackground="#0d1117", activeforeground="#e6edf3",
            text="Großer Countdown (letzte 5 Sek.)"
        ).grid(row=row, column=1, sticky="w", padx=10)

        # Speichern-Button
        tk.Button(main_frame, text="💾 Speichern & Anwenden", bg="#238636", fg="white",
                  font=("Segoe UI", 11, "bold"), relief="flat", cursor="hand2",
                  padx=20, pady=6, command=self._save).pack(pady=(20, 0))

        # Version-Anzeige
        tk.Label(main_frame, text=f"WoWra v{CURRENT_VERSION}",
                 fg="#484f58", bg="#0d1117",
                 font=("Segoe UI", 9, "italic")).pack(pady=(12, 4))

    def _get_active_buffs(self):
        """Gibt die Buff-Liste des im Dialog gewählten Profils zurück."""
        pname = self.profile_var.get()
        return self.config.get('profiles', {}).get(pname, {}).get('buffs', [])

    def _set_active_buffs(self, buffs):
        """Setzt die Buff-Liste des im Dialog gewählten Profils."""
        pname = self.profile_var.get()
        self.config.setdefault('profiles', {}).setdefault(pname, {})['buffs'] = buffs

    def _refresh_list(self):
        self.buff_listbox.delete(0, tk.END)
        for buff in self._get_active_buffs():
            sound = "🔊" if buff.get('sound', True) else "🔇"
            tts = "🗣️" if buff.get('tts', True) else ""
            alert_b = buff.get('alert_before', 0)
            alert_txt = f"  ⏰{alert_b}s vorher" if alert_b > 0 else ""
            dep = buff.get('depends_on', '')
            dep_txt = f"  🔗{dep}" if dep else ""
            snd = buff.get('sound_file', '')
            snd_txt = f"  🎵" if snd else ""
            text = (f"{buff['name']}  |  [{buff['hotkey']}]  |  "
                    f"{buff['duration']}s / max {buff['max_duration']}s  "
                    f"{sound} {tts}{alert_txt}{dep_txt}{snd_txt}")
            self.buff_listbox.insert(tk.END, text)

    def _on_profile_changed(self):
        self._refresh_list()

    def _new_profile(self):
        name = simpledialog.askstring("Neues Profil", "Profilname:", parent=self.win)
        if not name or not name.strip():
            return
        name = name.strip()
        if name in self.config.get('profiles', {}):
            messagebox.showwarning("Existiert", f"Profil '{name}' existiert bereits.", parent=self.win)
            return
        self.config.setdefault('profiles', {})[name] = {"buffs": []}
        self.profile_var.set(name)
        self.profile_menu['values'] = list(self.config['profiles'].keys())
        self._refresh_list()

    def _copy_profile(self):
        current = self.profile_var.get()
        name = simpledialog.askstring("Profil kopieren", "Name der Kopie:", parent=self.win,
                                          initialvalue=f"{current} (Kopie)")
        if not name or not name.strip():
            return
        name = name.strip()
        if name in self.config.get('profiles', {}):
            messagebox.showwarning("Existiert", f"Profil '{name}' existiert bereits.", parent=self.win)
            return
        source = self.config.get('profiles', {}).get(current, {"buffs": []})
        self.config['profiles'][name] = json.loads(json.dumps(source))
        self.profile_var.set(name)
        self.profile_menu['values'] = list(self.config['profiles'].keys())
        self._refresh_list()

    def _delete_profile(self):
        profiles = self.config.get('profiles', {})
        if len(profiles) <= 1:
            messagebox.showwarning("Nicht möglich", "Das letzte Profil kann nicht gelöscht werden.", parent=self.win)
            return
        current = self.profile_var.get()
        if messagebox.askyesno("Profil löschen", f"Profil '{current}' wirklich löschen?", parent=self.win):
            del profiles[current]
            first = next(iter(profiles.keys()))
            self.profile_var.set(first)
            self.profile_menu['values'] = list(profiles.keys())
            self._refresh_list()

    def _add_buff(self):
        BuffEditDialog(self.win, None, self._on_buff_saved, self._get_all_buff_names())

    def _edit_buff(self):
        sel = self.buff_listbox.curselection()
        if not sel:
            messagebox.showwarning("Auswahl", "Bitte einen Buff auswählen.", parent=self.win)
            return
        idx = sel[0]
        buffs = self._get_active_buffs()
        BuffEditDialog(self.win, buffs[idx], lambda b: self._on_buff_saved(b, idx), self._get_all_buff_names())

    def _get_all_buff_names(self):
        """Gibt alle Buff-Namen des aktiven Profils zurück (für Dependency-Dropdown)."""
        return [b['name'] for b in self._get_active_buffs()]

    def _on_buff_saved(self, buff_data, replace_idx=None):
        buffs = self._get_active_buffs()
        if replace_idx is not None:
            buffs[replace_idx] = buff_data
        else:
            buffs.append(buff_data)
        self._set_active_buffs(buffs)
        self._refresh_list()

    def _remove_buff(self):
        sel = self.buff_listbox.curselection()
        if not sel:
            messagebox.showwarning("Auswahl", "Bitte einen Buff auswählen.", parent=self.win)
            return
        idx = sel[0]
        buffs = self._get_active_buffs()
        name = buffs[idx]['name']
        if messagebox.askyesno("Entfernen", f"'{name}' wirklich entfernen?", parent=self.win):
            buffs.pop(idx)
            self._set_active_buffs(buffs)
            self._refresh_list()

    def _save(self):
        self.config['active_profile'] = self.profile_var.get()
        self.config['overlay']['opacity'] = self.opacity_var.get()
        self.config['overlay']['attach_to_wow'] = self.attach_wow_var.get()
        self.config['alert_sound_freq'] = self.freq_var.get()
        self.config['expired_display_seconds'] = self.expired_var.get()
        self.config['visual_countdown'] = self.visual_cd_var.get()
        self.on_save(self.config)
        self.win.destroy()


class BuffEditDialog:
    """Dialog zum Erstellen/Bearbeiten eines einzelnen Buffs."""

    def __init__(self, parent, buff_data, on_save, all_buff_names=None):
        self.on_save = on_save
        self.is_edit = buff_data is not None
        self.all_buff_names = all_buff_names or []

        self.win = tk.Toplevel(parent)
        self.win.title("Buff bearbeiten" if self.is_edit else "Neuen Buff hinzufügen")
        self.win.geometry("420x560")
        self.win.configure(bg="#0d1117")
        self.win.attributes('-topmost', True)
        self.win.resizable(False, False)

        frame = tk.Frame(self.win, bg="#0d1117")
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)

        defaults = buff_data or DEFAULT_BUFF.copy()
        defaults = {**DEFAULT_BUFF, **defaults}  # Merge mit Defaults

        # Name
        tk.Label(frame, text="Buff-Name:", fg="#e6edf3", bg="#0d1117",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 2))
        self.name_var = tk.StringVar(value=defaults['name'])
        tk.Entry(frame, textvariable=self.name_var, bg="#161b22", fg="#e6edf3",
                 font=("Segoe UI", 11), relief="flat", insertbackground="#e6edf3"
                 ).pack(fill=tk.X, pady=(0, 8))

        # Hotkey mit Recorder
        tk.Label(frame, text="Hotkey:", fg="#e6edf3",
                 bg="#0d1117", font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 2))
        hotkey_row = tk.Frame(frame, bg="#0d1117")
        hotkey_row.pack(fill=tk.X, pady=(0, 8))

        self.hotkey_var = tk.StringVar(value=defaults['hotkey'])
        self.hotkey_entry = tk.Entry(
            hotkey_row, textvariable=self.hotkey_var, bg="#161b22", fg="#e6edf3",
            font=("Segoe UI", 11), relief="flat", insertbackground="#e6edf3"
        )
        self.hotkey_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        self.record_btn = tk.Button(
            hotkey_row, text="🎯 Aufnehmen", bg="#da3633", fg="white",
            font=("Segoe UI", 9, "bold"), relief="flat", cursor="hand2",
            command=self._start_recording
        )
        self.record_btn.pack(side=tk.RIGHT)

        # Duration
        dur_frame = tk.Frame(frame, bg="#0d1117")
        dur_frame.pack(fill=tk.X, pady=(0, 8))

        tk.Label(dur_frame, text="Dauer (Sek.):", fg="#e6edf3", bg="#0d1117",
                 font=("Segoe UI", 10)).pack(side=tk.LEFT)
        self.dur_var = tk.IntVar(value=defaults['duration'])
        tk.Entry(dur_frame, textvariable=self.dur_var, bg="#161b22", fg="#e6edf3",
                 font=("Segoe UI", 11), relief="flat", width=6, insertbackground="#e6edf3"
                 ).pack(side=tk.LEFT, padx=8)

        tk.Label(dur_frame, text="Max:", fg="#e6edf3", bg="#0d1117",
                 font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=(10, 0))
        self.max_var = tk.IntVar(value=defaults['max_duration'])
        tk.Entry(dur_frame, textvariable=self.max_var, bg="#161b22", fg="#e6edf3",
                 font=("Segoe UI", 11), relief="flat", width=6, insertbackground="#e6edf3"
                 ).pack(side=tk.LEFT, padx=8)

        # Sound
        self.sound_var = tk.BooleanVar(value=defaults.get('sound', True))
        tk.Checkbutton(frame, text="🔊 Sound bei Ablauf", variable=self.sound_var,
                       fg="#e6edf3", bg="#0d1117", selectcolor="#161b22",
                       activebackground="#0d1117", activeforeground="#e6edf3",
                       font=("Segoe UI", 10)).pack(anchor="w", pady=2)

        # Eigene Sound-Datei
        sound_frame = tk.Frame(frame, bg="#0d1117")
        sound_frame.pack(fill=tk.X, pady=(0, 4))
        tk.Label(sound_frame, text="🎵 Sound-Datei (.wav):", fg="#8b949e",
                 bg="#0d1117", font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self.sound_file_var = tk.StringVar(value=defaults.get('sound_file', ''))
        tk.Entry(sound_frame, textvariable=self.sound_file_var, bg="#161b22", fg="#e6edf3",
                 font=("Segoe UI", 9), relief="flat", width=18, insertbackground="#e6edf3"
                 ).pack(side=tk.LEFT, padx=4)
        tk.Button(sound_frame, text="📂", bg="#21262d", fg="#e6edf3",
                  font=("Segoe UI", 8), relief="flat", cursor="hand2",
                  command=self._browse_sound).pack(side=tk.LEFT)

        # TTS
        self.tts_var = tk.BooleanVar(value=defaults.get('tts', True))
        tts_text = "🗣️ TTS Ansage bei Ablauf" if HAS_TTS else "🗣️ TTS (nicht verfügbar)"
        tk.Checkbutton(frame, text=tts_text, variable=self.tts_var,
                       fg="#e6edf3", bg="#0d1117", selectcolor="#161b22",
                       activebackground="#0d1117", activeforeground="#e6edf3",
                       font=("Segoe UI", 10),
                       state=tk.NORMAL if HAS_TTS else tk.DISABLED).pack(anchor="w", pady=2)

        # Alert Before (Früh-Alarm)
        alert_frame = tk.Frame(frame, bg="#0d1117")
        alert_frame.pack(fill=tk.X, pady=(6, 0))
        tk.Label(alert_frame, text="⏰ Alarm X Sek. vor Ablauf:", fg="#e6edf3",
                 bg="#0d1117", font=("Segoe UI", 10)).pack(side=tk.LEFT)
        self.alert_before_var = tk.IntVar(value=defaults.get('alert_before', 0))
        tk.Entry(alert_frame, textvariable=self.alert_before_var, bg="#161b22", fg="#e6edf3",
                 font=("Segoe UI", 11), relief="flat", width=5, insertbackground="#e6edf3"
                 ).pack(side=tk.LEFT, padx=8)
        tk.Label(alert_frame, text="(0 = bei Ablauf)", fg="#484f58",
                 bg="#0d1117", font=("Segoe UI", 9, "italic")).pack(side=tk.LEFT)

        # Abhängigkeit (Dependency)
        dep_frame = tk.Frame(frame, bg="#0d1117")
        dep_frame.pack(fill=tk.X, pady=(8, 0))
        tk.Label(dep_frame, text="🔗 Startet nur wenn aktiv:", fg="#e6edf3",
                 bg="#0d1117", font=("Segoe UI", 10)).pack(side=tk.LEFT)
        dep_choices = ["(keine)"] + [n for n in self.all_buff_names if n != defaults.get('name', '')]
        self.depends_var = tk.StringVar(value=defaults.get('depends_on', '') or "(keine)")
        dep_menu = ttk.Combobox(
            dep_frame, textvariable=self.depends_var,
            values=dep_choices, state="readonly", width=15
        )
        dep_menu.pack(side=tk.LEFT, padx=8)

        # Speichern
        tk.Button(frame, text="✅ Speichern", bg="#238636", fg="white",
                  font=("Segoe UI", 11, "bold"), relief="flat", cursor="hand2",
                  padx=20, pady=4, command=self._save).pack(pady=(15, 0))

        # Recording state
        self._recording = False
        self._record_hooks = []
        self._pressed_modifiers = set()

    def _browse_sound(self):
        """Öffnet einen Datei-Dialog zum Auswählen einer .wav-Datei."""
        path = filedialog.askopenfilename(
            parent=self.win,
            title="Sound-Datei auswählen",
            initialdir=SOUNDS_DIR,
            filetypes=[("WAV-Dateien", "*.wav"), ("Alle Dateien", "*.*")]
        )
        if path:
            self.sound_file_var.set(path)

    def _start_recording(self):
        """Startet die Hotkey-Aufnahme."""
        if self._recording:
            return
        self._recording = True
        self._pressed_modifiers = set()
        self.hotkey_var.set("")
        self.hotkey_entry.configure(bg="#3d1a1a")
        self.record_btn.configure(text="⏺ Warte...", bg="#8b0000")

        # Keyboard hook
        kb_hook = keyboard.hook(self._on_record_key, suppress=False)
        self._record_hooks.append(('keyboard', kb_hook))

        # Mouse hook
        if HAS_MOUSE:
            mouse_hook = mouse.hook(self._on_record_mouse)
            self._record_hooks.append(('mouse', mouse_hook))

        # Timeout: nach 10s automatisch stoppen
        self.win.after(10000, self._stop_recording_timeout)

    def _on_record_key(self, event):
        """Callback für Tastatur-Events während der Aufnahme."""
        if not self._recording:
            return

        name = event.name.lower() if event.name else ''

        if event.event_type == 'down':
            if name in MODIFIER_KEYS or any(m in name for m in ('ctrl', 'shift', 'alt')):
                self._pressed_modifiers.add(normalize_modifier(name))
                # Live-Anzeige der Modifier
                if self._pressed_modifiers:
                    preview = '+'.join(sorted(self._pressed_modifiers)) + '+...'
                    self.win.after(0, lambda: self.hotkey_var.set(preview))
            else:
                # Trigger-Taste gefunden
                modifiers = sorted(self._pressed_modifiers)
                if modifiers:
                    result = '+'.join(modifiers) + '+' + event.name
                else:
                    result = event.name
                self.win.after(0, lambda r=result: self._finish_recording(r))

    def _on_record_mouse(self, event):
        """Callback für Maus-Events während der Aufnahme."""
        if not self._recording:
            return
        if not isinstance(event, mouse.ButtonEvent):
            return
        if event.event_type != 'down':
            return
        # Links-Klick ignorieren (damit UI bedienbar bleibt)
        if event.button == 'left':
            return

        display_name = MOUSE_BUTTON_MAP.get(event.button, event.button)
        modifiers = sorted(self._pressed_modifiers)
        if modifiers:
            result = '+'.join(modifiers) + '+' + display_name
        else:
            result = display_name
        self.win.after(0, lambda r=result: self._finish_recording(r))

    def _finish_recording(self, result):
        """Beendet die Aufnahme und setzt das Ergebnis."""
        self._recording = False
        self._unhook_recording()
        self.hotkey_var.set(result)
        self.hotkey_entry.configure(bg="#161b22")
        self.record_btn.configure(text="🎯 Aufnehmen", bg="#da3633")

    def _stop_recording_timeout(self):
        """Timeout - Aufnahme abbrechen."""
        if self._recording:
            self._recording = False
            self._unhook_recording()
            self.hotkey_entry.configure(bg="#161b22")
            self.record_btn.configure(text="🎯 Aufnehmen", bg="#da3633")
            if not self.hotkey_var.get() or self.hotkey_var.get().endswith('...'):
                self.hotkey_var.set("")

    def _unhook_recording(self):
        """Entfernt alle Recording-Hooks."""
        for hook_type, hook in self._record_hooks:
            try:
                if hook_type == 'keyboard':
                    keyboard.unhook(hook)
                elif hook_type == 'mouse' and HAS_MOUSE:
                    mouse.unhook(hook)
            except Exception:
                pass
        self._record_hooks.clear()
        self._pressed_modifiers.clear()

    def _save(self):
        name = self.name_var.get().strip()
        hotkey = self.hotkey_var.get().strip()
        if not name or not hotkey:
            messagebox.showwarning("Pflichtfelder", "Name und Hotkey sind erforderlich.",
                                   parent=self.win)
            return
        try:
            dur = int(self.dur_var.get())
            max_dur = int(self.max_var.get())
            if dur <= 0 or max_dur <= 0:
                raise ValueError()
        except (ValueError, tk.TclError):
            messagebox.showwarning("Ungültig", "Dauer muss eine positive Zahl sein.",
                                   parent=self.win)
            return
        if max_dur < dur:
            messagebox.showwarning("Ungültig",
                                   "Max-Dauer muss größer oder gleich der Dauer sein.",
                                   parent=self.win)
            return

        depends = self.depends_var.get()
        if depends == "(keine)":
            depends = ""

        buff = {
            "name": name,
            "hotkey": hotkey,
            "duration": dur,
            "max_duration": max_dur,
            "alert_before": max(0, int(self.alert_before_var.get())),
            "sound": self.sound_var.get(),
            "tts": self.tts_var.get(),
            "sound_file": self.sound_file_var.get().strip(),
            "depends_on": depends,
        }
        self.on_save(buff)
        self.win.destroy()


class TextElementDialog:
    """Dialog zum Erstellen/Bearbeiten eines Layout-Text-Elements."""

    def __init__(self, parent, elem_data, on_save):
        self.on_save = on_save

        self.win = tk.Toplevel(parent)
        self.win.title("Text bearbeiten" if elem_data else "Neues Text-Element")
        self.win.geometry("380x380")
        self.win.configure(bg="#0d1117")
        self.win.attributes('-topmost', True)
        self.win.resizable(False, False)

        frame = tk.Frame(self.win, bg="#0d1117")
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)

        d = elem_data or {
            'text': 'Neuer Text', 'font_size': 14,
            'font_family': 'Segoe UI', 'font_weight': 'bold',
            'color': '#ffffff'
        }

        # Text
        tk.Label(frame, text="Text:", fg="#e6edf3", bg="#0d1117",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 2))
        self.text_var = tk.StringVar(value=d.get('text', 'Text'))
        tk.Entry(frame, textvariable=self.text_var, bg="#161b22", fg="#e6edf3",
                 font=("Segoe UI", 11), relief="flat", insertbackground="#e6edf3"
                 ).pack(fill=tk.X, pady=(0, 8))

        # Schriftgröße
        size_frame = tk.Frame(frame, bg="#0d1117")
        size_frame.pack(fill=tk.X, pady=(0, 8))
        tk.Label(size_frame, text="Schriftgröße:", fg="#e6edf3", bg="#0d1117",
                 font=("Segoe UI", 10)).pack(side=tk.LEFT)
        self.size_var = tk.IntVar(value=d.get('font_size', 14))
        tk.Spinbox(size_frame, from_=8, to=120, textvariable=self.size_var,
                   width=5, bg="#161b22", fg="#e6edf3", font=("Segoe UI", 10),
                   buttonbackground="#21262d").pack(side=tk.LEFT, padx=8)

        # Schriftart
        tk.Label(frame, text="Schriftart:", fg="#e6edf3", bg="#0d1117",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 2))
        self.font_var = tk.StringVar(value=d.get('font_family', 'Segoe UI'))
        ttk.Combobox(frame, textvariable=self.font_var,
                     values=['Segoe UI', 'Impact', 'Arial', 'Consolas',
                             'Tahoma', 'Verdana', 'Georgia', 'Courier New'],
                     width=20).pack(fill=tk.X, pady=(0, 8))

        # Stil
        self.bold_var = tk.BooleanVar(
            value=d.get('font_weight', 'bold') == 'bold')
        tk.Checkbutton(frame, text="Fett", variable=self.bold_var,
                       fg="#e6edf3", bg="#0d1117", selectcolor="#161b22",
                       activebackground="#0d1117", activeforeground="#e6edf3",
                       font=("Segoe UI", 10)).pack(anchor="w", pady=2)

        # Farbe
        color_frame = tk.Frame(frame, bg="#0d1117")
        color_frame.pack(fill=tk.X, pady=(4, 8))
        tk.Label(color_frame, text="Farbe:", fg="#e6edf3", bg="#0d1117",
                 font=("Segoe UI", 10)).pack(side=tk.LEFT)
        self.color_var = tk.StringVar(value=d.get('color', '#ffffff'))
        self._color_preview = tk.Label(color_frame, text="  \u2588\u2588  ",
                                        fg=self.color_var.get(), bg="#0d1117",
                                        font=("Segoe UI", 12))
        self._color_preview.pack(side=tk.LEFT, padx=4)
        tk.Entry(color_frame, textvariable=self.color_var, bg="#161b22",
                 fg="#e6edf3", font=("Segoe UI", 10), relief="flat", width=8,
                 insertbackground="#e6edf3").pack(side=tk.LEFT, padx=4)

        # Vorschau
        preview_size = min(d.get('font_size', 14), 24)
        self._preview = tk.Label(frame, text=d.get('text', 'Text'),
                                  fg=d.get('color', '#ffffff'), bg="#161b22",
                                  font=(d.get('font_family', 'Segoe UI'),
                                        preview_size,
                                        d.get('font_weight', 'bold')),
                                  padx=10, pady=4)
        self._preview.pack(fill=tk.X, pady=(4, 8))

        # Live-Updates
        for var in (self.text_var, self.font_var, self.color_var):
            var.trace_add('write', lambda *_: self._refresh_preview())
        self.size_var.trace_add('write', lambda *_: self._refresh_preview())
        self.bold_var.trace_add('write', lambda *_: self._refresh_preview())

        # Speichern
        tk.Button(frame, text="✅ Speichern", bg="#238636", fg="white",
                  font=("Segoe UI", 11, "bold"), relief="flat", cursor="hand2",
                  padx=20, pady=4, command=self._save).pack(pady=(8, 0))

    def _refresh_preview(self):
        try:
            w = 'bold' if self.bold_var.get() else 'normal'
            s = min(max(self.size_var.get(), 8), 24)
            self._preview.configure(text=self.text_var.get(),
                                     fg=self.color_var.get(),
                                     font=(self.font_var.get(), s, w))
            self._color_preview.configure(fg=self.color_var.get())
        except Exception:
            pass

    def _save(self):
        text = self.text_var.get().strip()
        if not text:
            messagebox.showwarning("Pflichtfeld", "Text darf nicht leer sein.",
                                   parent=self.win)
            return
        self.on_save({
            'text': text,
            'font_size': max(8, self.size_var.get()),
            'font_family': self.font_var.get() or 'Segoe UI',
            'font_weight': 'bold' if self.bold_var.get() else 'normal',
            'color': self.color_var.get() or '#ffffff'
        })
        self.win.destroy()


if __name__ == "__main__":
    app = WoWraOverlay()
    app.run()
