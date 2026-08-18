"""
Language-model layer. Two jobs, both optional (templates used if no key):
  1. analyze()      -> per-item "why it matters" notes for the spreadsheet
  2. write_brief()  -> the synthesized <=5-page narrative used as the email body

Provider auto-selected by which key is set:
  - ANTHROPIC_API_KEY  -> Claude API (paid)
  - GEMINI_API_KEY     -> Google Gemini API (free tier)
  - neither            -> main.py falls back to templates + the structured list

Gemini "thinking" is disabled so the token budget goes to the answer (newer
flash models otherwise spend it reasoning and return empty text). Failures are
logged with a key-safe [analyst] line and the code tries several model names.
"""
import json
import os

import requests

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest").strip()

GEMINI_FALLBACKS = ["gemini-flash-latest", "gemini-2.5-flash",
                    "gemini-2.5-flash-lite", "gemini-3-flash"]

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
    "Use ONLY these HTML tags: <h2>, <h3>, <p>, <ul>, <li>, <b>:\n"
    "1. <h2>Bottom line</h2> then one <p>: 2-4 sentences on the single most important "
    "thing for today's trading and the overall risk tone into the open.\n"
    "2. <h2>Read first</h2> then a short <ul>: the 2-3 must-reads, one line each.\n"
    "3. Themed sections: 3-6 <h3> sections (e.g. Rates & Central Banks, Geopolitics & "
    "Oil, Canadian Financials, Tech & Quantum) each with a tight <p> that SYNTHESIZES "
    "the related items — do not just list them. Name specific holdings where the link "
    "is real. Forward-looking.\n"
    "4. <h2>Calendar</h2> then a short <ul> of today's and this week's key scheduled "
    "events, if any are provided.\n"
    "5. ONLY IF discovery movers are provided, add <h2>Under the radar</h2> then: a "
    "short <p> spotlighting 1-2 SMALL-CAP names that are moving, each with the "
    "percent move and, where given, the apparent catalyst; then a one-line <p> on a "
    "notable off-watchlist 'headline' mover of any size. These are names outside the "
    "reader's holdings and sectors. Frame them explicitly as speculative leads to "
    "investigate, not recommendations, and note small caps are volatile / higher risk. "
    "Do NOT hype; if a mover has no clear catalyst, say the driver is unclear.\n\n"
    "Rules: under ~1,100 words (well under 5 pages). Prioritise and compress. Do NOT "
    "invent numbers or facts not implied by the inputs. Analyst register: direct, no "
    "marketing tone, no hedging boilerplate. End with one <p> telling the reader the "
    "full ranked list with source links is in the attached spreadsheet. "
    "Output ONLY the HTML fragment, no <html> wrapper, no code fences."
)


def _holdings_str(companies):
    return "; ".join(
        f"{c['company'] or c['ticker']} ({c['ticker']}, {c['exchange']}, {c['sector']})"
        for c in companies if c.get("ticker")
    ) or "(none listed)"


def _anthropic(system, user, max_tokens):
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": ANTHROPIC_MODEL, "max_tokens": max_tokens,
                  "system": system, "messages": [{"role": "user", "content": user}]},
            timeout=120)
        if r.status_code != 200:
            print(f"[analyst] Anthropic HTTP {r.status_code}: {r.text[:300]}")
            return None
        return "".join(b.get("text", "") for b in r.json().get("content", [])
                       if b.get("type") == "text")
    except Exception as e:
        print(f"[analyst] Anthropic request error: {type(e).__name__}: {e}")
        return None


def _gemini(system, user, json_mode, max_tokens):
    models = []
    for m in [GEMINI_MODEL] + GEMINI_FALLBACKS:
        if m and m not in models:
            models.append(m)
    base_cfg = {"maxOutputTokens": max_tokens, "temperature": 0.4}
    if json_mode:
        base_cfg["responseMimeType"] = "application/json"

    def call(model, cfg):
        return requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={GEMINI_API_KEY}",
            headers={"content-type": "application/json"},
            json={"systemInstruction": {"parts": [{"text": system}]},
                  "contents": [{"parts": [{"text": user}]}],
                  "generationConfig": cfg},
            timeout=120)

    for m in models:
        # First try with "thinking" OFF (frees the whole budget for the answer);
        # if a model rejects that field, retry the same model without it.
        for cfg in ({**base_cfg, "thinkingConfig": {"thinkingBudget": 0}}, base_cfg):
            try:
                r = call(m, cfg)
                if r.status_code != 200:
                    body = r.text
                    if "thinking" in body.lower() and "thinkingConfig" in cfg:
                        continue                       # retry same model without it
                    print(f"[analyst] Gemini model '{m}' HTTP {r.status_code}: {body[:300]}")
                    if r.status_code in (401, 403) or "API key not valid" in body:
                        return None
                    break                              # move to next model
                data = r.json()
                cands = data.get("candidates") or []
                if not cands:
                    print(f"[analyst] Gemini '{m}' no candidates: {str(data)[:200]}")
                    break
                parts = cands[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts)
                if text.strip():
                    if m != GEMINI_MODEL:
                        print(f"[analyst] Gemini used fallback model '{m}'.")
                    return text
                print(f"[analyst] Gemini '{m}' empty text (finishReason="
                      f"{cands[0].get('finishReason')}).")
                break                                  # try next model
            except Exception as e:
                print(f"[analyst] Gemini '{m}' request error: {type(e).__name__}: {e}")
                break
    return None


def _complete(system, user, json_mode, max_tokens=8192):
    if ANTHROPIC_API_KEY:
        return _anthropic(system, user, max_tokens)
    if GEMINI_API_KEY:
        return _gemini(system, user, json_mode, max_tokens)
    print("[analyst] No API key set (GEMINI_API_KEY / ANTHROPIC_API_KEY) -> templates.")
    return None


def analyze(items, companies, sectors):
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
        print(f"[analyst] Could not parse notes JSON ({e}).")
        return None


def write_brief(items, econ, companies, sectors, discovery=None):
    if not items:
        return None
    listing = "\n".join(
        f"- [{it['tier']}] {it.get('category','')} | {it.get('subject','')}: "
        f"{it.get('title','')}" for it in items)
    cal = "\n".join(f"- {e.get('date','')} {e.get('country','')} "
                    f"{e.get('event','')} ({e.get('impact','')})"
                    for e in (econ or [])[:15]) or "(none provided)"
    disc = "\n".join(
        f"- {d['symbol']} ({d.get('name','')}) {d.get('bucket','')} "
        f"{d.get('pct',0):+.1f}% at ${d.get('price',0)}"
        + (f" | catalyst: {d['catalyst']}" if d.get("catalyst") else " | catalyst unclear")
        for d in (discovery or [])) or "(none provided)"
    user = (f"Holdings the reader trades around:\n{_holdings_str(companies)}\n\n"
            f"Today's ranked news items (already de-duplicated and ranked):\n{listing}\n\n"
            f"Scheduled calendar events:\n{cal}\n\n"
            f"Discovery movers (off-watchlist, for the Under the radar section):\n{disc}\n\n"
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
