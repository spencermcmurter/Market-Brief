"""
Entry point. GitHub Actions runs this. It:
  1. checks it's really ~8 AM Eastern on a run day (Sun-Fri),
  2. reads your watchlist from the Google Sheet,
  3. pulls sector news, company news, U.S. filings, and the calendar,
  4. ranks + de-duplicates,
  5. writes analyst "why it matters" notes (Claude API, with template fallback),
  6. builds the spreadsheet + email, and sends it.

Set FORCE_RUN=1 to bypass the time check (used for testing / manual runs).
"""
import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

import analyst
import brief as B
import emailer
import ranking
import sources
import watchlist

EASTERN = ZoneInfo("America/Toronto")

# Rule-based fallback, used only if the Claude API step is off or fails.
WHY = {
    "Systemic / Geo": "Broad, immediate market impact — sets today's risk tone across oil, yields and rate-sensitive holdings.",
    "Macro": "Scheduled macro / central-bank data that drives the whole tape and your banks, utility and insurers.",
    "Regulatory": "Government or regulator action with a direct, forward effect on the sector.",
    "Filing": "Official filing — the kind of disclosure (guidance, control change, material event) that can move the stock immediately.",
    "Company (top-tier)": "Top-tier corporate event (M&A, leadership or guidance) — clears your bar for company-specific news.",
    "Company (strategic)": "Strategic move (deal, launch or partnership) shaping the company's outlook without being a same-day shock.",
    "Company (result/rating)": "Backward-looking result or rating — lower priority per your forward-looking rule.",
    "Company": "Company mention; monitored but not a same-day catalyst.",
    "Sector / Industry": "Industry trend that shapes a sector you follow.",
    "Operational / low-signal": "Operational item with little direct market impact.",
}


def should_run(now_et):
    if os.environ.get("FORCE_RUN") == "1":
        return True
    if now_et.weekday() == 5:            # Saturday off
        return False
    return now_et.hour == 8


def add_why(items, companies, sectors):
    notes = analyst.analyze(items, companies, sectors)
    for i, it in enumerate(items):
        note = notes.get(str(i)) if notes else None
        if note and note.strip():
            it["why"] = note.strip()
        else:
            base = WHY.get(it.get("category", ""), "Monitored for market relevance.")
            if it.get("sector") and it.get("scope") == "company":
                base += f" (Sector: {it['sector']}.)"
            it["why"] = base
    return items


def main():
    now_et = dt.datetime.now(EASTERN)
    if not should_run(now_et):
        print(f"Not a run moment ({now_et:%Y-%m-%d %H:%M %Z}); exiting quietly.")
        return

    lookback_days = 3 if now_et.weekday() == 6 else 2      # Sunday sweeps the weekend
    date_label = now_et.strftime("%A, %B %d, %Y")

    companies, sectors = watchlist.load_watchlist()
    print(f"Loaded {len(companies)} companies, {len(sectors)} sectors.")

    raw = []
    raw += sources.fetch_sector_news(sectors, lookback_days)
    raw += sources.fetch_company_news(companies, lookback_days)
    raw += sources.fetch_us_filings(companies, lookback_days)
    print(f"Collected {len(raw)} raw items.")

    ranked = ranking.rank_and_dedupe(raw)[:40]
    ranked = add_why(ranked, companies, sectors)
    sections = ranking.to_sections(ranked, cap=40)

    econ, earnings = sources.fetch_calendar(days_ahead=7)

    date_short = now_et.strftime("%Y-%m-%d")
    out_path = f"/tmp/Market_Brief_{date_short}.xlsx"
    B.build_xlsx(sections, econ, earnings, out_path, date_label)
    html_body = B.build_email_html(sections, econ, date_label)

    rf = len(sections["read_first"])
    hi = len(sections["high"])
    subject = f"Market Brief \u2014 {now_et:%a %b %-d} \u00b7 {rf} read-first \u00b7 {hi} high-impact"

    emailer.send_brief(subject, html_body, out_path)
    print(f"Sent: {subject}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
