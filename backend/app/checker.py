"""Evidence-first brand checker.

Pure function: draft text + approved passages in, findings out. A finding that claims
support must point at a real approved passage; otherwise it is downgraded to 'unverified'.
"""
import re

SUPER = re.compile(
    r"(?<!\w)(best|fastest|cheapest|leading|number one|world-class|unbeatable|"
    r"guarantee[sd]?|guarantees|cure[sd]?|risk-free|clinically proven|100%)(?!\w)",
    re.I,
)
HIGH_RISK = {"guarantee", "guaranteed", "guarantees", "cure", "cured", "cures", "risk-free", "clinically proven", "100%"}
SAFE = {"best": "great", "fastest": "fast", "cheapest": "good-value", "leading": "trusted",
        "world-class": "high-quality", "unbeatable": "strong", "number one": "popular"}
NUM = re.compile(r"(\d[\d,]*)(\+?)\s*(customers|stores|users|clients|countries)", re.I)
HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
TERMS = re.compile(r"avoid[^:\n]*:\s*([^\n]+)", re.I)
CAPS = re.compile(r"\b[A-Z]{4,}\b")
STOP = {"the", "and", "for", "with", "our", "are", "was", "that", "this", "from", "across",
        "into", "your", "you", "all", "any", "not", "its", "one", "per", "use", "new"}


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", s.lower()) if w not in STOP}


def evidence(p, s) -> dict:
    return {"source_id": s.id, "passage_id": p.id, "source_title": f"{s.title} v{s.version}", "evidence": p.text}


def item(category, verdict, excerpt, reason, rule_key, confidence, ev=None, replacement=None, suggestion=None) -> dict:
    d = {"category": category, "verdict": verdict, "excerpt": excerpt, "reason": reason,
         "rule_key": rule_key, "confidence": confidence, "replacement": replacement,
         "suggestion": suggestion, "source_id": None, "passage_id": None,
         "source_title": None, "evidence": None}
    if ev:
        d.update(ev)
    return d


def run_check(text: str, passages: list) -> list[dict]:
    """passages: list of (SourcePassage, Source) for the latest version of each approved source."""
    out: list[dict] = []

    # 1. Figures (customers, stores...) against the fact sheet.
    facts = {}
    for p, s in passages:
        for kw in ("customers", "stores", "users", "clients", "countries"):
            m = re.search(rf"{kw}\s*:\s*([\d,]+)", p.text, re.I) or re.search(rf"([\d,]+)\s*\+?\s*{kw}", p.text, re.I)
            if m and kw not in facts:
                facts[kw] = (int(m.group(1).replace(",", "")), p, s)
    for m in NUM.finditer(text):
        num, plus, kw = int(m.group(1).replace(",", "")), bool(m.group(2)), m.group(3).lower()
        rule = f"factual:{kw}"
        if kw not in facts:
            out.append(item("factual", "unverified", m.group(0), "No approved fact sheet figure covers this claim.", rule, 0.6))
            continue
        actual, p, s = facts[kw]
        ok = actual >= num if plus else actual == num
        if ok:
            out.append(item("factual", "supported", m.group(0), f"Approved fact sheet confirms {actual:,} {kw}.", rule, 0.95, evidence(p, s)))
        else:
            out.append(item("factual", "contradicted", m.group(0), f"Approved fact sheet says {actual:,} {kw}, not {m.group(1)}.",
                            rule, 0.9, evidence(p, s), replacement=m.group(0).replace(m.group(1), f"{actual:,}"),
                            suggestion=f"Use the approved figure: {actual:,}{'+' if plus else ''} {kw}."))

    # 2. Forbidden terms from the brand book.
    terms = {}
    for p, s in passages:
        for m in TERMS.finditer(p.text):
            for t in m.group(1).split(","):
                t = t.strip(" .").lower()
                if t:
                    terms.setdefault(t, (p, s))
    for t, (p, s) in terms.items():
        for m in re.finditer(rf"\b{re.escape(t)}\b", text, re.I):
            out.append(item("terminology", "contradicted", m.group(0), f"The approved terminology list says to avoid '{t}'.",
                            f"terminology:{t}", 0.9, evidence(p, s), suggestion="Rephrase without this term."))

    # 3. Promotional claims: superlatives need benchmarks; high-risk claims go to a human.
    claims = [(p, s) for p, s in passages if s.category == "claims"]
    bench = [(p, s) for p, s in passages if re.search(r"benchmark|measured", p.text, re.I)]

    def policy(key):
        hit = next(((p, s) for p, s in claims if re.search(key, p.text, re.I)), None)
        return evidence(*hit) if hit else None

    for sent in sentences(text):
        for m in SUPER.finditer(sent):
            word = m.group(0).lower()
            if word in HIGH_RISK:
                out.append(item("claims", "human_review", sent, f"'{word}' is a high-risk claim and needs an authorised reviewer.",
                                "claims:high_risk", 0.8, policy("high risk"), suggestion="Remove the claim or send it to a reviewer."))
                continue
            safe = SAFE.get(word, "strong")
            bw = words(sent) - words(word)
            hit = next(((p, s) for p, s in bench if len(bw & words(p.text)) >= 2), None)
            if hit:
                out.append(item("claims", "supported", sent, "An approved benchmark backs this claim.", "claims:superlative", 0.85, evidence(*hit)))
            else:
                out.append(item("claims", "unverified", sent, f"'{word}' needs an approved benchmark, and none was found.",
                                "claims:superlative", 0.6, policy("superlative"),
                                replacement=sent.replace(m.group(0), safe, 1),
                                suggestion=f"Add an approved benchmark, or use '{safe}'."))

    # 4. Tone: shouting and repeated exclamation marks.
    tone = [(p, s) for p, s in passages if s.category == "tone"]

    def tone_ev(key):
        hit = next(((p, s) for p, s in tone if re.search(key, p.text, re.I)), None)
        return evidence(*hit) if hit else None

    bangs = [x for x in sentences(text) if "!" in x]
    for i, x in enumerate(bangs):
        if x.count("!") > 1 or i > 0:
            ev = tone_ev("exclamation")
            out.append(item("tone", "contradicted" if ev else "unverified", x,
                            "Too many exclamation marks for the tone guide." if ev else "No tone rule covers exclamation marks.",
                            "tone:exclamation", 0.8 if ev else 0.5, ev, replacement=re.sub(r"!+", ".", x),
                            suggestion="Keep at most one exclamation mark."))
    for m in CAPS.finditer(text):
        ev = tone_ev("capital")
        out.append(item("tone", "contradicted" if ev else "unverified", m.group(0),
                        "All-capital words read as shouting." if ev else "No tone rule covers capital letters.",
                        "tone:capitals", 0.8 if ev else 0.5, ev, replacement=m.group(0).capitalize(), suggestion="Use sentence case."))

    # 5. Visual identity: colours must come from the approved palette.
    palette, pal = set(), None
    for p, s in passages:
        if re.search(r"palette|colour|color", p.text, re.I):
            palette |= {h.upper() for h in HEX.findall(p.text)}
            pal = pal or (p, s)
    for m in HEX.finditer(text):
        h = m.group(0).upper()
        if h in palette:
            out.append(item("visual", "supported", m.group(0), "Colour is in the approved palette.", "visual:colour", 0.95, evidence(*pal)))
        elif pal:
            out.append(item("visual", "contradicted", m.group(0), f"{h} is not in the approved palette.", "visual:colour", 0.9,
                            evidence(*pal), suggestion="Use a colour from the approved palette."))
        else:
            out.append(item("visual", "unverified", m.group(0), "No approved palette has been uploaded.", "visual:colour", 0.5))

    # Citation validator: a finding may only claim support if it cites a real passage.
    for f in out:
        if f["verdict"] in ("supported", "contradicted") and f["passage_id"] is None:
            f["verdict"] = "unverified"
            f["reason"] += " (citation could not be validated)"
    return out
