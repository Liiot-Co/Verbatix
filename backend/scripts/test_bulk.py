import os
import sys
import uuid
import time
from pathlib import Path

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

def run_test_for_file(db, user_id, filename, coding_type, verbatims_sheet, codebook_sheet, source_studio_id=None):
    filepath = f"/data/{filename}"
    if not os.path.exists(filepath):
        print(f"Skipping {filename}: file not found")
        return None
        
    print(f"\n{'='*50}\nTesting {filename} - {coding_type}\n{'='*50}")
    
    project_id = uuid.uuid4()
    round_id = uuid.uuid4()
    studio_id = uuid.uuid4()

    db.execute(text("insert into projects (id, name, created_by) values (:id, 'Test Bulk', :u) on conflict do nothing"), {"id": project_id, "u": user_id})
    db.execute(text("insert into rounds (id, project_id, name, round_number, created_by) values (:id, :p, 'R_bulk', 1, :u) on conflict do nothing"), {"id": round_id, "p": project_id, "u": user_id})
    
    db.execute(
        text("""
            insert into studio (id, round_id, name, coding_type, origin_mode, source_studio_id)
            values (:id, :r, 'Studio Bulk', :ct, :om, :src)
        """),
        {"id": studio_id, "r": round_id, "ct": coding_type, "om": "homologated" if source_studio_id else "from_scratch", "src": source_studio_id}
    )
    
    cb_id = create_codebook(db, studio_id)
    if source_studio_id:
        from app.repositories import clone_codebook
        print(f"Homologating codebook from {source_studio_id}...")
        inherited = clone_codebook(db, source_studio_id, cb_id)
        print(f"Inherited codes: {inherited['codes']}")
    
    seed_system_codes(db, cb_id)
    
    with open(filepath, "rb") as f:
        content = f.read()
        
    try:
        rows = excel.parse_verbatims(content, verbatims_sheet)
    except Exception as e:
        print(f"Could not parse verbatims sheet {verbatims_sheet}: {e}")
        return None

    file_id = uuid.uuid4()
    db.execute(text("insert into imported_files (id, studio_id, file_type, original_filename, status, uploaded_by) values (:id, :s, 'combined_xlsx', :f, 'uploaded', :u)"), {"id": file_id, "s": studio_id, "f": filename, "u": user_id})
    
    print(f"Inserting {len(rows)} verbatims...")
    insert_verbatims(db, studio_id, file_id, rows, coding_type)
    
    if not source_studio_id and codebook_sheet:
        try:
            parsed_cb = excel.parse_codebook(content, codebook_sheet)
            insert_codebook_from_excel(db, cb_id, parsed_cb)
            print(f"Codebook imported: {len(parsed_cb['codes'])} codes.")
        except Exception as e:
            print(f"Codebook parsing error for sheet {codebook_sheet}: {e}")
    
    print("Building mention groups...")
    build_mention_groups(db, studio_id)
    
    db.commit()
    
    start = time.time()
    try:
        result = process_studio(db, studio_id)
        duration = time.time() - start
        print(f"Processing result (took {duration:.1f}s):")
        print(result)
        
        anomalies = db.execute(text("select normalized_text, frequency_count from mention_groups where studio_id = :s and status = 'anomaly' order by frequency_count desc limit 10"), {"s": studio_id}).fetchall()
        print(f"Top 10 Anomalies:")
        for a in anomalies:
            print(f"- {a[0]} ({a[1]})")
    except Exception as e:
        print("Processing failed:", e)
        
    return studio_id

def main():
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    engine = create_engine(url)
    Session = sessionmaker(bind=engine)
    db = Session()
    
    user_row = db.execute(text("select id from profiles limit 1")).fetchone()
    user_id = user_row[0] if user_row else uuid.uuid4()
    
    # Process R1 as source of truth
    r1_file = "LC 32406432 TRACK MULTICATEGORY GLORIA QUESO - RONDA 1 2026.xlsx"
    src_brands = run_test_for_file(db, user_id, r1_file, "brands", "Verbatims_Marcas", "LC Marcas")
    src_reasons = run_test_for_file(db, user_id, r1_file, "reasons", "Verbatims_Razones", "Razones")
    
    files = [
        "LC 32406432 TRACK MULTICATEGORY GLORIA QUESO - RONDA 2 2026.xlsx",
        "LC 32406432 TRACK MULTICATEGORY GLORIA QUESO - RONDA 3 2026.xlsx",
        "LC 32406432 TRACK MULTICATEGORY GLORIA QUESO - RONDA 4 2026.xlsx",
    ]
    
    for f in files:
        if src_brands:
            run_test_for_file(db, user_id, f, "brands", "Verbatims_Marcas", None, source_studio_id=src_brands)
        if src_reasons:
            run_test_for_file(db, user_id, f, "reasons", "Verbatims_Razones", None, source_studio_id=src_reasons)
        
    db.close()

if __name__ == "__main__":
    main()
