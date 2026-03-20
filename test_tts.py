"""Schnelltest: TTS spricht zweimal hintereinander."""
import subprocess
import time

def speak(text):
    safe_text = text.replace("'", "''").replace('"', '')
    ps_script = (
        f"Add-Type -AssemblyName System.Speech; "
        f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.Rate = 2; "
        f"$s.Speak('{safe_text}'); "
        f"$s.Dispose()"
    )
    result = subprocess.run(
        ['powershell', '-NoProfile', '-Command', ps_script],
        timeout=10,
        creationflags=0x08000000,
        capture_output=True, text=True
    )
    print(f"  -> '{text}' gesprochen (returncode={result.returncode})")
    if result.stderr:
        print(f"  STDERR: {result.stderr}")

print("Test 1:")
speak("Blühendes Leben abgelaufen")
time.sleep(0.5)
print("Test 2:")
speak("Blühendes Leben abgelaufen")
time.sleep(0.5)
print("Test 3:")
speak("Noch ein Test")
print("Fertig!")
