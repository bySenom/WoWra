# 🛡️ WoWra

Externes Overlay-Tool für World of Warcraft – erinnert dich an ablaufende Buffs, ähnlich wie WeakAuras.

Seit WoW: The War Within nutzen Auren **Secret Values**. Dadurch können AddOns wie WeakAuras Buff-Laufzeiten nicht mehr auslesen. WoWs eigener Cooldown-Manager ist dafür leider keine brauchbare Alternative – genau dafür gibt es WoWra.

> **[🌐 Website](https://bySenom.github.io/WoWra/)** · **[⬇ Download](https://github.com/bySenom/WoWra/releases/latest)**

---

## Features

- **WoW-Fenster Tracking** – Overlay klebt am WoW-Fenster, folgt bei Bewegung, versteckt sich bei Alt-Tab/Minimierung
- **Profile** – Verschiedene Buff-Sets pro Klasse/Situation, ein Klick zum Wechseln
- **Visueller Countdown** – Großer WeakAura-Style Countdown über dem WoW-Fenster (letzte 5 Sek.)
- **Eigene Sounds** – .wav-Dateien pro Buff oder Standard-Beep
- **TTS-Ansage** – Sprachausgabe über Windows SAPI (z.B. "Blühendes Leben erneuern!")
- **Buff-Abhängigkeiten** – Buff A startet nur wenn Buff B aktiv ist
- **Früh-Alarm** – Alarm X Sekunden vor Ablauf, pro Buff einstellbar
- **Maustasten-Support** – M3–M5 als Hotkeys nutzbar
- **Buff-Verlängerung** – z.B. für Rasche Heilung: eigener Hotkey, Cursor-Radius-Check, Cooldown
- **Auto-Updater** – Prüft beim Start auf neue Versionen
- **Dark-Theme** – Transparentes Overlay mit Countdown-Balken (Grün → Gelb → Rot)
- **Stacking** – Erneutes Drücken addiert Dauer (bis zum Maximum)
- **Auto-Exit** – Beendet sich automatisch wenn WoW geschlossen wird

## Installation

### Voraussetzungen
- Python 3.8+
- Windows 10/11

### Setup

```bash
git clone https://github.com/bySenom/WoWra.git
cd WoWra
pip install -r requirements.txt
```

## Starten

```bash
# Als Administrator starten (nötig für globale Hotkeys in WoW)
python main.py
```

> **⚠ Hinweis:** Für globale Hotkeys die in WoW funktionieren, muss das Programm
> als **Administrator** laufen.

## Bedienung

1. **Starten** – Overlay erscheint und heftet sich ans WoW-Fenster
2. **Verschieben** – Per Drag & Drop auf der Titelleiste
3. **Hotkey drücken** (z.B. `F5` oder `M5`) – Timer startet
4. **Nochmal drücken** – Addiert Dauer zum laufenden Timer (bis zum Maximum)
5. **Timer läuft ab** – Sound + TTS + Countdown erinnern dich

### Einstellungen (⚙)

Zahnrad-Symbol im Overlay:
- Profile erstellen, kopieren, löschen, wechseln
- Buffs hinzufügen/bearbeiten (Sound, Abhängigkeiten, Früh-Alarm, Verlängerung)
- Transparenz, Sound, visuellen Countdown anpassen

### Profil-Wechsel

Klick auf den 📋 Profilnamen → nächstes Profil.

## Konfiguration

Einstellungen landen in `config.json`:

| Feld | Beschreibung |
|------|-------------|
| `name` | Buff-Name (wird im Overlay angezeigt) |
| `hotkey` | Taste zum Aktivieren (z.B. `F5`, `M5`, `ctrl+1`) |
| `duration` | Sekunden die pro Druck addiert werden |
| `max_duration` | Maximale Gesamtdauer |
| `alert_before` | Alarm X Sek. vor Ablauf (0 = bei Ablauf) |
| `sound` | Beep bei Ablauf (true/false) |
| `sound_file` | Eigene .wav statt Beep (Pfad) |
| `tts` | Sprachansage bei Ablauf (true/false) |
| `depends_on` | Buff der aktiv sein muss |
| `extend_hotkey` | Hotkey für Verlängerung (z.B. Rasche Heilung) |
| `extend_seconds` | Sekunden die verlängert werden |
| `extend_radius` | Max. Cursor-Abstand zur letzten Aktivierung (px) |
| `extend_enabled` | Verlängerung aktiv (true/false) |

## Beispiel: Blühendes Leben (Lifebloom)

- **Hotkey:** `M5`
- **Dauer:** 15 Sekunden
- **Max:** 20 Sekunden
- M5 drücken: Timer startet mit 15s
- M5 nochmal bei 8s übrig: 8 + 15 = 23 → gekappt auf 20s
- Bei 4s: Früh-Alarm (Sound + TTS)
- Bei 0s: Ablauf-Warnung + blinkender roter Balken
- **Rasche Heilung:** Eigener Extend-Hotkey verlängert den Timer über 20s hinaus

## Disclaimer

WoWra liest keinen Spielspeicher, injiziert keinen Code und interagiert nicht mit dem WoW-Client. Es ist ein reines Overlay – im Prinzip eine Stoppuhr auf dem Bildschirm. Trotzdem: Nutzung auf eigene Verantwortung. Blizzard kann jederzeit Richtlinien ändern.

## Lizenz

MIT
