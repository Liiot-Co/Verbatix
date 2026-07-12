import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.pipeline.llm.client import classify_batch
from app.core.config import settings


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def classify_studio(db: Session, studio_id: uuid.UUID) -> dict:
    """Classifies pending mention_groups of a studio against its codebook using the local LLM.

    Reads the exact-match dedup groups that import already built (build_mention_groups),
    then resolves whatever's still 'pending_review' — the same engine serves reasons studios
    (all groups, triggered automatically after import) and the brand fuzzy-match leftovers
    (whatever a future alias-matching pass doesn't resolve), per docs/ideas/verbatix-sharpen.md.
    """
    run_id = uuid.uuid4()
    db.execute(
        text("""
            insert into processing_runs (id, studio_id, run_type, algorithm, status, started_at)
            values (:id, :studio, 'initial', 'llm_structured_output', 'running', now())
        """),
        {"id": run_id, "studio": studio_id},
    )
    db.commit()

    coding_type = db.execute(
        text("select coding_type from studio where id = :studio"),
        {"studio": studio_id},
    ).scalar()

    codes = db.execute(
        text("""
            select c.id, c.code_number, c.label, n.name as net_name
            from codes c
            join codebooks b on b.id = c.codebook_id
            left join net_codes nc on nc.code_id = c.id
            left join nets n on n.id = nc.net_id
            where b.studio_id = :studio and c.is_active
            order by b.version desc
        """),
        {"studio": studio_id},
    ).mappings().all()
    codes_by_number = {c["code_number"]: c["id"] for c in codes}
    codebook_payload = [
        {"code_number": c["code_number"], "label": c["label"], "net": c["net_name"]} for c in codes
    ]

    groups = db.execute(
        text("""
            select id, sample_text from mention_groups
            where studio_id = :studio and status = 'pending_review'
        """),
        {"studio": studio_id},
    ).mappings().all()
    groups_by_id = {str(g["id"]): g for g in groups}

    auto_coded = 0
    anomalies = 0
    for batch in _chunks(groups, settings.classification_batch_size):
        payload = [{"id": str(g["id"]), "text": g["sample_text"]} for g in batch]
        results = classify_batch(codebook_payload, payload, coding_type)

        for result in results:
            group = groups_by_id.get(result["verbatim_id"])
            if group is None:
                continue
            group_id = group["id"]
            matched_code_ids = [codes_by_number[n] for n in result["code_numbers"] if n in codes_by_number]
            confidence = result.get("confidence")
            # No confidence in the response is treated as low confidence, not high — a case
            # the LLM won't rate shouldn't get auto-coded any more than one it rates poorly.
            below_threshold = confidence is None or confidence < settings.llm_confidence_threshold

            if not matched_code_ids or below_threshold:
                db.execute(
                    text("update mention_groups set status = 'anomaly', created_by_run_id = :run where id = :id"),
                    {"run": run_id, "id": group_id},
                )
                db.execute(
                    text("update verbatims set coding_status = 'needs_review' where mention_group_id = :id"),
                    {"id": group_id},
                )
                anomalies += 1
                continue

            db.execute(
                text("""
                    update mention_groups
                    set status = 'auto_coded', suggested_code_id = :code, created_by_run_id = :run
                    where id = :id
                """),
                {"code": matched_code_ids[0], "run": run_id, "id": group_id},
            )
            for idx, code_id in enumerate(matched_code_ids, start=1):
                # ponytail: 'engine_fuzzy' is the closest allowed source value for LLM-assigned
                # codes under the current schema check constraint (no dedicated 'llm' value yet).
                db.execute(
                    text("""
                        insert into verbatim_codes (id, verbatim_id, code_id, output_index, source, processing_run_id)
                        select gen_random_uuid(), v.id, :code, :idx, 'engine_fuzzy', :run
                        from verbatims v where v.mention_group_id = :group_id
                        on conflict (verbatim_id, code_id) do nothing
                    """),
                    {"code": code_id, "idx": idx, "run": run_id, "group_id": group_id},
                )
            db.execute(
                text("update verbatims set coding_status = 'auto_coded' where mention_group_id = :id"),
                {"id": group_id},
            )
            auto_coded += 1
        db.commit()

    db.execute(
        text("""
            update processing_runs
            set status = 'completed', finished_at = now(),
                total_verbatims = :total, auto_coded_count = :auto, anomalies_count = :anom
            where id = :id
        """),
        {"total": len(groups), "auto": auto_coded, "anom": anomalies, "id": run_id},
    )
    db.commit()

    return {"run_id": str(run_id), "groups_classified": auto_coded, "anomalies": anomalies, "total": len(groups)}
