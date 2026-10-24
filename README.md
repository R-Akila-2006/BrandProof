# BrandProof

**AI brand governance for content that is checked before it is published.**
Evidence-backed brand compliance. Human-controlled approval.

BrandProof checks drafts (text, pasted or uploaded as PDF/DOCX) against your organisation's own approved
brand book, fact sheet, claims library and visual guide. Every finding cites the exact approved passage
behind it. Claims without evidence are marked **unverified**, never automatically false. Humans approve
content and guideline changes.

## What works

- **Evidence-linked checker**: tone, terminology, factual figures, promotional claims, visual colours.
  Four verdicts: supported, contradicted, unverified, human review.
- **Evidence contract**: a finding that claims support must cite a real approved passage, or it is downgraded.
- **Creator workflow**: check a draft, accept suggested rewrites (meaning kept), dispute findings with a reason,
  edit and re-check, send for review.
- **Review queue**: reviewers approve or request revisions. Creators cannot approve their own work. Approval
  is blocked while contradicted findings are unresolved.
- **Guideline Gap Detector**: repeated disputes or unverified claims produce rule proposals. Brand managers
  approve or reject them. Approved rules become a new, versioned source the checker uses.
- **Approved sources**: upload brand books, fact sheets and claim evidence (txt, md, pdf, docx). A new upload
  of the same title becomes the next version.
- **Audit log and analytics**: every action recorded with who and when; evidence coverage, approval rate, verdict counts.

## Run it

Requires Python 3.11+ and Docker (for PostgreSQL).

    docker compose up -d
    cd backend
    python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    cp .env.example .env
    python -m scripts.seed
    uvicorn app.main:app --reload

Open http://localhost:8000

Demo accounts (password `demo-pass-123`): `manager@`, `creator@`, `reviewer@`, `compliance@demo.brandproof`.

Quick demo: sign in as creator, open a flagged draft, accept a fix, send for review. Sign in as reviewer,
approve or request revision. Sign in as manager, open Gap detector, scan, and approve the proposed rule.

## Layout

    docker-compose.yml          local PostgreSQL
    backend/app/checker.py      evidence-first checker (pure function, no database)
    backend/app/gaps.py         Guideline Gap Detector and rule versioning
    backend/app/routers/        auth, sources, submissions (workflow), governance (gaps, analytics, audit)
    backend/app/static/         single-page professional UI served by the API
    backend/scripts/seed.py     demo brand, users, sources, sample drafts and review history

## Configuration

`GAP_MIN_RECORDS` (default 3) sets how many disputes or unverified records are needed before the
Gap Detector proposes a rule. The detector reports nothing rather than guessing with too little data.

## Known limits (Round 1)

- The checker is rule-based and retrieval-based. It is deterministic and auditable, but it does not yet
  use a language model for nuanced tone or meaning checks. The checker module is the place to add a Claude API call.
- Image checks (OCR, logo and contrast analysis, alt text) are not implemented. Images are not accepted yet.
- Single-process demo: tables are created on startup. Use Alembic migrations before a pilot.
- Not yet included: CMS or Slack integrations, SSO, email notifications, personal-data masking.
