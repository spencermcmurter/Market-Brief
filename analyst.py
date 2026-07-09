"""
Writes the "why it matters" notes using the Claude API — one batched call per
run. It sees each item plus your holdings and active themes, and returns a short
analyst-grade note per item (what it is, the transmission mechanism, the forward
implication for your names).

If ANTHROPIC_API_KEY is not set, or the call fails for any reason, main.py falls
back to the rule-based templates so the brief always goes out.
"""
import json
import os

import requests

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5").strip()

SYSTEM = (
    "You are a markets analyst writing the morning 'why it matters' notes for a "
    "portfolio manager who trades Canadian (TSX) and U.S. (NYSE/Nasdaq) equities. "
    "For each news item, write the kind of crisp, senior-level note a sell-side "
    "analyst sends their desk before the open.\n\n"
    "Each note must do three things: (1) state what the development actually is in "
    "market terms; (2) explain the transmission mechanism — how it flows through to "
    "prices, yields, the sector, or the reader's specific holdings; (3) give the "
    "forward implication for today / this week (directional: pressures margins, "
    "supports multiples, raises tail risk, etc.).\n\n"
    "Rules:\n"
    "- Connect to the reader's named holdings or sectors ONLY where the link is real; "
    "never force a connection that isn't there.\n"
    "- Be forward-looking: what it means for what's ahead, not a recap of the past.\n"
    "- Do NOT invent numbers, prices, or facts not implied by the headline. Reason "
    "about direction and mechanism. If the headline is thin, say precisely what to "
    "watch and why it would matter.\n"
    "- Analyst register: direct and substantive. No hedging boilerplate, no phrases "
    "like 'this could move markets', no marketing tone. Assume a sophisticated reader.\n"
    "- 1-3 sentences each. No preamble, no bullet points."
)


def analyze(items, companies, sectors):
    """Returns {index_str: note} or None to signal fallback."""
    if not API_KEY or not items:
        return None

    holdings = "; ".join(
        f"{c['company'] or c['ticker']} ({c['ticker']}, {c['exchange']}, {c['sector']})"
        for c in companies if c.get("ticker")
    ) or "(none listed)"
    themes = ", ".join(s["sector"] for s in sectors) or "(none listed)"

    listing = "\n".join(
        f"[{i}] tier={it['tier']} | category={it['category']} | "
        f"subject={it.get('subject','')} | headline: {it.get('title','')}"
        for i, it in enumerate(items)
    )

    user = (
        f"Holdings the reader trades around:\n{holdings}\n\n"
        f"Active themes on the watchlist: {themes}\n\n"
        "Write an analyst 'why it matters' note for each item below. "
        'Return ONLY a JSON object mapping the item index (as a string) to its note, '
        'e.g. {"0": "...", "1": "..."}. No other text.\n\n'
        f"Items:\n{listing}"
    )

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 3000,
                "system": SYSTEM,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=90,
        )
        resp.raise_for_status()
        data = resp.json()
        text = "".join(b.get("text", "") for b in data.get("content", [])
                        if b.get("type") == "text").strip()
        # strip accidental code fences
        if text.startswith("```"):
            text = text.strip("`")
            if text[:4].lower() == "json":
                text = text[4:]
        return json.loads(text)
    except Exception as e:
        print(f"Analyst step failed ({e}); falling back to templates.")
        return None
