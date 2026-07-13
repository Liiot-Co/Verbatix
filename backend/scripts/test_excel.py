import os
import sys
import uuid
from pathlib import Path
from pprint import pprint

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

for line in (BACKEND / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.pipeline.ingest import excel
from app.repositories import (
    build_mention_groups,
    create_codebook,
    insert_codebook_from_excel,
    insert_verbatims,
    seed_system_codes,
)
from app.pipeline.process import process_studio

def main():
    excel_path = "/data/LC 32406432 TRACK MULTICATEGORY GLORIA QUESO - RONDA 1 2026.xlsx"
    
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    engine = create_engine(url)
    Session = sessionmaker(bind=engine)
    db = Session()
    
    project_id = uuid.uuid4()
    round_id = uuid.uuid4()
    studio_id = uuid.uuid4()
    user_id = uuid.uuid4() # Mock user

    # Grab an existing user or mock if none
    user_row = db.execute(text("select id from profiles limit 1")).fetchone()
    if user_row:
        user_id = user_row[0]
    else:
        # Fallback just in case, might still fail if strict FK is on
        user_id = uuid.uuid4()
        
    db.execute(text("insert into projects (id, name, created_by) values (:id, 'Test Proj', :user) on conflict do nothing"), {"id": project_id, "user": user_id})
    db.execute(text("insert into rounds (id, project_id, name, round_number, created_by) values (:id, :p, 'R1', 1, :user) on conflict do nothing"), {"id": round_id, "p": project_id, "user": user_id})
    
    # We will test "marcas" (brands) first
    coding_type = "brands"
    
    db.execute(
        text("""
            insert into studio (id, round_id, name, coding_type, origin_mode)
            values (:id, :r, 'Test Studio Marcas', :ct, 'from_scratch')
        """),
        {"id": studio_id, "r": round_id, "ct": coding_type}
    )
    
    cb_id = create_codebook(db, studio_id)
    seed_system_codes(db, cb_id)
    
    with open(excel_path, "rb") as f:
        content = f.read()
    
    # Parse excel
    print("Parsing excel...")
    rows = excel.parse_verbatims(content, "Verbatims_Marcas")
    
    file_id = uuid.uuid4()
    db.execute(text("insert into imported_files (id, studio_id, file_type, original_filename, status, uploaded_by) values (:id, :s, 'combined_xlsx', 'test.xlsx', 'uploaded', :user)"), {"id": file_id, "s": studio_id, "user": user_id})
    
    print(f"Inserting {len(rows)} verbatims...")
    insert_verbatims(db, studio_id, file_id, rows, coding_type)
    
    try:
        parsed_cb = excel.parse_codebook(content, "LC Marcas")
        insert_codebook_from_excel(db, cb_id, parsed_cb)
        print(f"Codebook imported: {len(parsed_cb['codes'])} codes.")
    except Exception as e:
        print("Codebook parsing error or missing sheet:", e)
    
    print("Building mention groups...")
    build_mention_groups(db, studio_id)
    
    db.commit()
    
    print("Starting process_studio...")
    result = process_studio(db, studio_id)
    print("Processing result:")
    pprint(result)
    
    # Show anomaly counts
    anomalies = db.execute(text("select normalized_text, frequency_count from mention_groups where studio_id = :s and status = 'anomaly' order by frequency_count desc limit 10"), {"s": studio_id}).fetchall()
    print("\nTop 10 Anomalies (Unclassified):")
    for a in anomalies:
        print(f"- {a[0]} ({a[1]})")

if __name__ == "__main__":
    main()
