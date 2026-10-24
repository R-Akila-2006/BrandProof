import io
from pathlib import PurePath

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.config import settings
from app.db import get_db
from app.models import Role, Source, SourcePassage, User

router = APIRouter(prefix="/sources", tags=["sources"])

ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}
TARGET_PASSAGE_CHARS = 600


class PassageOut(BaseModel):
    id: int
    position: int
    text: str


class SourceOut(BaseModel):
    id: int
    title: str
    category: str
    version: int
    filename: str
    passage_count: int


def extract_text(filename: str, data: bytes) -> str:
    ext = PurePath(filename).suffix.lower()
    if ext in {".txt", ".md"}:
        return data.decode("utf-8", errors="replace")
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    if ext == ".docx":
        from docx import Document

        document = Document(io.BytesIO(data))
        return "\n\n".join(p.text for p in document.paragraphs)
    raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"Unsupported file type: {ext}")


def chunk_into_passages(text: str) -> list[str]:
    """Split on blank lines, then merge small paragraphs up to a target size.
    Each passage is a citable unit, so it should be a self-contained statement."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    passages: list[str] = []
    buffer = ""
    for para in paragraphs:
        if buffer and len(buffer) + len(para) + 1 > TARGET_PASSAGE_CHARS:
            passages.append(buffer)
            buffer = para
        else:
            buffer = f"{buffer}\n{para}".strip()
    if buffer:
        passages.append(buffer)
    return passages


@router.post("", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
async def upload_source(
    title: str = Form(...),
    category: str = Form("general"),
    file: UploadFile = File(...),
    user: User = Depends(require_roles(Role.brand_manager)),
    db: Session = Depends(get_db),
) -> SourceOut:
    if user.brand_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your account is not linked to a brand")

    filename = file.filename or "upload"
    if PurePath(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Use txt, md, pdf or docx")

    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large")

    try:
        text = extract_text(filename, data)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Could not read this file")

    passages = chunk_into_passages(text)
    if not passages:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No readable text found")

    # New upload of the same title in the same brand becomes the next version.
    previous_version = (
        db.query(Source)
        .filter(Source.brand_id == user.brand_id, Source.title == title)
        .order_by(Source.version.desc())
        .first()
    )
    version = previous_version.version + 1 if previous_version else 1

    source = Source(
        brand_id=user.brand_id,
        title=title,
        category=category,
        version=version,
        filename=filename,
        owner_id=user.id,
    )
    source.passages = [
        SourcePassage(position=i, text=chunk) for i, chunk in enumerate(passages)
    ]
    db.add(source)
    db.commit()
    db.refresh(source)

    return SourceOut(
        id=source.id,
        title=source.title,
        category=source.category,
        version=source.version,
        filename=source.filename,
        passage_count=len(passages),
    )


@router.get("", response_model=list[SourceOut])
def list_sources(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SourceOut]:
    if user.brand_id is None:
        return []
    sources = (
        db.query(Source)
        .filter(Source.brand_id == user.brand_id)
        .order_by(Source.uploaded_at.desc())
        .all()
    )
    return [
        SourceOut(
            id=s.id,
            title=s.title,
            category=s.category,
            version=s.version,
            filename=s.filename,
            passage_count=len(s.passages),
        )
        for s in sources
    ]


@router.get("/{source_id}/passages", response_model=list[PassageOut])
def get_passages(
    source_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PassageOut]:
    source = db.get(Source, source_id)
    if source is None or source.brand_id != user.brand_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    return [PassageOut(id=p.id, position=p.position, text=p.text) for p in source.passages]
