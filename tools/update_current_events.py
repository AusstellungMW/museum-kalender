import datetime as dt
import hashlib
import json
import re
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "User-Agent": "MuseumCurrentEventsUpdater/1.1",
}

OUTPUT_FILE = Path("current_events.json")

PRICE_PUBLIC_GUIDED_TOUR = "7,50 €"
PRICE_TANZMEISTER = "9,50 €"
PRICE_DEFAULT_EVENT = ""

MUSEUM_EVENT_SOURCES = [
    {
        "museum": "Bürger Museum",
        "url": "https://www.museumwolfenbuettel.de/B%C3%BCrger-Museum/Veranstaltungen/",
        "kind": "Veranstaltung",
    },
    {
        "museum": "Schloss Museum",
        "url": "https://www.museumwolfenbuettel.de/Schloss-Museum/Veranstaltungen/",
        "kind": "Veranstaltung",
    },
    {
        "museum": "Schloss Museum",
        "url": "https://www.museumwolfenbuettel.de/Schloss-Museum/%C3%96ffentliche-F%C3%BChrungen/",
        "kind": "Öffentliche Führung",
    },
]


def normalize_spaces(text: str) -> str:
    text = (text or "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text.strip())


def clean_time_text(text: str) -> str:
    """
    Entfernt technische/Screenreader-Labels aus der Website-Ausgabe.
    Aus 'Uhrzeit: 11:00 bis 11:50 Uhr' wird '11:00 bis 11:50 Uhr'.
    """
    text = normalize_spaces(text)
    text = re.sub(r"^Uhrzeit:\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"^Datum:\s*", "", text, flags=re.IGNORECASE).strip()
    return text


def normalize_event_title(title: str) -> str:
    title = normalize_spaces(title)
    title = re.sub(r"^#\s*", "", title).strip()
    return title


def slugify_for_event_id(value: str, max_len: int = 90) -> str:
    value = normalize_spaces(value).lower()
    value = value.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    if not value:
        value = "event"
    return value[:max_len].strip("-")


def make_event_id(museum: str, start_dt: dt.datetime, title: str) -> str:
    museum_slug = slugify_for_event_id(museum, 35)
    title_slug = slugify_for_event_id(title, 90)
    date_part = start_dt.strftime("%Y-%m-%d_%H-%M")
    base = f"{museum_slug}_{date_part}_{title_slug}"

    hash_src = f"{museum}|{start_dt.isoformat(timespec='minutes')}|{title}".encode("utf-8")
    short_hash = hashlib.sha1(hash_src).hexdigest()[:8]

    return f"{base}_{short_hash}"


def fetch_text_url(url: str) -> str | None:
    try:
        r = requests.get(url, timeout=25, headers=HEADERS, allow_redirects=True)
        r.raise_for_status()

        # Die Website nutzt teilweise ISO-8859-15.
        if not r.encoding or r.encoding.lower() in ("iso-8859-1", "latin-1"):
            r.encoding = r.apparent_encoding or "ISO-8859-15"

        return r.text.lstrip("\ufeff")

    except Exception as e:
        print(f"ERROR fetch {url}: {type(e).__name__}: {e}")
        return None


def parse_german_event_datetime(date_text: str, time_text: str = "") -> dt.datetime | None:
    date_text = normalize_spaces(date_text)
    time_text = clean_time_text(time_text)

    m_date = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", date_text)
    if not m_date:
        return None

    day, month, year = map(int, m_date.groups())

    m_time = re.search(r"(\d{1,2}):(\d{2})", time_text)
    if m_time:
        hour, minute = map(int, m_time.groups())
    else:
        hour, minute = 0, 0

    try:
        return dt.datetime(year, month, day, hour, minute)
    except Exception:
        return None


def detect_event_price(title: str, source_url: str = "", kind: str = "") -> str:
    title_l = normalize_spaces(title).lower()
    url_l = source_url.lower()
    kind_l = kind.lower()

    if "tanzmeister" in title_l:
        return PRICE_TANZMEISTER

    if "öffentliche führung" in kind_l:
        return PRICE_PUBLIC_GUIDED_TOUR

    if "öffentliche-führungen" in url_l or "%c3%96ffentliche-f%c3%bchrungen".lower() in url_l:
        return PRICE_PUBLIC_GUIDED_TOUR

    return PRICE_DEFAULT_EVENT


def extract_event_from_li(li, source: dict) -> dict | None:
    title_tag = li.find("h3", class_="list-title")
    if not title_tag:
        return None

    title = normalize_event_title(title_tag.get_text(" ", strip=True))
    if not title:
        return None

    small_texts = [normalize_spaces(s.get_text(" ", strip=True)) for s in li.find_all("small")]

    date_text = ""
    time_text = ""

    for text in small_texts:
        if re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", text):
            date_text = text

        if "Uhr" in text or re.search(r"\d{1,2}:\d{2}", text):
            time_text = text

    full_text = normalize_spaces(li.get_text(" ", strip=True))

    if not date_text:
        m = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})", full_text)
        if m:
            date_text = m.group(1)

    if not time_text:
        m = re.search(r"(\d{1,2}:\d{2}(?:\s*bis\s*\d{1,2}:\d{2})?\s*Uhr)", full_text)
        if m:
            time_text = m.group(1)

    if not date_text:
        return None

    time_text = clean_time_text(time_text)

    start_dt = parse_german_event_datetime(date_text, time_text)
    if start_dt is None:
        return None

    price = detect_event_price(title, source["url"], source.get("kind", ""))
    event_id = make_event_id(source["museum"], start_dt, title)

    return {
        "event_id": event_id,
        "title": title,
        "museum": source["museum"],
        "kind": source.get("kind", ""),
        "start": start_dt.isoformat(timespec="minutes"),
        "time_text": time_text,
        "price": price,
        "source_url": source["url"],
    }


def fetch_museum_events_from_site() -> list[dict]:
    all_events = []
    now = dt.datetime.now()
    horizon = now + dt.timedelta(days=365)
    seen = set()

    for source in MUSEUM_EVENT_SOURCES:
        html = fetch_text_url(source["url"])
        if not html:
            print(f"Keine HTML-Daten: {source['url']}")
            continue

        soup = BeautifulSoup(html, "html.parser")

        candidate_items = []
        for title_tag in soup.find_all("h3", class_="list-title"):
            li = title_tag.find_parent("li")
            if li:
                candidate_items.append(li)

        print(f"{source['museum']} / {source.get('kind', '')}: candidates={len(candidate_items)}")

        for li in candidate_items:
            ev = extract_event_from_li(li, source)
            if not ev:
                continue

            start_dt = dt.datetime.fromisoformat(ev["start"])

            if start_dt < now:
                continue

            if start_dt > horizon:
                continue

            key = (ev["title"].lower(), ev["start"], ev["museum"].lower())
            if key in seen:
                continue

            seen.add(key)
            all_events.append(ev)

    all_events.sort(key=lambda x: x["start"])
    return all_events


def main():
    events = fetch_museum_events_from_site()

    text = json.dumps(events, ensure_ascii=False, indent=2) + "\n"
    old_text = OUTPUT_FILE.read_text(encoding="utf-8") if OUTPUT_FILE.exists() else ""

    if old_text == text:
        print("current_events.json unchanged")
        return

    OUTPUT_FILE.write_text(text, encoding="utf-8")
    print(f"current_events.json updated: {len(events)} events")


if __name__ == "__main__":
    main()
