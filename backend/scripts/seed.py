"""Creates a demo brand with users, approved sources, sample drafts and review history.
Run once. Usage (from backend/):  python -m scripts.seed
"""
from app.auth import hash_password
from app.db import Base, SessionLocal, engine
from app.gaps import detect
from app.models import Brand, Decision, Role, Source, SourcePassage, Submission, User, record
from app.routers.sources import chunk_into_passages
from app.routers.submissions import run

DEMO_PASSWORD = "demo-pass-123"  # Demo only. Never use in a real deployment.
USERS = [
    ("manager@demo.brandproof", Role.brand_manager),
    ("creator@demo.brandproof", Role.creator),
    ("reviewer@demo.brandproof", Role.reviewer),
    ("compliance@demo.brandproof", Role.compliance),
]
SOURCES = [
    ("Brand Book", "tone",
     "Tone: friendly, plain and confident. Speak to the reader as you.\n\n"
     "Never shout: avoid all-capitals words, and use at most one exclamation mark per post.\n\n"
     "Avoid these terms in all content: cheap, miracle, hack."),
    ("Fact Sheet", "facts",
     "Customers: 7,500 as of Sep 2026.\n\nStores: 42 across India as of Sep 2026.\n\nFounded: 2016."),
    ("Claims Library", "claims",
     "Superlatives such as best, fastest, cheapest or leading need an approved benchmark before publishing.\n\n"
     "Guarantee, cure and risk-free claims are high risk and always need human review.\n\n"
     "Approved benchmark: average delivery time is 2.1 days, measured across 1,200 orders in Q2 2026."),
    ("Visual Guide", "visual",
     "Approved palette: #0B2545, #13315C, #FFFFFF and #F4F7FB.\n\nThe logo sits only on navy or white backgrounds."),
]
DRAFTS = [
    ("Spring launch banner", "web", "Trusted by 10,000+ customers across India. The fastest app in its category."),
    ("Wallet promo", "social", "Our new Wallet app is the best way to pay. Guaranteed savings every month!!"),
    ("Weekend deals", "social", "Quick tips! Grab a cheap deal today. Shop with us across 42 stores in India."),
    ("Logo refresh post", "social", "Our new logo is live, sitting on #FFD166 with bold text: SHOP NOW."),
    ("Bakery feature", "web", "Our bakery makes the best sourdough in town, with the fastest delivery."),
    ("Customer thank-you", "email", "Join 7,500+ customers who trust us. Our stores are across India."),
    ("Tea launch", "web", "Our tea is a miracle cure, clinically proven and risk-free."),
]


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Brand).filter(Brand.name == "Demo Brand").first():
            print("Demo data already exists. Sign in with manager@demo.brandproof / demo-pass-123")
            return
        brand = Brand(name="Demo Brand")
        db.add(brand)
        db.flush()
        people = {}
        for email, role in USERS:
            u = User(email=email, password_hash=hash_password(DEMO_PASSWORD), role=role, brand_id=brand.id)
            db.add(u)
            people[role] = u
        db.flush()
        manager, creator, reviewer = people[Role.brand_manager], people[Role.creator], people[Role.reviewer]

        for title, cat, text in SOURCES:
            src = Source(brand_id=brand.id, title=title, category=cat, version=1,
                         filename=title.lower().replace(" ", "-") + ".txt", owner_id=manager.id)
            src.passages = [SourcePassage(position=i, text=t) for i, t in enumerate(chunk_into_passages(text))]
            db.add(src)
            record(db, brand.id, manager.email, "source.uploaded", f"{title} v1")
        db.flush()

        subs = []
        for title, channel, text in DRAFTS:
            s = Submission(brand_id=brand.id, creator_id=creator.id, title=title, channel=channel, text=text)
            run(db, s)
            db.add(s)
            subs.append(s)
            record(db, brand.id, creator.email, "submission.checked", f"'{title}': {len(s.findings)} findings")
        db.flush()

        # Creators dispute the superlative finding on three drafts, so the rule looks unclear.
        for s in (subs[0], subs[1], subs[4]):
            f = next(x for x in s.findings if x.rule_key == "claims:superlative")
            f.status = "disputed"
            s.decisions.append(Decision(actor_id=creator.id, action="dispute",
                                        note="Our delivery benchmark is current; this should pass.", rule_key=f.rule_key))
            record(db, brand.id, creator.email, "finding.disputed", f.rule_key)

        subs[2].status = "in_review"
        subs[2].decisions.append(Decision(actor_id=creator.id, action="submitted"))
        subs[5].status = "approved"
        subs[5].decisions.append(Decision(actor_id=reviewer.id, action="approve"))
        db.flush()

        created = detect(db, brand.id)
        record(db, brand.id, manager.email, "gaps.scanned", f"{created} new proposal(s)")
        db.commit()
        print(f"Seeded demo brand: {len(DRAFTS)} drafts, {len(SOURCES)} sources, {created} rule proposal(s).")
        print("Sign in with manager@ / creator@ / reviewer@ / compliance@demo.brandproof, password demo-pass-123")
    finally:
        db.close()


if __name__ == "__main__":
    main()
