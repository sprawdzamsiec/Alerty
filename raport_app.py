import os
import json
import ssl
import urllib.request
from datetime import datetime, timezone
import feedparser
import certifi
import requests
from google import genai
from google.genai import types

# Konfiguracja kluczy ze zmiennych środowiskowych (GitHub Secrets)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
ONESIGNAL_APP_ID = os.environ.get("ONESIGNAL_APP_ID")
ONESIGNAL_API_KEY = os.environ.get("ONESIGNAL_API_KEY")

# Oficjalne kanały RSS (Polska i Niemcy — bezpieczeństwo, cyberzagrożenia, ostrzeżenia)
RSS_FEEDS = [
    ("CERT Polska", "https://cert.pl"),
    ("Niebezpiecznik", "https://niebezpiecznik.pl"),
    ("Zaufana Trzecia Strona", "https://zaufanatrzeciastrona.pl"),
    ("BSI Deutschland", "https://bund.de"),
    ("Tagesschau", "https://tagesschau.de"),
]

def fetch_rss_items():
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    handler = urllib.request.HTTPSHandler(context=ssl_context)
    collected = []

    for source_name, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url, handlers=[handler])
            for entry in feed.entries[:5]:
                collected.append({
                    "source": source_name,
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:400],
                    "link": entry.get("link", ""),
                    "published": entry.get("published", "")
                })
        except Exception as e:
            print(f"Błąd pobierania RSS ({source_name}): {e}")
    return collected

def analyze_with_gemini(articles):
    client = genai.Client(api_key=GEMINI_API_KEY)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    prompt = f"""
    Jesteś asystentem bezpieczeństwa dla rodziny i przyjaciół mieszkających w Polsce i Niemczech.
    Przeanalizuj poniższe najnowsze wiadomości z kanałów RSS i wybierz maksymalnie 8 najważniejszych, realnych zagrożeń lub przydatnych ostrzeżeń (np. nowe oszustwa SMS/BLIK, wycieki danych, wycofanie skażonej żywności, awarie, ważne zmiany w prawie w PL/DE, ostrzeżenia graniczne).
    Ignoruj zwykłą politykę i plotki.

    Zwróć wynik WYŁĄCZNIE jako poprawny obiekt JSON o dokładnie takiej strukturze:
    {{
      "updated_at": "{now_str}",
      "urgent_push": {{
        "send": true/false (ustaw true TYLKO jeśli pojawiło się nowe, pilne zagrożenie wymagające natychmiastowego ostrzeżenia rodziny, np. masowy atak phishingowy lub pilne wycofanie produktu),
        "title": "Krótki tytuł alertu po polsku (max 50 znaków)",
        "message": "Krótka treść alertu po polsku (max 140 znaków)"
      }},
      "PL": [
        {{
          "cat": "jedna z wartości: advice, cyber, food, law, market, other",
          "cat_label": "Polska nazwa kategorii (np. Cyber i Oszustwa, Zalecenia, Żywność i Awarie, Prawo, Giełda, Granice)",
          "ikona": "odpowiednie emoji np. 🚨, ⚠️, 📱, 🥫",
          "tytul": "Zrozumiały tytuł po polsku",
          "opis": "Krótkie, konkretne podsumowanie po polsku i co zrobić, żeby się chronić (2-3 zdania).",
          "time": "Dzisiaj",
          "link": "dokładny URL źródła z danych wejściowych"
        }}
      ],
      "DE": [
        {{
          "cat": "ta sama kategoria co w PL: advice, cyber, food, law, market, other",
          "cat_label": "Niemiecka nazwa kategorii (np. Cyber & Betrug, Empfehlungen, Lebensmittel & Ausfälle, Recht, Börse, Grenzen)",
          "ikona": "emoji",
          "tytul": "Zrozumiały tytuł po niemiecku",
          "opis": "Krótkie, konkretne podsumowanie po niemiecku (2-3 zdania).",
          "time": "Heute",
          "link": "dokładny URL źródła"
        }}
      ]
    }}

    Dane wejściowe RSS:
    {json.dumps(articles, ensure_ascii=False)}
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )
    return json.loads(response.text)

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
    articles = fetch_rss_items()
    if not articles:
        print("Brak nowych artykułów RSS.")
        return

    data = analyze_with_gemini(articles)

    # Sprawdzenie, czy nie wysyłamy tego samego alertu drugi raz
    old_push_title = ""
    if os.path.exists("dane.json"):
        try:
            with open("dane.json", "r", encoding="utf-8") as f:
                old_data = json.load(f)
                old_push_title = old_data.get("urgent_push", {}).get("title", "")
        except Exception:
            pass

    urgent = data.get("urgent_push", {})
    if urgent.get("send") and urgent.get("title") and urgent.get("title") != old_push_title:
        send_onesignal_push(urgent["title"], urgent["message"])

    with open("dane.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("Zapisano dane.json pomyślnie.")

if __name__ == "__main__":
    main()
