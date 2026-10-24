from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.db import get_db
from app.gaps import apply_proposal, detect
from app.models import AuditLog, Finding, GapProposal, Role, Submission, User, record

router = APIRouter(prefix="/governance", tags=["governance"])
MANAGER = require_roles(Role.brand_manager)
OVERSIGHT = require_roles(Role.brand_manager, Role.compliance)


class DecideIn(BaseModel):
    action: str  # approve | reject


def gap_list(db: Session, brand_id: int) -> list[dict]:
    return [{"id": g.id, "gap_type": g.gap_type, "rule_key": g.rule_key, "summary": g.summary,
             "rewrite": g.rewrite, "evidence_count": g.evidence_count, "status": g.status}
            for g in db.query(GapProposal).filter(GapProposal.brand_id == brand_id).order_by(GapProposal.id.desc())]


@router.get("/gaps")
def gaps(user: User = Depends(OVERSIGHT), db: Session = Depends(get_db)):
    return gap_list(db, user.brand_id)


@router.post("/gaps/run")
def run_gaps(user: User = Depends(MANAGER), db: Session = Depends(get_db)):
    db.flush()
    created = detect(db, user.brand_id)
    record(db, user.brand_id, user.email, "gaps.scanned", f"{created} new proposal(s)")
    db.commit()
    return {"created": created, "gaps": gap_list(db, user.brand_id)}


@router.post("/gaps/{gid}/decide")
def decide_gap(gid: int, body: DecideIn, user: User = Depends(MANAGER), db: Session = Depends(get_db)):
    g = db.get(GapProposal, gid)
    if g is None or g.brand_id != user.brand_id:
        raise HTTPException(404, "Proposal not found")
    if g.status != "pending":
        raise HTTPException(400, "This proposal has already been decided")
    if body.action == "approve":
        apply_proposal(db, g, user.id)
        g.status = "approved"
    elif body.action == "reject":
        g.status = "rejected"
    else:
        raise HTTPException(400, "Action must be approve or reject")
    record(db, user.brand_id, user.email, f"gap.{g.status}", f"{g.rule_key}: {g.summary}")
    db.commit()
    return gap_list(db, user.brand_id)


@router.get("/analytics")
def analytics(user: User = Depends(OVERSIGHT), db: Session = Depends(get_db)):
    subs = db.query(Submission).filter(Submission.brand_id == user.brand_id).all()
    findings = (db.query(Finding).join(Submission, Finding.submission_id == Submission.id)
                .filter(Submission.brand_id == user.brand_id).all())
    approved = sum(1 for s in subs if s.status == "approved")
    evidenced = sum(1 for f in findings if f.passage_id is not None)
    open_gaps = db.query(GapProposal).filter(GapProposal.brand_id == user.brand_id, GapProposal.status == "pending").count()
    return {
        "submissions": len(subs),
        "approved_rate": round(100 * approved / len(subs)) if subs else 0,
        "evidence_coverage": round(100 * evidenced / len(findings)) if findings else 0,
        "open_gaps": open_gaps,
        "verdicts": dict(Counter(f.verdict for f in findings)),
    }


@router.get("/audit")
def audit(user: User = Depends(OVERSIGHT), db: Session = Depends(get_db)):
    rows = (db.query(AuditLog).filter(AuditLog.brand_id == user.brand_id)
            .order_by(AuditLog.id.desc()).limit(200).all())
    return [{"actor": r.actor_email, "action": r.action, "detail": r.detail, "at": r.created_at.isoformat()} for r in rows]
