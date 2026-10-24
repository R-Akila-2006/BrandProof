import datetime as dt
import enum
from typing import Optional

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Role(str, enum.Enum):
    creator = "creator"
    reviewer = "reviewer"
    brand_manager = "brand_manager"
    compliance = "compliance"


class Brand(Base):
    __tablename__ = "brands"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sources: Mapped[list["Source"]] = relationship(back_populates="brand")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role, name="role"))
    brand_id: Mapped[Optional[int]] = mapped_column(ForeignKey("brands.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Source(Base):
    """Approved brand source. Each upload of the same title is a new version."""
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(100), default="general")
    version: Mapped[int] = mapped_column(Integer, default=1)
    filename: Mapped[str] = mapped_column(String(255))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    brand: Mapped[Brand] = relationship(back_populates="sources")
    passages: Mapped[list["SourcePassage"]] = relationship(
        back_populates="source", cascade="all, delete-orphan", order_by="SourcePassage.position"
    )


class SourcePassage(Base):
    __tablename__ = "source_passages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[Source] = relationship(back_populates="passages")


class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    channel: Mapped[str] = mapped_column(String(20), default="web")
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="checked")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan", order_by="Finding.id"
    )
    decisions: Mapped[list["Decision"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan", order_by="Decision.id"
    )


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(30))
    verdict: Mapped[str] = mapped_column(String(30))
    excerpt: Mapped[str] = mapped_column(Text)
    replacement: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    suggestion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    rule_key: Mapped[str] = mapped_column(String(80))
    source_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    passage_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")
    submission: Mapped[Submission] = relationship(back_populates="findings")


class Decision(Base):
    """Human and workflow events on a submission: disputes, submissions, approvals, revisions."""
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text, default="")
    rule_key: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submission: Mapped[Submission] = relationship(back_populates="decisions")


class GapProposal(Base):
    __tablename__ = "gap_proposals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    gap_type: Mapped[str] = mapped_column(String(20))
    rule_key: Mapped[str] = mapped_column(String(80))
    summary: Mapped[str] = mapped_column(Text)
    rewrite: Mapped[str] = mapped_column(Text)
    evidence_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Append-only record of who did what and when."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    actor_email: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def record(db, brand_id: int, actor_email: str, action: str, detail: str) -> None:
    db.add(AuditLog(brand_id=brand_id, actor_email=actor_email, action=action, detail=detail[:1000]))
