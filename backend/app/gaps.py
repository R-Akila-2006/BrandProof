"""Guideline Gap Detector: turns repeated disputes and unverified claims into reviewable rule proposals."""
import os

from app.models import Decision, Finding, GapProposal, Source, SourcePassage, Submission

MIN_RECORDS = int(os.getenv("GAP_MIN_RECORDS", "3"))

REWRITES = {
    "claims:superlative": "Superlatives such as best, fastest or cheapest need an approved benchmark in the claims library. Without one, use descriptive wording such as 'great' or 'fast'.",
    "claims:high_risk": "Guarantee, cure and risk-free claims always need an authorised reviewer and can never publish on AI judgement alone.",
    "factual:customers": "Customer counts must match the current fact sheet. Use '+' only when the approved figure is at least that large.",
    "tone:exclamation": "Use at most one exclamation mark per post, and none in whitepapers or B2B content.",
    "tone:capitals": "Do not use all-capital words for emphasis. Use sentence case.",
    "visual:colour": "Use only colours listed in the approved palette in published content.",
}
CATEGORY_OF = {"claims": "claims", "tone": "tone", "factual": "facts", "visual": "visual"}


def detect(db, brand_id: int) -> int:
    covered = {g.rule_key for g in db.query(GapProposal).filter(GapProposal.brand_id == brand_id)}
    disputes, unverified = {}, {}
    for d in (db.query(Decision).join(Submission, Decision.submission_id == Submission.id)
              .filter(Submission.brand_id == brand_id, Decision.action == "dispute")):
        disputes[d.rule_key] = disputes.get(d.rule_key, 0) + 1
    for f in (db.query(Finding).join(Submission, Finding.submission_id == Submission.id)
              .filter(Submission.brand_id == brand_id, Finding.verdict == "unverified")):
        unverified[f.rule_key] = unverified.get(f.rule_key, 0) + 1

    created = 0

    def propose(gap, rule, n, summary):
        nonlocal created
        db.add(GapProposal(
            brand_id=brand_id, gap_type=gap, rule_key=rule, summary=summary, evidence_count=n,
            rewrite=REWRITES.get(rule, f"Add an approved source that states the rule for '{rule}', with a measurable do and don't example."),
        ))
        covered.add(rule)
        created += 1

    for rule, n in disputes.items():
        if rule and n >= MIN_RECORDS and rule not in covered:
            propose("ambiguous", rule, n, f"{n} disputed findings under '{rule}' suggest the rule is unclear.")
    for rule, n in unverified.items():
        if rule and n >= MIN_RECORDS and rule not in covered:
            propose("missing", rule, n, f"{n} claims went unverified under '{rule}' because no approved evidence covers them.")
    return created


def apply_proposal(db, g: GapProposal, actor_id: int) -> None:
    """Approving a proposal adds it as a new version of the matching guideline update source."""
    cat = CATEGORY_OF.get(g.rule_key.split(":")[0], "general")
    title = f"Guideline Updates ({cat})"
    prev = (db.query(Source).filter(Source.brand_id == g.brand_id, Source.title == title)
            .order_by(Source.version.desc()).first())
    texts = [p.text for p in prev.passages] if prev else []
    texts.append(g.rewrite)
    src = Source(brand_id=g.brand_id, title=title, category=cat, version=(prev.version + 1 if prev else 1),
                 filename=f"{cat}-guideline-updates.txt", owner_id=actor_id)
    src.passages = [SourcePassage(position=i, text=t) for i, t in enumerate(texts)]
    db.add(src)
