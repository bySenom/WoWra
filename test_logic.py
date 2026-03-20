"""Schnelltest für die Kernlogik."""
import sys
import os
import time

# __file__ Workaround
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Importiere nur die Klassen die wir brauchen
sys.path.insert(0, ".")

from main import BuffTimer, load_config, save_config

# Test 1: BuffTimer Grundfunktion
t = BuffTimer("Blühendes Leben", 15, 20)
assert not t.active
assert t.remaining == 0.0
print("[OK] Timer initial inaktiv")

# Test 2: Aktivierung
t.activate()
assert t.active
assert 14.9 < t.remaining <= 15.0
print(f"[OK] Nach activate: {t.remaining:.2f}s (erwartet ~15)")

# Test 3: Repress addiert, capped auf max_duration
time.sleep(0.1)
t.activate()
r = t.remaining
assert r <= 20.0
assert r > 19.5  # ~14.9 + 15 = 29.9 -> capped to 20
print(f"[OK] Nach Repress: {r:.2f}s (capped auf max 20)")

# Test 4: Expiration
t2 = BuffTimer("Test", 0.2, 0.5)
t2.activate()
time.sleep(0.3)
expired = t2.check_expired()
assert expired
assert t2.expired_at is not None
print("[OK] Timer korrekt abgelaufen")

# Test 5: Config laden
cfg = load_config()
assert cfg["buffs"][0]["name"] == "Blühendes Leben"
assert cfg["buffs"][0]["duration"] == 15
assert cfg["buffs"][0]["max_duration"] == 20
print("[OK] Config korrekt geladen")

print("\n✅ Alle Tests bestanden!")
