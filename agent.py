import os
import json
import time
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

import requests
from flask import Flask, request, jsonify

# -------------------------------------------------
# Konfiguracja podstawowa
# -------------------------------------------------

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

if not GEMINI_API_KEY:
    app.logger.warning("Brak GEMINI_API_KEY w zmiennych środowiskowych. "
                       "Ustaw ją w Render → Environment.")


# -------------------------------------------------
# Prosta pamięć w RAM (per proces)
# -------------------------------------------------

# Struktura:
# {
#   "session_id": str,
#   "role": "user" | "assistant" | "system" | "webhook",
#   "content": str,
#   "timestamp": float
# }
MEMORY: List[Dict[str, Any]] = []


def add_memory_entry(session_id: str, role: str, content: str) -> None:
    MEMORY.append(
        {
            "session_id": session_id,
            "role": role,
            "content": content,
            "timestamp": time.time(),
        }
    )


def get_session_history(session_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    history = [m for m in MEMORY if m["session_id"] == session_id]
    # sort by time, newest last
    history = sorted(history, key=lambda x: x["timestamp"])
    return history[-limit:]


# -------------------------------------------------
# Integracja z Gemini (REST API)
# -------------------------------------------------

def call_gemini(
    prompt: str,
    system_instructions: Optional[str] = None,
    history: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Wywołanie Gemini przez REST API.
    - prompt: aktualna wiadomość użytkownika
    - system_instructions: rola / opis agenta
    - history: lista poprzednich wiadomości (user/assistant)
    """

    if not GEMINI_API_KEY:
        return "Błąd: Brak klucza GEMINI_API_KEY po stronie serwera."

    contents = []

    # System prompt jako pierwsza wiadomość (opcjonalnie)
    if system_instructions:
        contents.append(
            {
                "role": "user",
                "parts": [{"text": f"[SYSTEM INSTRUCTIONS]\n{system_instructions}"}],
            }
        )

    # Historia rozmowy
    if history:
        for msg in history:
            role = msg.get("role", "user")
            text = msg.get("content", "")
            # Mapujemy role na format Gemini
            if role == "assistant":
                g_role = "model"
            elif role == "system":
                g_role = "user"
            elif role == "webhook":
                g_role = "user"
                text = f"[WEBHOOK EVENT]\n{text}"
            else:
                g_role = "user"

            contents.append(
                {
                    "role": g_role,
                    "parts": [{"text": text}],
                }
            )

    # Aktualna wiadomość użytkownika
    contents.append(
        {
            "role": "user",
            "parts": [{"text": prompt}],
        }
    )

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.6,
            "maxOutputTokens": 1024,
        },
    }

    headers = {
        "Content-Type": "application/json",
    }

    params = {
        "key": GEMINI_API_KEY,
    }

    try:
        resp = requests.post(
            GEMINI_ENDPOINT,
            headers=headers,
            params=params,
            data=json.dumps(payload),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        # Proste wyciągnięcie tekstu z odpowiedzi
        candidates = data.get("candidates", [])
        if not candidates:
            return "Brak odpowiedzi od modelu."

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return "Model nie zwrócił treści."

        return parts[0].get("text", "").strip() or "Model zwrócił pustą odpowiedź."
    except Exception as e:
        app.logger.exception("Błąd podczas wywołania Gemini")
        return f"Błąd podczas wywołania Gemini: {e}"


# -------------------------------------------------
# Proste akcje / komendy
# -------------------------------------------------

def handle_command(
    session_id: str,
    message: str,
) -> Optional[Dict[str, Any]]:
    """
    Proste komendy tekstowe:
    - /remember <tekst>  → zapisuje do pamięci
    - /history           → zwraca historię
    - /fetch <url>       → pobiera stronę i streszcza
    Zwraca dict z odpowiedzią lub None, jeśli to nie komenda.
    """

    msg = message.strip()

    # /remember
    if msg.lower().startswith("/remember "):
        to_remember = msg[len("/remember "):].strip()
        add_memory_entry(session_id, "system", f"[REMEMBER] {to_remember}")
        return {
            "type": "remember",
            "response": f"Zapamiętałem: {to_remember}",
        }

    # /history
    if msg.lower().startswith("/history"):
        history = get_session_history(session_id, limit=50)
        lines = []
        for h in history:
            ts = datetime.fromtimestamp(h["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"[{ts}] {h['role']}: {h['content']}")
        text = "\n".join(lines) if lines else "Brak historii dla tej sesji."
        return {
            "type": "history",
            "response": text,
        }

    # /fetch <url>
    if msg.lower().startswith("/fetch "):
        url = msg[len("/fetch "):].strip()
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            content = r.text[:4000]  # ograniczamy długość
            summary_prompt = (
                f"Streść krótko zawartość tej strony w języku polskim:\n\n{content}"
            )
            summary = call_gemini(
                prompt=summary_prompt,
                system_instructions="Jesteś asystentem, który streszcza strony internetowe.",
            )
            return {
                "type": "fetch",
                "response": f"Streszczenie strony {url}:\n\n{summary}",
            }
        except Exception as e:
            return {
                "type": "fetch_error",
                "response": f"Nie udało się pobrać strony {url}: {e}",
            }

    # Nie jest komendą
    return None


# -------------------------------------------------
# Endpoint: /
# -------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    return """
    <html>
      <head><title>Agent API</title></head>
      <body>
        <h1>Agent działa ✅</h1>
        <p>Endpoint API: <code>/agent</code> (POST, JSON)</p>
        <p>Przykładowe komendy:</p>
        <ul>
          <li><code>/remember coś do zapamiętania</code></li>
          <li><code>/history</code></li>
          <li><code>/fetch https://example.com</code></li>
        </ul>
      </body>
    </html>
    """, 200


# -------------------------------------------------
# Endpoint: /agent
# -------------------------------------------------

@app.route("/agent", methods=["POST"])
def agent_endpoint():
    """
    Oczekuje JSON:
    {
      "message": "tekst użytkownika",
      "session_id": "opcjonalny identyfikator sesji"
    }
    """

    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    session_id = data.get("session_id") or "default"

    if not message:
        return jsonify({"error": "Brak pola 'message' w JSON."}), 400

    app.logger.info(f"[SESSION {session_id}] USER: {message}")

    # Zapisujemy wiadomość użytkownika do pamięci
    add_memory_entry(session_id, "user", message)

    # Sprawdzamy, czy to komenda
    cmd_result = handle_command(session_id, message)
    if cmd_result is not None:
        response_text = cmd_result["response"]
        add_memory_entry(session_id, "assistant", response_text)
        return jsonify(
            {
                "ok": True,
                "type": cmd_result["type"],
                "response": response_text,
            }
        )

    # Jeśli to nie komenda → idzie do Gemini
    history = get_session_history(session_id, limit=20)

    system_instructions = (
        "Jesteś osobistym agentem użytkownika Marek. "
        "Masz być konkretny, pomocny, praktyczny. "
        "Jeśli użytkownik prosi o działanie, najpierw wyjaśnij, co zrobisz."
    )

    gemini_reply = call_gemini(
        prompt=message,
        system_instructions=system_instructions,
        history=history,
    )

    # Zapisujemy odpowiedź modelu do pamięci
    add_memory_entry(session_id, "assistant", gemini_reply)

    return jsonify(
        {
            "ok": True,
            "type": "gemini",
            "response": gemini_reply,
        }
    )


# -------------------------------------------------
# Endpoint: /webhook
# -------------------------------------------------

@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Uniwersalny webhook.
    Odbiera dowolny JSON i zapisuje go do pamięci jako event.
    Opcjonalnie może przekazać go do Gemini do interpretacji.
    """

    payload = request.get_json(silent=True) or {}
    session_id = payload.get("session_id") or "webhook"

    pretty = json.dumps(payload, ensure_ascii=False, indent=2)
    add_memory_entry(session_id, "webhook", pretty)

    # Opcjonalna interpretacja przez Gemini
    interpret = payload.get("interpret_with_gemini", False)

    gemini_summary = None
    if interpret:
        prompt = (
            "Otrzymałeś następujące zdarzenie webhook (JSON). "
            "Wyjaśnij po polsku, co ono oznacza i co można z nim zrobić:\n\n"
            f"{pretty}"
        )
        gemini_summary = call_gemini(
            prompt=prompt,
            system_instructions="Jesteś asystentem, który tłumaczy zdarzenia systemowe.",
        )
        add_memory_entry(session_id, "assistant", gemini_summary)

    return jsonify(
        {
            "ok": True,
            "message": "Webhook odebrany.",
            "session_id": session_id,
            "gemini_summary": gemini_summary,
        }
    )


# -------------------------------------------------
# Uruchomienie lokalne
# -------------------------------------------------

if __name__ == "__main__":
    # Lokalnie możesz odpalić: python agent.py
    app.run(host="0.0.0.0", port=8000, debug=True)






