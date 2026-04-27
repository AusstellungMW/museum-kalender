import json
from pathlib import Path

MESSUNGEN_FILE = Path("Messungen.json")
ANNOUNCEMENTS_FILE = Path("announcements.txt")

MARKER = "[KLIMA_AUTO]"


def main():
    data = json.loads(MESSUNGEN_FILE.read_text(encoding="utf-8"))

    temperature = data.get("temperature_c")
    humidity = data.get("humidity_percent")

    if temperature is None or humidity is None:
        raise ValueError("temperature_c or humidity_percent missing in Messungen.json")

    klima_line = (
        f"{MARKER} Aktuelle Temperatur und Luftfeuchtigkeit im Raum: "
        f"{float(temperature):.1f} °C und {float(humidity):.1f} %"
    )

    text = ANNOUNCEMENTS_FILE.read_text(encoding="utf-8").strip()

    parts = text.split("\\\\")

    found = False
    new_parts = []

    for part in parts:
        stripped = part.strip()

        if stripped.startswith(MARKER):
            new_parts.append(klima_line)
            found = True
        else:
            new_parts.append(part.strip())

    if not found:
        new_parts.append(klima_line)

    new_text = "\\\\".join(new_parts)

    ANNOUNCEMENTS_FILE.write_text(new_text, encoding="utf-8")


if __name__ == "__main__":
    main()
