import os
import re
import sys
import ssl
import html
import json
import time
import socket
import certifi
import requests
import feedparser
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
import urllib.request
from google import genai
from google.genai import types

socket.setdefaulttimeout(10)
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
ONESIGNAL_APP_ID = os.environ.get("ONESIGNAL_APP_ID")
ONESIGNAL_API_KEY = os.environ.get("ONESIGNAL_API_KEY")
LOCAL_TZ = ZoneInfo("Europe/Berlin")

PROTO = "https://"

RSS_SOURCES_SECURITY = [
    ("CERT Polska", "cert.pl", "/rss.xml"),
    ("CyberDefence24", "cyberdefence24.pl", "/feed"),
    ("Niebezpiecznik", "niebezpiecznik.pl", "/feed/"),
    ("Sekurak", "sekurak.pl", "/feed/"),
    ("Demagog", "demagog.org.pl", "/feed/"),
    ("Konkret24", "konkret24.tvn24.pl", "/najnowsze.xml"),
    ("CERT-Bund (BSI)", "wid.cert-bund.de", "/content/public/securityAdvisory/rss"),
    ("Heise Security", "www.heise.de", "/security/rss/news-atom.xml"),
    ("Golem.de", "rss.golem.de", "/rss.php?feed=RSS2.0"),
    ("Mimikama", "www.mimikama.org", "/feed/"),
    ("Correctiv", "correctiv.org", "/feed/"),
    ("EUvsDisinfo", "euvsdisinfo.eu", "/feed/"),
    ("Lebensmittelwarnung (DE)", "www.lebensmittelwarnung.de", "/bvl-lmw-de/feed/alle/alle_bundeslaender.rss"),
    ("Lebensmittelwarnung (Hessen)", "www.lebensmittelwarnung.de", "/bvl-lmw-de/feed/alle/hessen.rss"),
]

RSS_SOURCES_WORLD_NEWS = [
    ("OSW", "www.osw.waw.pl", "/pl/rss.xml"),
    ("PAP", "www.pap.pl", "/rss/wiadomosci.xml"),
    ("TVN24 Najnowsze", "tvn24.pl", "/najnowsze.xml"),
    ("TVN24 Świat", "tvn24.pl", "/swiat.xml"),
    ("RMF24 Polska", "www.rmf24.pl", "/fakty/polska/feed"),
    ("RMF24 Świat", "www.rmf24.pl", "/fakty/swiat/feed"),
    ("RMF24 Ekonomia", "www.rmf24.pl", "/ekonomia/feed"),
    ("Bankier.pl", "www.bankier.pl", "/rss/wiadomosci.xml"),
    ("Tagesschau", "www.tagesschau.de", "/infoservices/alle-meldungen-100~rss2.xml"),
    ("Tagesschau Wirtschaft", "www.tagesschau.de", "/wirtschaft/index~rss2.xml"),
    ("Hessenschau (Hessen)", "www.hessenschau.de", "/index.rss"),
    ("Deutsche Welle DE", "://dw.com", "/xml/rss-de-all"),
]

NOISE_KEYWORDS = {
    "bundesliga", "ekstraklasa", "champions league", "liga mistrzów", "piłka nożna",
    "fußball", "handball", "siatkówka", "tenis", "skoki narciarskie", "formel 1", "formuła 1",
    "horoskop", "taniec z gwiazdami", "m jak miłość", "first dates", "dschungelcamp",
    "celebryci", "plotki", "wynik meczu", "kwalifikacje do"
}

ALLOWED_DOMAINS = {
    "cert.pl", "cyberdefence24.pl", "niebezpiecznik.pl", "sekurak.pl",
    "cert-bund.de", "wid.cert-bund.de", "bsi.bund.de", "heise.de",
    "golem.de", "osw.waw.pl", "tagesschau.de", "reuters.com", "nato.int",
    "pap.pl", "tvn24.pl", "demagog.org.pl", "correctiv.org", "euvsdisinfo.eu",
    "konkret24.tvn24.pl", "mimikama.org", "rmf24.pl", "polsatnews.pl",
    "hessenschau.de", "ffh.de", "bankier.pl", "dw.com", "lebensmittelwarnung.de", "gov.pl"
}


def is_allowed_url(url):
    try:
        domain = urlparse(url).netloc.lower()
        return any(domain == d or domain.endswith("." + d) for d in ALLOWED_DOMAINS)
    except Exception:
        return False


def is_noise(title, summary):
    combined = (title + " " + summary).lower()
    return any(kw in combined for kw in NOISE_KEYWORDS)


def fetch_recent_articles(sources, known_links, hours=24):
    feedparser.USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    new_items = []

    for source_name, host, path in sources:
        url = PROTO + host + path
        try:
            print(f"  -> Sprawdzam: {source_name}...", flush=True)
            feed = feedparser.parse(url)
            if not feed.entries:
                continue
            for entry in feed.entries:
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                if published:
                    pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                    if pub_dt >= cutoff:
                        link = entry.get("link", "").strip()
                        if link and is_allowed_url(link) and link not in known_links:
                            title = html.unescape(entry.get("title", ""))
                            summary = html.unescape(re.sub(r'<[^>]+>', '', entry.get("summary", "")))[:600]
                            if not is_noise(title, summary):
                                text_block = f"[{source_name}] {title}\nSzczegóły: {summary}\nLink: {link}\n"
                                new_items.append(text_block)
                                known_links.add(link)
        except Exception as e:
            print(f"  [!] Pominięto {source_name}: {e}", flush=True)

    return new_items


def fetch_gis_warnings(known_links):
    url = "https://www.gov.pl"
    new_items = []
    try:
        print("  -> Sprawdzam: GIS Polska (Ostrzeżenia o żywności)...", flush=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            page_html = resp.read().decode("utf-8", errors="ignore")
        matches = re.findall(r'href="(/web/gis/ostrzezenie-[^"]+)"[^>]*>(.*?)</a>', page_html, re.S)
        for path, raw_title in matches[:10]:
            full_link = "https://www.gov.pl" + path.strip()
            clean_t = html.unescape(re.sub(r"<[^>]+>", " ", raw_title)).strip()
            clean_t = re.sub(r"\s+", " ", clean_t)
            if clean_t and full_link not in known_links:
                text_block = f"[GIS Polska – Żywność] {clean_t}\nSzczegóły: Oficjalne ostrzeżenie Głównego Inspektoratu Sanitarnego w Polsce dotyczące wycofania produktu spożywczego.\nLink: {full_link}\n"
                new_items.append(text_block)
                known_links.add(full_link)
    except Exception as e:
        print(f"  [!] Pominięto GIS Polska: {e}", flush=True)
    return new_items
def generate_report_data(articles_text, lang="PL"):
    empty_msg = (
        "Seit dem letzten Bericht gab es keine neuen Warnungen oder relevanten Vorfälle – alles ist sicher."
        if lang == "DE"
        else "Od ostatniego raportu nie pojawiły się żadne nowe ostrzeżenia ani istotne zagrożenia – wszystko jest bezpieczne."
    )
    empty_result = {
        "dorosli": [], "dzieci": [], "bezpieczne_podsumowanie": empty_msg,
        "aplikacje_i_sprzet": [], "oszustwa_i_wycieki": [], "awarie_i_kraj": [],
        "granice_i_wojsko": [], "dezinformacja": [], "zmiany_w_prawie": [], "gielda_i_etf": []
    }
    if not articles_text.strip():
        return empty_result

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    if lang == "DE":
        prompt = f'''
Du bist mein persönlicher Informationsfilter für eine Familie in Deutschland (Hessen) mit Bezug zu Polen. Deine Aufgabe ist es, die Flut an Nachrichten aus dem Internet so zu filtern, dass ich keine Boulevard-Portale mehr lesen muss – aber KEINE echte Gefahr übersehe.

ZWEI KLARE REGELN FÜR DIE AUSWAHL:

1. KATEGORIEN OHNE LIMIT (ALLE relevanten Vorfälle aufnehmen!):
- Lebensmittelwarnungen & Produktrückrufe (DE / Hessen / PL) -> ALLE aufnehmen!
- Cyberangriffe, große Datenlecks, Betrugswellen auf Portalen (Booking, Check24, Kleinanzeigen, Vinted, Amazon, PayPal, Banken) -> ALLE aufnehmen!
- Wichtige Sicherheitsupdates für Heimgeräte & Apps (iOS, Android, Windows, Router, Browser) -> ALLE aufnehmen (nur reine Unternehmens-IT wie SAP, Cisco, Fortinet weglassen).

2. ALLGEMEINE NACHRICHTEN (STRENGER ANTI-CLICKBAIT-FILTER):
- Ignoriere konsequent Boulevard-Müll, Clickbait, Politiker-Gezänk ("Politiker X fordert/kritisiert..."), lokale Verkehrsunfälle, Promi-News und normale tägliche Börsenschwankungen.
- Nimm bei Recht, Infrastruktur, Grenzen, Desinformation und Börse NUR harte Fakten, bereits beschlossene Gesetze, größere Störungen (Strom, Bahn, Mobilfunk) oder bedeutende Marktbewegungen (DAX, WIG20, S&P 500, ETFs, Zinsentscheidungen) auf.

STIL & STRUKTUR:
- Deduplizierung: Wenn mehrere Quellen über denselbe Ereignis berichten, fasse sie zu EINEM einzigen Punkt zusammen.
- Schreibe klar, sachlich und prägnant (2 kurze Sätze pro Punkt), komplett ohne Fachjargon (keine Abkürzungen wie CVE, API, RCE, DoS, Firmware, Exploit, Phishing).
- Konsistenz: Jeder Lebensmittelrückruf, relevante Cyberangriff, App-Fehler oder wichtige Gesetzesstart muss auch unter dorosli oder dzieci mit einem kurzen 1-Satz-Handlungstipp erscheinen.
- Keine Platzhalter: Wenn es keine konkreten Warnungen für Erwachsene oder Kinder gibt, lasse "dorosli" und "dzieci" zwingend als leere Listen [] (schreibe dort KEINE allgemeinen Sicherheitstipps).

Gib das Ergebnis als reines JSON-Objekt mit genau diesen Schlüsseln zurück (ALLE Werte auf DEUTSCH):
{{
  "dorosli": [{{"ikona": "🏨", "tytul": "Kurzer Titel", "opis": "1-2 knappe Handlungssätze (Was konkret tun?)."}}],
  "dzieci": [{{"ikona": "🎮", "tytul": "Kurzer Titel", "opis": "1-2 knappe Handlungssätze für Kinder/Jugendliche."}}],
  "bezpieczne_podsumowanie": "1-2 Sätze auf Deutsch, dass die übrigen Bereiche (Ubiquiti, Yubico, Signal/WhatsApp, Banken DE/PL) sicher sind.",
  "aplikacje_i_sprzet": [{{"ikona": "🍎", "tytul": "Gerät/App", "opis": "2 Sätze zu Sicherheitsupdates bei Endgeräten/Apps (ohne Server-IT).", "link": "URL"}}],
  "oszustwa_i_wycieki": [{{"ikona": "🚨", "tytul": "Portal/Betrug", "opis": "2 Sätze zu allen gemeldeten Datenlecks, Cyberangriffen und Betrugswellen.", "link": "URL"}}],
  "awarie_i_kraj": [{{"ikona": "⚡", "tytul": "Ort/Thema", "opis": "2 Sätze zu ALLEN Lebensmittelrückrufen (DE/Hessen/PL), großen Infrastrukturausfällen oder Behördenwarnungen.", "link": "URL"}}],
  "granice_i_wojsko": [{{"ikona": "📡", "tytul": "Region/Thema", "opis": "2 Sätze nur zu relevanten Sicherheitsvorfällen an NATO/EU-Grenzen + ruhige Einschätzung.", "link": "URL"}}],
  "dezinformacja": [{{"ikona": "📘", "tytul": "Thema/Plattform", "opis": "2 Sätze zu viralen Falschmeldungen und deren Richtigstellung.", "link": "URL"}}],
  "zmiany_w_prawie": [{{"ikona": "🇩🇪", "tytul": "Land – Bereich", "opis": "2 Sätze nur zu beschlossenen oder in Kraft tretenden Gesetzen in DE (Hessen) und PL (Verkehr, Miete, Arbeit, Rente, Schule, Steuern).", "link": "URL"}}],
  "gielda_i_etf": [{{"ikona": "📈", "tytul": "Markt/Zinsen", "opis": "2 sachliche Sätze nur zu bedeutenden Marktbewegungen (DAX, WIG20, S&P 500, ETFs) oder EZB/Fed-Entscheidungen (rein informativ).", "link": "URL"}}]
}}

ARTIKEL:
{articles_text}

WICHTIGSTE REGEL: Schreibe ALLE Texte, Titel und Beschreibungen im JSON-Objekt zu 100 % auf DEUTSCH! Übersetze alle polnischen Nachrichtenquellen komplett ins Deutsche. Es darf KEIN einziges polnisches Wort im Ergebnis vorkommen!
'''
    else:
        prompt = f'''
Jesteś moim osobistym filtrem informacyjnym dla rodziny mieszkającej w Niemczech (Hesja) i związanej z Polską. Twoim zadaniem jest przesianie zalewu wiadomości z internetu tak, żebym nie musiał wchodzić na portale pełne klikbajtów (WP, Interia, Bild), ale jednocześnie NIE PRZEGAPIŁ żadnego realnego zagrożenia.

DWIE JASNE ZASADY SELEKCJI:

1. KATEGORIE BEZ LIMITU (WRZUCAJ WSZYSTKIE ISTOTNE ZDARZENIA!):
- Ostrzeżenia o żywności i wycofania produktów ze sklepów (GIS Polska, Lebensmittelwarnung DE/Hesja) -> WRZUĆ WSZYSTKIE!
- Ataki cybernetyczne, wycieki danych, fale oszustw na portalach i w bankach (Booking, Check24, Kleinanzeigen, Vinted, OLX, Allegro, Amazon, PayPal) -> WRZUĆ WSZYSTKIE!
- Ważne luki i aktualizacje bezpieczeństwa dla domowego sprzętu i aplikacji (iOS, Android, Windows, routery, przeglądarki) -> WRZUĆ WSZYSTKIE (pomiń tylko niszowe oprogramowanie serwerowe dla firm jak SAP, Cisco, Fortinet).

2. POZOSTAŁE WIADOMOŚCI (SUROWY FILTR ANTY-KLIKBAJTOWY):
- Bezwzględnie odrzucaj klikbajty, sensacyjne nagłówki bez treści, polityczne przepychanki („polityk X powiedział/skrytykował...”), lokalne wypadki drogowe, plotki oraz codzienne drobne wahania giełdowe.
- W działach prawo, awarie, granice, dezinformacja i giełda zostawiaj TYLKO twarde fakty: uchwalone lub wchodzące w życie przepisy (PL i DE/Hesja), duże awarie (prąd, kolej, sieci), realne incydenty przy granicach NATO/UE, głośne fake newsy oraz wyraźne ruchy na rynkach (DAX, WIG20, S&P 500, ETF-y, decyzje EBC/Fed/NBP).

STYL I SPÓJNOŚĆ:
- Deduplikacja: Jeśli kilka serwisów pisze o tym samym wydarzeniu, połącz je w JEDEN konkretny punkt (zero powtórek).
- Pisz krótko, rzeczowo i prostym językiem (dokładnie 2 zwięzłe zdania na punkt), bez żargonu (zero skrótów typu CVE, API, RCE, DoS, firmware, exploit, phishing).
- Spójność: Każde wycofanie żywności, istotny atak cybernetyczny, błąd w aplikacji domowej lub ważna zmiana w prawie MUSI pojawić się też w dorosli lub dzieci jako 1 krótkie zdanie z praktyczną wskazówką, co zrobić.
- Zero wypełniaczy: Jeśli nie ma konkretnych ostrzeżeń dla dorosłych lub dzieci, zostaw "dorosli" oraz "dzieci" jako puste listy [] (nie wpisuj tam ogólnych porad typu „wszystko bezpieczne”).

Zwróć wynik jako czysty obiekt JSON z dokładnie poniższymi kluczami (wszystkie wartości po POLSKU):
{{
  "dorosli": [{{"ikona": "🏨", "tytul": "Krótki tytuł", "opis": "1-2 zwięzłe zdania co konkretnie zrobić."}}],
  "dzieci": [{{"ikona": "🎮", "tytul": "Krótki tytuł", "opis": "1-2 zwięzłe zdania na co uczulić dzieci i młodzież."}}],
  "bezpieczne_podsumowanie": "1-2 zdania potwierdzające, że pozostałe monitorowane obszary (sieć Ubiquiti, Yubico, Signal/WhatsApp, banki PL/DE) są bezpieczne.",
  "aplikacje_i_sprzet": [{{"ikona": "🍎", "tytul": "Sprzęt/Aplikacja", "opis": "2 zwięzłe zdania o aktualizacjach sprzętu domowego i aplikacji (bez IT serwerowego).", "link": "URL"}}],
  "oszustwa_i_wycieki": [{{"ikona": "🚨", "tytul": "Portal/Oszustwo", "opis": "2 zwięzłe zdania o wszystkich zgłoszonych wyciekach danych, cyberatakach i falach oszustw.", "link": "URL"}}],
  "awarie_i_kraj": [{{"ikona": "⚡", "tytul": "Miejsce/Temat", "opis": "2 zwięzłe zdania o WSZYSTKICH wycofaniach żywności (PL/DE/Hesja), dużych awariach lub komunikatach służb.", "link": "URL"}}],
  "granice_i_wojsko": [{{"ikona": "📡", "tytul": "Region/Temat", "opis": "2 zwięzłe zdania tylko o realnych incydentach przy granicach NATO/UE ze spokojną oceną.", "link": "URL"}}],
  "dezinformacja": [{{"ikona": "📘", "tytul": "Temat/Platforma", "opis": "2 zwięzłe zdania o wiralowych fake newsach i ich sprostowaniu.", "link": "URL"}}],
  "zmiany_w_prawie": [{{"ikona": "🇵🇱", "tytul": "Kraj – Dziedzina", "opis": "2 zwięzłe zdania tylko o uchwalonych lub wchodzących w życie przepisach w PL i DE/Hesji (ruch drogowy, najem, praca, emerytury, szkoła, podatki).", "link": "URL"}}],
  "gielda_i_etf": [{{"ikona": "📈", "tytul": "Rynek/Stopy", "opis": "2 rzeczowe zdania tylko o istotnych ruchach rynkowych (DAX, WIG20, S&P 500, ETF-y) lub decyzjach EBC/Fed/NBP (wyłącznie informacyjnie).", "link": "URL"}}]
}}

ARTYKUŁY:
{articles_text}

NAJWAŻNIEJSZA ZASADA: Napisz WSZYSTKIE teksty, tytuły i opisy w obiekcie JSON w 100% po POLSKU! Przetłumacz wszystkie niemieckie źródła na język polski. Ani jedno słowo nie może być po niemiecku!
'''
    models_to_try = [
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.6-flash",
        "gemini-3.7-flash",
        "gemini-3.8-flash"
    ]

    last_error = None
    for attempt in range(2):
        for model_name in models_to_try:
            try:
                print(f"[{lang}] Próba generowania ({model_name})...", flush=True)
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        response_mime_type="application/json"
                    )
                )
                raw = response.text.strip()
                raw = re.sub(r'^```json\s*|\s*```$', '', raw)
                return json.loads(raw)
            except Exception as e:
                last_error = e
                print(f"[{lang}] {model_name} niedostępny ({type(e).__name__}), czekam 8s...", flush=True)
                time.sleep(8)

    raise RuntimeError(f"[{lang}] Nie udało się wygenerować raportu: {last_error}")


def merge_report_parts(part_sec, part_news, lang="PL"):
    merged = {}
    list_keys = [
        "dorosli", "dzieci", "aplikacje_i_sprzet", "oszustwa_i_wycieki",
        "awarie_i_kraj", "granice_i_wojsko", "dezinformacja",
        "zmiany_w_prawie", "gielda_i_etf"
    ]
    for k in list_keys:
        merged[k] = (part_sec.get(k) or []) + (part_news.get(k) or [])

    has_alerts = bool(merged["dorosli"] or merged["dzieci"])
    base_ok = part_sec.get("bezpieczne_podsumowanie") or part_news.get("bezpieczne_podsumowanie") or ""

    if has_alerts:
        if lang == "DE":
            merged["bezpieczne_podsumowanie"] = "Abgesehen von den oben genannten Empfehlungen sind alle übrigen überwachten Bereiche (Heimnetzwerk Ubiquiti, Yubico, Signal/WhatsApp, Banken DE/PL) sicher."
        else:
            merged["bezpieczne_podsumowanie"] = "Poza powyższymi zaleceniami, pozostałe monitorowane obszary (sieć domowa Ubiquiti, Yubico, Signal/WhatsApp, banki PL/DE) są bezpieczne."
    else:
        merged["bezpieczne_podsumowanie"] = base_ok

    return merged
def flatten_for_app(report_dict, lang="PL"):
    items = []
    time_label = "Ostatnie 24h" if lang == "PL" else "Letzte 24h"

    sections = [
        ("dorosli", "advice", "👨‍💼 Dorośli" if lang == "PL" else "👨‍💼 Erwachsene"),
        ("dzieci", "advice", "🧒 Dzieci i młodzież" if lang == "PL" else "🧒 Kinder & Jugendliche"),
        ("oszustwa_i_wycieki", "cyber", "🚨 Oszustwa i wycieki" if lang == "PL" else "🚨 Betrug & Datenlecks"),
        ("aplikacje_i_sprzet", "cyber", "📱 Aplikacje i sprzęt" if lang == "PL" else "📱 Apps & Heimgeräte"),
        ("awarie_i_kraj", "food", "⚡ Żywność i awarie" if lang == "PL" else "⚡ Lebensmittel & Infrastruktur"),
        ("zmiany_w_prawie", "law", "📜 Zmiany w prawie" if lang == "PL" else "📜 Gesetzesänderungen"),
        ("gielda_i_etf", "market", "📈 Giełda i ETF" if lang == "PL" else "📈 Börse & ETFs"),
        ("granice_i_wojsko", "other", "📡 Granice i bezpieczeństwo" if lang == "PL" else "📡 Sicherheitslage Grenzen"),
        ("dezinformacja", "other", "🔍 Dezinformacja" if lang == "PL" else "🔍 Desinformation"),
    ]

    for key, cat_id, cat_label in sections:
        for entry in report_dict.get(key, []) or []:
            if isinstance(entry, dict):
                items.append({
                    "cat": cat_id,
                    "cat_label": cat_label,
                    "ikona": entry.get("ikona", "📌"),
                    "tytul": entry.get("tytul", ""),
                    "opis": entry.get("opis", ""),
                    "time": time_label,
                    "link": entry.get("link", "")
                })

    summary = report_dict.get("bezpieczne_podsumowanie", "")
    if summary:
        items.append({
            "cat": "other",
            "cat_label": "🛡️ Status bezpieczeństwa" if lang == "PL" else "🛡️ Sicherheitsstatus",
            "ikona": "✅",
            "tytul": "Pozostałe monitorowane obszary" if lang == "PL" else "Übrige überwachte Bereiche",
            "opis": summary,
            "time": time_label,
            "link": ""
        })

    return items


def send_onesignal_push(title, message):
    if not ONESIGNAL_APP_ID or not ONESIGNAL_API_KEY:
        print("Brak kluczy OneSignal — pomijam wysyłkę Push.")
        return

    url = "https://onesignal.com"
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Key {ONESIGNAL_API_KEY}"
    }
    payload = {
        "app_id": ONESIGNAL_APP_ID,
        "included_segments": ["Subscribed Users"],
        "headings": {"en": title, "pl": title},
        "contents": {"en": message, "pl": message},
        "url": "https://github.io"
    }

    res = requests.post(url, headers=headers, json=payload, timeout=15)
    print("Status wysyłki OneSignal:", res.status_code, res.text)


def main():
    now_local = datetime.now(LOCAL_TZ)
    print(f"=== Uruchomienie skanera aplikacji: {now_local.strftime('%Y-%m-%d %H:%M %Z')} ===", flush=True)

    known_links = set()
    print("1. Skanowanie źródeł bezpieczeństwa, żywności i fact-checkingu (PL + DE + EU)...", flush=True)
    new_sec_items = fetch_recent_articles(RSS_SOURCES_SECURITY, known_links, hours=24)
    new_gis_items = fetch_gis_warnings(known_links)
    all_sec = new_sec_items + new_gis_items

    print("2. Skanowanie wiadomości z Polski, Niemiec/Hesji, Świata i Rynków...", flush=True)
    all_news = fetch_recent_articles(RSS_SOURCES_WORLD_NEWS, known_links, hours=24)

    print(f"Zebrano -> Alerty (Cyber/Żywność): {len(all_sec)}, Świat/Prawo/Rynki: {len(all_news)}", flush=True)

    if not all_sec and not all_news:
        print("BŁĄD: Nie udało się pobrać żadnych artykułów z kanałów RSS!")
        sys.exit(1)

    sec_text = "\n---\n".join(all_sec[:50])
    news_text = "\n---\n".join(all_news[:50])

    print("[PL] Analiza części 1 (Cyber, Oszustwa i Żywność)...", flush=True)
    part_sec_pl = generate_report_data(sec_text, lang="PL")
    print("[PL] Analiza części 2 (Polska, Niemcy, Świat, Prawo i Giełda)...", flush=True)
    part_news_pl = generate_report_data(news_text, lang="PL")
    report_pl = merge_report_parts(part_sec_pl, part_news_pl, lang="PL")

    print("[DE] Analiza części 1 (Cyber, Betrug & Lebensmittel)...", flush=True)
    part_sec_de = generate_report_data(sec_text, lang="DE")
    print("[DE] Analiza części 2 (Deutschland, Polen, Welt, Recht & Börse)...", flush=True)
    part_news_de = generate_report_data(news_text, lang="DE")
    report_de = merge_report_parts(part_sec_de, part_news_de, lang="DE")

    urgent_list = (report_pl.get("dorosli") or []) + (report_pl.get("dzieci") or [])
    first_urgent = urgent_list if urgent_list and isinstance(urgent_list, dict) else {}
    new_push_title = first_urgent.get("tytul", "")
    new_push_msg = first_urgent.get("opis", "")

    old_push_title = ""
    if os.path.exists("dane.json"):
        try:
            with open("dane.json", "r", encoding="utf-8") as f:
                old_data = json.load(f)
                old_push_title = old_data.get("last_push_title", "")
        except Exception:
            pass

    if new_push_title and new_push_title != old_push_title:
        send_onesignal_push(f"⚠️ {new_push_title}", new_push_msg)

    output_data = {
        "updated_at": now_local.strftime("%d.%m.%Y, %H:%M"),
        "last_push_title": new_push_title or old_push_title,
        "PL": flatten_for_app(report_pl, lang="PL"),
        "DE": flatten_for_app(report_de, lang="DE")
    }

    with open("dane.json", "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print("Zapisano dane.json pomyślnie!", flush=True)


if __name__ == "__main__":
    main()
