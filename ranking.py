"""
The ranking brain. Turns raw items into a ranked, de-duplicated brief that
follows the rubric we agreed on:

  HIGH   = immediate / critical market impact (macro today, systemic/geo,
           sector regulation, guidance change, M&A, leadership change, dividend CUT,
           pre-market direction)
  MEDIUM = shapes the sector but not a same-day shock (industry trends, product/
           contract, routine dividend/buyback, secondary data)
  LOW    = delayed / questionable / backward-looking (earnings result alone,
           analyst ratings, insider trades, competitor routine news)
  EXCLUDE= opinion / stock-tip content (already filtered by source blocklist)

Industry news is preferred; company news only surfaces strongly when it clears
a top-tier category ("*" = big for that company).
"""
import re
from difflib import SequenceMatcher

from sources import _source_tier

# --- keyword buckets for category detection ---
HIGH_MACRO = ["rate decision", "interest rate", "fomc", "fed ", "federal reserve",
              "bank of canada", "boc ", "cpi", "inflation", "jobs report", "payrolls",
              "unemployment", "gdp", "central bank", "rate cut", "rate hike"]
HIGH_SYSTEMIC = ["war", "invasion", "strike", "ceasefire", "sanction", "attack",
                 "banking crisis", "bank failure", "default", "shutdown",
                 "government spending", "tariff", "oil price", "strait of hormuz"]
HIGH_REG = ["osfi", "crtc", "regulator", "regulation", "antitrust", "rate case",
            "ruling", "probe", "investigation", "government report"]
HIGH_COMPANY = ["acquire", "acquisition", "merger", "takeover", "buyout", "to buy",
                "guidance", "forecast cut", "cuts outlook", "raises outlook", "warns",
                "ceo", "cfo", "chief executive", "chief financial", "steps down",
                "resigns", "appoint", "dividend cut", "slashes dividend"]
MED_COMPANY = ["launch", "unveils", "contract", "deal", "partnership", "consortium",
               "buyback", "dividend increase", "raises dividend", "expansion", "expands"]
LOW_COMPANY = ["beats", "misses", "earnings", "quarterly results", "reported",
               "price target", "upgrade", "downgrade", "analyst", "rated",
               "insider", "stake"]


def _cat_and_tier(item):
    t = (item.get("title", "") + " " + item.get("subject", "")).lower()
    scope = item.get("scope", "sector")

    if item.get("is_filing"):
        form = item.get("form", "")
        if form in ("8-K", "6-K", "SC 13D", "SC 13D/A", "425"):
            return "Filing", "High", True
        return "Filing", "Medium", True

    if any(k in t for k in HIGH_SYSTEMIC):
        return "Systemic / Geo", "High", False
    if any(k in t for k in HIGH_MACRO):
        return "Macro", "High", False
    if any(k in t for k in HIGH_REG):
        return "Regulatory", "High", scope == "company"

    if scope == "company":
        if any(k in t for k in HIGH_COMPANY):
            return "Company (top-tier)", "High", True
        if any(k in t for k in MED_COMPANY):
            return "Company (strategic)", "Medium", True
        if any(k in t for k in LOW_COMPANY):
            return "Company (result/rating)", "Low", False
        return "Company", "Low", False

    # sector-scope default: industry trend
    return "Sector / Industry", "Medium", False


def _score(item, tier, source_tier):
    base = {"High": 100, "Medium": 55, "Low": 20}[tier]
    base += source_tier * 6                       # reputable outlets rank higher
    if item.get("scope") == "sector":
        base += 8                                 # industry-first preference
    if item.get("scope") == "company" and item.get("priority", "Watch") == "Core":
        base += 4
    if item.get("is_filing"):
        base += 6
    return base


def _norm_title(s):
    s = re.sub(r"[^a-z0-9 ]", "", (s or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def _similar(a, b):
    return SequenceMatcher(None, a, b).ratio()


def rank_and_dedupe(raw_items):
    scored = []
    for it in raw_items:
        st = _source_tier(it.get("source", ""))
        if st == 0:
            continue                              # excluded tip/opinion outlet
        cat, tier, star = _cat_and_tier(it)
        it["category"] = cat
        it["tier"] = tier
        it["company_star"] = star
        it["score"] = _score(it, tier, st)
        it["_norm"] = _norm_title(it.get("title", ""))
        scored.append(it)

    # collapse duplicates: same story across outlets -> keep highest score
    scored.sort(key=lambda x: x["score"], reverse=True)
    kept = []
    for it in scored:
        dup = False
        for k in kept:
            if it.get("ticker") and it["ticker"] == k.get("ticker") and \
               _similar(it["_norm"], k["_norm"]) > 0.62:
                dup = True
                break
            if _similar(it["_norm"], k["_norm"]) > 0.78:
                dup = True
                break
        if not dup:
            kept.append(it)

    # read-first = top High-tier items (macro today + systemic lead the eye)
    order = {"Systemic / Geo": 0, "Macro": 1, "Regulatory": 2}
    highs = [x for x in kept if x["tier"] == "High"]
    highs.sort(key=lambda x: (order.get(x["category"], 9), -x["score"]))
    for x in highs[:3]:
        x["read_first"] = True
    return kept


def to_sections(items, cap=40):
    items = items[:cap]
    return {
        "read_first": [x for x in items if x.get("read_first")],
        "high": [x for x in items if x["tier"] == "High"],
        "medium": [x for x in items if x["tier"] == "Medium"],
        "low": [x for x in items if x["tier"] == "Low"],
    }
