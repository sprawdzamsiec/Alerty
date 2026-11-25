import os
import sys
import json
from datetime import datetime, timezone
import feedparser
import requests
from google import genai
from google.genai import types

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
ONESIGNAL_APP_ID = os.environ.get("ONESIGNAL_APP_ID")
ONESIGNAL_API_KEY = os.environ.get("ONESIGNAL_API_KEY")

FEEDS = [
    ("Wiadomości PL", "https://google.com"),
    ("Technologia PL", "https://google.com"),
    ("Biznes i Prawo PL", "https://google.com"),
    ("Nachrichten DE", "https://google.com"),
    ("Technologie DE", "https://google.com"),
    ("Wirtschaft DE", "https://google.com"),
]

def fetch_rss_items():
    collected = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    for source_name, url in FEEDS:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            print(f"Pobrano {len(feed.entries)} wpisów z: {source_name}")
            for entry in feed.entries[:10]:
                collected.append({
                    "source": source_name,
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", "")
                })
        except Exception as e:
            print(f"Błąd pobierania ({source_name}): {e}")
    return collected

def analyze_with_gemini(articles):
    if not GEMINI_API_KEY:
        raise ValueError("BŁĄD: Brak klucza GEMINI_API_KEY w GitHub Secrets!")

    client = genai.Client(api_key=GEMINI_API_KEY)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    prompt = f"""
    Jesteś asystentem bezpieczeństwa dla rodziny i przyjaciół mieszkających w Polsce i Niemczech.
    Przeanalizuj poniższe najnowsze nagłówki wiadomości i wybierz maksymalnie 8 najważniejszych informacji z zakresu:
    - cyberbezpieczeństwa i nowych oszustw (SMS, BLIK, banki, wycieki danych),
    - ostrzeżeń konsumenckich (wycofana żywność, niebezpieczne produkty, awarie),
    - ważnych zmian w prawie, gospodarce, na giełdzie lub na granicach w PL i DE.
    Jeśli w danym momencie nie ma krytycznych oszustw, wybierz najistotniejsze praktyczne wiadomości dla mieszkańców Polski i Niemiec.

    Zwróć wynik WYŁĄCZNIE jako poprawny obiekt JSON o dokładnie takiej strukturze:
    {{
      "updated_at": "{now_str}",
      "urgent_push": {{
        "send": false,
        "title": "Krótki tytuł alertu po polsku (max 50 znaków)",
        "message": "Krótka treść alertu po polsku (max 140 znaków)"
      }},
      "PL": [
        {{
          "cat": "jedna z wartości: advice, cyber, food, law, market, other",
          "cat_label": "Polska nazwa kategorii (np. Cyber i Oszustwa, Zalecenia, Żywność i Awarie, Prawo, Giełda, Granice)",
          "ikona": "odpowiednie emoji np. 🚨, ⚠️, 📱, 🥫, 📈",
          "tytul": "Zrozumiały tytuł po polsku",
          "opis": "Krótkie, konkretne podsumowanie po polsku i praktyczna wskazówka (2-3 zdania).",
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

    Dane wejściowe:
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
    print(f"Łącznie zebrano artykułów: {len(articles)}")
    if not articles:
        print("BŁĄD: Nie udało się pobrać żadnych artykułów z RSS!")
        sys.exit(1)

    data = analyze_with_gemini(articles)

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
