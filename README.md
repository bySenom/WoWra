# 🛡️ WoWra

Ein WeakAura-ähnliches externes Overlay-Tool für World of Warcraft, das dich an ablaufende Buffs erinnert.

> **[🌐 Website](https://bySenom.github.io/WoWra/)** · **[⬇ Download](https://github.com/bySenom/WoWra/releases/latest)**

---

## Features

- **🎯 WoW-Fenster Tracking** – Overlay heftet sich an WoW, folgt bei Bewegung, versteckt bei Alt-Tab/Minimierung
- **📋 Profile** – Verschiedene Buff-Sets für verschiedene Klassen/Situationen, schneller Wechsel per Klick
- **⏱️ Visueller Countdown** – Großer WeakAura-Style Countdown über dem WoW-Fenster (letzte 5 Sek.)
- **🔊 Individuelle Sounds** – Eigene .wav-Dateien pro Buff oder Standard-Beep
- **🗣️ TTS-Ansage** – Sprachausgabe via Windows SAPI (z.B. "Blühendes Leben erneuern!")
- **🔗 Buff-Abhängigkeiten** – Buff A startet nur, wenn Buff B aktiv ist
- **⏰ Früh-Alarm** – Alarm X Sekunden vor Ablauf, konfigurierbar pro Buff
- **🖱️ Maustasten-Support** – M3–M5 als Hotkeys via GetAsyncKeyState-Polling
- **🔄 Auto-Updater** – Prüft auf neue Versionen bei Start via GitHub Releases
- **🎨 Dark-Theme Overlay** – Transparentes Overlay mit farbigen Countdown-Balken (Grün → Gelb → Rot)
- **Stacking-Logik** – Erneutes Drücken addiert Dauer (bis zum konfigurierten Maximum)
- **Blinkende Ablauf-Warnung** – Visueller Hinweis auf dem Overlay

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
# Als Administrator starten (erforderlich für globale Hotkeys in WoW)
python main.py
```

> **⚠ Hinweis:** Für globale Hotkeys die auch in WoW funktionieren, muss das Programm
> als **Administrator** gestartet werden.

## Bedienung

1. **Starten** – Das Overlay erscheint und heftet sich automatisch an das WoW-Fenster
2. **Verschieben** – Overlay per Drag & Drop auf der Titelleiste positionieren
3. **Hotkey drücken** (z.B. `F5` oder `M5`) – Startet den Timer für den konfigurierten Buff
4. **Erneut drücken** – Addiert die Dauer zum laufenden Timer (bis zum Maximum)
5. **Timer läuft ab** – Sound + TTS + visueller Countdown erinnern dich

### Einstellungen (⚙)

Klicke auf das Zahnrad-Symbol im Overlay um:
- Profile erstellen, kopieren, löschen oder wechseln
- Neue Buffs hinzuzufügen mit eigenem Sound, Abhängigkeiten und Früh-Alarm
- Bestehende Buffs zu bearbeiten oder zu entfernen
- Transparenz, Sound-Frequenz, visuellen Countdown etc. anzupassen

### Profil-Wechsel

Klicke auf den 📋 Profilnamen im Overlay um zum nächsten Profil zu wechseln.

## Konfiguration

Die Einstellungen werden in `config.json` gespeichert:

| Feld | Beschreibung |
|------|-------------|
| `name` | Buff-Name (wird im Overlay angezeigt) |
| `hotkey` | Taste zum Aktivieren (z.B. `F5`, `M5`, `ctrl+1`) |
| `duration` | Sekunden die pro Tastendruck addiert werden |
| `max_duration` | Maximale Gesamtdauer des Timers |
| `alert_before` | Alarm X Sek. vor Ablauf (0 = bei Ablauf) |
| `sound` | Standard-Beep bei Ablauf (true/false) |
| `sound_file` | Eigene .wav-Datei statt Standard-Beep (Pfad) |
| `tts` | Sprachansage bei Ablauf (true/false) |
| `depends_on` | Name eines Buffs der aktiv sein muss |

## Beispiel: Blühendes Leben (Lifebloom)

- **Hotkey:** `M5`
- **Dauer:** 15 Sekunden
- **Max:** 20 Sekunden
- Beim Drücken von M5: Timer startet mit 15s
- M5 erneut bei 8s verbleibend: 8 + 15 = 23 → gekappt auf 20s
- Bei 4s: Früh-Alarm (Sound + TTS)
- Bei 0s: Ablauf-Warnung + blinkender roter Balken

## Lizenz

MIT
