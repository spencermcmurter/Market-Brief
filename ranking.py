"""
The ranking brain. Turns raw items into a ranked, de-duplicated brief following
the agreed rubric. Matching uses WHOLE-WORD boundaries so "war" no longer matches
"software" and "fed" no longer matches "federal". A noise filter drops operational
stories (labour disputes, sponsorships, galas) that share keywords with real events.
"""
import re
from difflib import SequenceMatcher

from sources import _source_tier

HIGH_MACRO = ["rate decision", "interest rate", "interest rates", "fomc",
              "federal reserve", "bank of canada", "boc", "cpi", "inflation",
              "jobs report", "payrolls", "nonfarm", "unemployment rate", "gdp",
              "central bank", "rate cut", "rate hike", "monetary policy",
              "fed minutes", "fed chair", "quantitative"]
HIGH_SYSTEMIC = ["war", "warfare", "invasion", "ceasefire", "airstrike", "air strike",
                 "air strikes", "missile", "missiles", "military strike",
                 "drone strike", "sanction", "sanctions", "embargo",
                 "banking crisis", "bank failure", "sovereign default",
                 "government shutdown", "government spending", "stimulus",
                 "tariff", "tariffs", "oil price", "oil prices",
                 "strait of hormuz", "geopolitical"]
HIGH_REG = ["osfi", "crtc", "regulator", "regulators", "regulation", "antitrust",
            "rate case", "ruling", "sanctioned", "probe", "investigation",
            "government report", "competition bureau"]
HIGH_COMPANY = ["acquire", "acquires", "acquisition", "merger", "merges", "takeover",
                "buyout", "to buy", "guidance", "cuts outlook", "raises outlook",
                "profit warning", "warns", "ceo", "cfo", "chief executive",
                "chief financial", "steps down", "resigns", "resign", "appoints",
                "appointment", "dividend cut", "slashes dividend", "cuts dividend"]
MED_COMPANY = ["launch", "launches", "unveils", "contract", "deal", "partnership",
               "consortium", "buyback", "share buyback", "dividend increase",
               "raises dividend", "expansion", "expands", "invests", "investment"]
LOW_COMPANY = ["beats", "misses", "earnings", "quarterly results", "reported",
               "price target", "upgrade", "downgrade", "analyst", "rated",
               "insider", "stake", "short seller"]

NOISE = ["replacement workers", "labour board", "labor board", "union", "picket",
         "collective agreement", "strike vote", "on strike", "layoff", "layoffs",
         "sponsor", "sponsorship", "donates", "donation", "charity", "foundation",
         "gala", "golf", "obituary", "wins award", "named to", "employee of"]


def _has(text, keywords):
    for kw in keywords:
        if re.search(r"\b" + re.escape(kw) + r"\b", text):
            return kw
    return None


def _cat_and_tier(item):
    t = (item.get("title", "") + " " + item.get("subject", "")).lower()
    scope = item.get("scope", "sector")

    if item.get("is_filing"):
        form = item.get("form", "")
        if form in ("8-K", "6-K", "SC 13D", "SC 13D/A", "425"):
            return "Filing", "High", True
        return "Filing", "Medium", True

    if _has(t, NOISE):
        return "Operational / low-signal", "Low", False

    if _has(t, HIGH_SYSTEMIC):
        return "Systemic / Geo", "High", False
    if _has(t, HIGH_MACRO):
        return "Macro", "High", False
    if _has(t, HIGH_REG):
        return "Regulatory", "High", scope == "company"

    if scope == "company":
        if _has(t, HIGH_COMPANY):
            return "Company (top-tier)", "High", True
        if _has(t, MED_COMPANY):
            return "Company (strategic)", "Medium", True
        if _has(t, LOW_COMPANY):
            return "Company (result/rating)", "Low", False
        return "Company", "Low", False

    return "Sector / Industry", "Medium", False


def _score(item, tier, source_tier):
    base = {"High": 100, "Medium": 55, "Low": 20}[tier]
    base += source_tier * 6
    if item.get("scope") == "sector":
        base += 8
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
            continue
        cat, tier, star = _cat_and_tier(it)
        it["category"] = cat
        it["tier"] = tier
        it["company_star"] = star
        it["score"] = _score(it, tier, st)
        it["_norm"] = _norm_title(it.get("title", ""))
        scored.append(it)

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
