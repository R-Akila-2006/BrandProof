from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.checker import run_check
from app.db import get_db
from app.models import Decision, Finding, Role, Source, SourcePassage, Submission, User, record

router = APIRouter(prefix="/submissions", tags=["submissions"])
CREATORS = (Role.creator, Role.brand_manager)
REVIEWERS = (Role.reviewer, Role.brand_manager, Role.compliance)


class SubmitIn(BaseModel):
    title: str
    channel: str = "web"
    text: str


class TextIn(BaseModel):
    text: str = ""


class NoteIn(BaseModel):
    note: str = ""


class DecisionIn(BaseModel):
    action: str  # approve | revise
    note: str = ""


def current_passages(db: Session, brand_id: int):
    """Passages from the latest version of each approved source."""
    rows = (db.query(SourcePassage, Source).join(Source, SourcePassage.source_id == Source.id)
            .filter(Source.brand_id == brand_id).all())
    latest: dict[str, int] = {}
    for _, s in rows:
        latest[s.title] = max(latest.get(s.title, 0), s.version)
    return [(p, s) for p, s in rows if s.version == latest[s.title]]


def email_of(db: Session, user_id: int) -> str:
    u = db.get(User, user_id)
    return u.email if u else "unknown"


def run(db: Session, s: Submission) -> None:
    s.findings = [Finding(**f) for f in run_check(s.text, current_passages(db, s.brand_id))]


def sub_out(db: Session, s: Submission) -> dict:
    keys = ("id", "category", "verdict", "excerpt", "replacement", "reason", "suggestion",
            "confidence", "rule_key", "source_title", "evidence", "status")
    return {
        "id": s.id, "title": s.title, "channel": s.channel, "text": s.text, "status": s.status,
        "creator": email_of(db, s.creator_id), "creator_id": s.creator_id, "created_at": s.created_at.isoformat(),
        "findings": [{k: getattr(f, k) for k in keys} for f in s.findings],
        "decisions": [{"action": d.action, "note": d.note, "rule_key": d.rule_key,
                       "actor": email_of(db, d.actor_id), "at": d.created_at.isoformat()} for d in s.decisions],
    }


def load(db: Session, sid: int, user: User) -> Submission:
    s = db.get(Submission, sid)
    if s is None or s.brand_id != user.brand_id or (user.role == Role.creator and s.creator_id != user.id):
        raise HTTPException(404, "Submission not found")
    return s


def owned(db: Session, sid: int, user: User) -> Submission:
    s = load(db, sid, user)
    if s.creator_id != user.id:
        raise HTTPException(403, "Only the creator can change this submission")
    return s


def open_finding(s: Submission, fid: int) -> Finding:
    f = next((x for x in s.findings if x.id == fid), None)
    if f is None or f.status != "open":
        raise HTTPException(400, "This finding is no longer open")
    return f


@router.get("")
def list_submissions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Submission).filter(Submission.brand_id == user.brand_id)
    if user.role == Role.creator:
        q = q.filter(Submission.creator_id == user.id)
    return [{"id": s.id, "title": s.title, "channel": s.channel, "status": s.status,
             "creator": email_of(db, s.creator_id), "creator_id": s.creator_id,
             "open": sum(f.status == "open" for f in s.findings), "created_at": s.created_at.isoformat()}
            for s in q.order_by(Submission.id.desc()).all()]


@router.get("/{sid}")
def get_submission(sid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return sub_out(db, load(db, sid, user))


@router.post("", status_code=201)
def create(body: SubmitIn, user: User = Depends(require_roles(*CREATORS)), db: Session = Depends(get_db)):
    if user.brand_id is None:
        raise HTTPException(400, "Your account is not linked to a brand")
    if not body.text.strip():
        raise HTTPException(422, "Add some content to check")
    s = Submission(brand_id=user.brand_id, creator_id=user.id, title=body.title.strip() or "Untitled",
                   channel=body.channel, text=body.text.strip())
    run(db, s)
    db.add(s)
    db.flush()
    record(db, user.brand_id, user.email, "submission.checked", f"'{s.title}': {len(s.findings)} findings")
    db.commit()
    return sub_out(db, s)


@router.post("/{sid}/recheck")
def recheck(sid: int, body: TextIn, user: User = Depends(require_roles(*CREATORS)), db: Session = Depends(get_db)):
    s = owned(db, sid, user)
    if s.status not in ("checked", "revision"):
        raise HTTPException(400, "Only drafts can be re-checked")
    if not body.text.strip():
        raise HTTPException(422, "The draft cannot be empty")
    s.text, s.status = body.text.strip(), "checked"
    run(db, s)
    record(db, s.brand_id, user.email, "submission.rechecked", f"'{s.title}': {len(s.findings)} findings")
    db.commit()
    return sub_out(db, s)


@router.post("/{sid}/findings/{fid}/accept")
def accept(sid: int, fid: int, user: User = Depends(require_roles(*CREATORS)), db: Session = Depends(get_db)):
    s = owned(db, sid, user)
    f = open_finding(s, fid)
    if f.replacement and f.excerpt in s.text:
        s.text = s.text.replace(f.excerpt, f.replacement, 1)
    f.status = "accepted"
    record(db, s.brand_id, user.email, "finding.accepted", f"{f.rule_key}: {f.excerpt[:80]}")
    db.commit()
    return sub_out(db, s)


@router.post("/{sid}/findings/{fid}/dispute")
def dispute(sid: int, fid: int, body: NoteIn, user: User = Depends(require_roles(*CREATORS)), db: Session = Depends(get_db)):
    s = owned(db, sid, user)
    f = open_finding(s, fid)
    if not body.note.strip():
        raise HTTPException(422, "Explain why the finding is wrong")
    f.status = "disputed"
    s.decisions.append(Decision(actor_id=user.id, action="dispute", note=body.note.strip(), rule_key=f.rule_key))
    record(db, s.brand_id, user.email, "finding.disputed", f"{f.rule_key}: {body.note.strip()[:80]}")
    db.commit()
    return sub_out(db, s)


@router.post("/{sid}/submit")
def submit(sid: int, user: User = Depends(require_roles(*CREATORS)), db: Session = Depends(get_db)):
    s = owned(db, sid, user)
    if s.status not in ("checked", "revision"):
        raise HTTPException(400, "This submission is already in review")
    s.status = "in_review"
    s.decisions.append(Decision(actor_id=user.id, action="submitted"))
    record(db, s.brand_id, user.email, "submission.sent_for_review", s.title)
    db.commit()
    return sub_out(db, s)


@router.post("/{sid}/decision")
def decide(sid: int, body: DecisionIn, user: User = Depends(require_roles(*REVIEWERS)), db: Session = Depends(get_db)):
    s = load(db, sid, user)
    if s.creator_id == user.id:
        raise HTTPException(403, "You cannot review your own content")
    if s.status != "in_review":
        raise HTTPException(400, "Nothing is waiting for review")
    if body.action == "approve":
        if any(f.status == "open" and f.verdict == "contradicted" for f in s.findings):
            raise HTTPException(400, "The creator must fix or dispute contradicted findings first")
        for f in s.findings:
            if f.status == "open" and f.verdict == "human_review":
                f.status = "reviewed"
        s.status = "approved"
    elif body.action == "revise":
        if not body.note.strip():
            raise HTTPException(422, "Add a note saying what to change")
        s.status = "revision"
    else:
        raise HTTPException(400, "Action must be approve or revise")
    s.decisions.append(Decision(actor_id=user.id, action=body.action, note=body.note.strip()))
    record(db, s.brand_id, user.email, f"submission.{body.action}", s.title)
    db.commit()
    return sub_out(db, s)
