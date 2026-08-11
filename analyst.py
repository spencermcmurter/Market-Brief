"""
Language-model layer. Two jobs, both optional (templates/list used if no key):
  1. analyze()      -> per-item "why it matters" notes for the spreadsheet
  2. write_brief()  -> the synthesized <=5-page narrative used as the email body

Provider auto-selected by which key is set:
  - ANTHROPIC_API_KEY  -> Claude API (paid)
  - GEMINI_API_KEY     -> Google Gemini API (free tier)
  - neither            -> main.py falls back to templates + the structured list
Any failure returns None so the brief always goes out.
"""
import json
import os

import requests

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()

NOTES_SYSTEM = (
    "You are a markets analyst writing the morning 'why it matters' notes for a "
    "portfolio manager who trades Canadian (TSX) and U.S. (NYSE/Nasdaq) equities. "
    "For each news item, write the kind of crisp, senior-level note a sell-side "
    "analyst sends their desk before the open.\n\n"
    "Each note: (1) state what the development is in market terms; (2) explain the "
    "transmission mechanism to prices, yields, the sector, or the reader's holdings; "
    "(3) give the forward implication for today/this week.\n\n"
    "Rules: connect to named holdings ONLY where real; be forward-looking; do NOT "
    "invent numbers or facts not implied by the headline; analyst register, no "
    "boilerplate; 1-3 sentences each, no preamble."
)

BRIEF_SYSTEM = (
    "You are the lead analyst writing the morning market briefing for a portfolio "
    "manager who trades Canadian (TSX) and U.S. (NYSE/Nasdaq) equities. Synthesize "
    "the day's news into one cohesive, skimmable briefing the reader can absorb in "
    "a few minutes instead of reading every article.\n\n"
    "Write it to this structure, using ONLY these HTML tags: <h2>, <h3>, <p>, <ul>, "
    "<li>, <b>:\n"
    "1. <h2>Bottom line</h2> then one <p>: 2-4 sentences on the single most important "
    "thing for today's trading and the overall risk tone into the open.\n"
    "2. <h2>Read first</h2> then a short <ul>: the 2-3 must-reads, one line each.\n"
    "3. Themed sections: 3-6 <h3> sections (e.g. Rates & Central Banks, Geopolitics & "
    "Oil, Canadian Financials, Tech & Quantum) each with a tight <p> that SYNTHESIZES "
    "the related items — do not just list them. Name specific holdings where the link "
    "is real. Forward-looking.\n"
    "4. <h2>Calendar</h2> then a short <ul> of today's and this week's key scheduled "
    "events, if any are provided.\n\n"
    "Rules: keep the whole thing under ~1,100 words (well under 5 pages). Prioritise "
    "and compress — omit trivia. Do NOT invent numbers, prices or facts not implied by "
    "the inputs. Analyst register: direct, substantive, no marketing tone, no hedging "
    "boilerplate. End with one <p> in grey-ish plain wording telling the reader the "
    "full ranked list with source links is in the attached spreadsheet. "
    "Output ONLY the HTML fragment, no <html> wrapper, no code fences."
)


def _holdings_str(companies):
    return "; ".join(
        f"{c['company'] or c['ticker']} ({c['ticker']}, {c['exchange']}, {c['sector']})"
        for c in companies if c.get("ticker")
    ) or "(none listed)"


def _complete(system, user, json_mode, max_tokens=4000):
    """Route to whichever provider is configured. Returns raw text or None."""
    if ANTHROPIC_API_KEY:
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_API_KEY,
                         "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": ANTHROPIC_MODEL, "max_tokens": max_tokens,
                      "system": system, "messages": [{"role": "user", "content": user}]},
                timeout=120)
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json().get("content", [])
                           if b.get("type") == "text")
        except Exception as e:
            print(f"Anthropic call failed ({e}).")
            return None
    if GEMINI_API_KEY:
        try:
            cfg = {"maxOutputTokens": max_tokens, "temperature": 0.4}
            if json_mode:
                cfg["responseMimeType"] = "application/json"
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
                headers={"content-type": "application/json"},
                json={"systemInstruction": {"parts": [{"text": system}]},
                      "contents": [{"parts": [{"text": user}]}],
                      "generationConfig": cfg},
                timeout=120)
            r.raise_for_status()
            parts = r.json()["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except Exception as e:
            print(f"Gemini call failed ({e}).")
            return None
    return None


def analyze(items, companies, sectors):
    """Per-item notes -> {index_str: note} or None."""
    if not items:
        return None
    themes = ", ".join(s["sector"] for s in sectors) or "(none listed)"
    listing = "\n".join(
        f"[{i}] tier={it['tier']} | category={it['category']} | "
        f"subject={it.get('subject','')} | headline: {it.get('title','')}"
        for i, it in enumerate(items))
    user = (f"Holdings the reader trades around:\n{_holdings_str(companies)}\n\n"
            f"Active themes: {themes}\n\n"
            "Write an analyst note for each item. Return ONLY a JSON object mapping "
            'the item index (as a string) to its note, e.g. {"0":"...","1":"..."}.\n\n'
            f"Items:\n{listing}")
    text = _complete(NOTES_SYSTEM, user, json_mode=True)
    if not text:
        return None
    try:
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text[:4].lower() == "json":
                text = text[4:]
        return json.loads(text)
    except Exception as e:
        print(f"Could not parse notes JSON ({e}).")
        return None


def write_brief(items, econ, companies, sectors):
    """Synthesized narrative HTML for the email body, or None."""
    if not items:
        return None
    listing = "\n".join(
        f"- [{it['tier']}] {it.get('category','')} | {it.get('subject','')}: "
        f"{it.get('title','')}"
        for it in items)
    cal = "\n".join(f"- {e.get('date','')} {e.get('country','')} "
                    f"{e.get('event','')} ({e.get('impact','')})"
                    for e in (econ or [])[:15]) or "(none provided)"
    user = (f"Holdings the reader trades around:\n{_holdings_str(companies)}\n\n"
            f"Today's ranked news items (already de-duplicated and ranked):\n{listing}\n\n"
            f"Scheduled calendar events:\n{cal}\n\n"
            "Write the morning briefing per your instructions.")
    html = _complete(BRIEF_SYSTEM, user, json_mode=False)
    if not html:
        return None
    html = html.strip()
    if html.startswith("```"):
        html = html.strip("`")
        if html[:4].lower() == "html":
            html = html[4:]
    return html.strip()
