"""Bootstrap del codebook de razones cuando arranca vacío (from_scratch, sin
codebook importado ni homologado).

Sin esto, classify_round (pipeline/llm/classify.py) solo puede elegir entre
los 5 códigos de sistema — ninguna categoría real ("sabor", "precio"...)
existe todavía — y el prompt termina metiendo casi todo en 97 "Otras
menciones" porque, literalmente, nada tiene su propio código.

Marcas resuelve esto agrupando por frecuencia exacta/fuzzy (ver
pipeline/fuzzy/catalog.discover_catalog_from_frequency): funciona porque una
marca repetida se escribe casi igual cada vez ("gloria", "glorea"). Una razón
casi nunca se repite palabra por palabra ("es rico" vs "tiene buen sabor"), así
que el agrupamiento tiene que ser semántico (embeddings + similitud coseno) en
vez de por texto.

Este módulo solo POBLA el codebook con categorías candidatas — no decide qué
mention_group va en cuál. La asignación real la sigue haciendo classify_round,
con su propia pasada LLM por texto (más precisa que los bordes de un cluster
por embeddings), ahora contra un codebook que ya tiene contenido real.
"""
from __future__ import annotations

import uuid
import json

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.pipeline.llm.client import propose_reason_codes

from .embed import embed


def cluster_by_similarity(
    items: list[tuple], threshold: float
) -> list[dict]:
    """Agrupa de forma reproducible mediante enlace completo.

    Solo se fusionan dos clusters cuando *todos* sus pares superan el umbral.
    Esto evita tanto la dependencia del orden del greedy anterior como el efecto
    cadena de single-link. El representante es el medoide y se conservan ejemplos
    centrales y de frontera para que DeepSeek vea la extensión real del cluster.
    """
    members: list[dict] = []
    for item in items:
        text_, vector, freq = item[:3]
        vector_array = np.array(vector, dtype=float)
        norm = np.linalg.norm(vector_array)
        if norm > 0:
            vector_array = vector_array / norm
        members.append({
            "text": text_,
            "vector": vector_array,
            "frequency": int(freq),
            "member_id": item[3] if len(item) > 3 else None,
        })

    # La clave estable hace que una permutación de la entrada produzca el mismo
    # clustering, representantes y orden de salida.
    members.sort(key=lambda m: (str(m["text"]).casefold(), str(m["member_id"] or "")))
    clusters: list[list[dict]] = [[member] for member in members]

    def complete_link(left: list[dict], right: list[dict]) -> float:
        return min(
            float(np.dot(a["vector"], b["vector"]))
            for a in left for b in right
        )

    while True:
        candidates: list[tuple[float, str, int, int]] = []
        for left_idx in range(len(clusters)):
            for right_idx in range(left_idx + 1, len(clusters)):
                similarity = complete_link(clusters[left_idx], clusters[right_idx])
                if similarity >= threshold:
                    stable_key = "|".join(
                        sorted(str(m["text"]).casefold() for m in clusters[left_idx] + clusters[right_idx])
                    )
                    candidates.append((similarity, stable_key, left_idx, right_idx))
        if not candidates:
            break
        _, _, left_idx, right_idx = sorted(
            candidates, key=lambda row: (-row[0], row[1])
        )[0]
        clusters[left_idx] = clusters[left_idx] + clusters[right_idx]
        del clusters[right_idx]

    output: list[dict] = []
    for cluster in clusters:
        def centrality(member: dict) -> float:
            return sum(
                float(np.dot(member["vector"], other["vector"])) * other["frequency"]
                for other in cluster
            ) / max(sum(other["frequency"] for other in cluster), 1)

        ranked = sorted(
            cluster,
            key=lambda member: (
                -centrality(member), -member["frequency"], str(member["text"]).casefold()
            ),
        )
        boundary = sorted(
            cluster,
            key=lambda member: (
                centrality(member), -member["frequency"], str(member["text"]).casefold()
            ),
        )
        representative = ranked[0]
        central_examples = [member["text"] for member in ranked[:3]]
        boundary_examples = [
            member["text"] for member in boundary[:2]
            if member["text"] not in central_examples
        ]
        output.append({
            "representative": representative["text"],
            "total_frequency": sum(member["frequency"] for member in cluster),
            "member_ids": [
                member["member_id"] for member in cluster if member["member_id"] is not None
            ],
            "examples": central_examples + boundary_examples,
            "central_examples": central_examples,
            "boundary_examples": boundary_examples,
        })

    return sorted(
        output,
        key=lambda cluster: (-cluster["total_frequency"], str(cluster["representative"]).casefold()),
    )


def discover_reason_catalog(db: Session, subproject_id: uuid.UUID, min_mentions: int) -> int:
    """Idempotente: si el codebook ya tiene algún code propio (no-system) no
    hace nada, igual que discover_catalog_from_frequency para marcas — una vez
    poblado, no se vuelve a tomar. Devuelve cuántos codes creó."""
    codebook_id = db.execute(
        text("select codebook_id from subprojects where id = :sp"),
        {"sp": subproject_id},
    ).scalar()
    if codebook_id is None:
        return 0

    has_own_codes = db.execute(
        text("select exists(select 1 from codes where codebook_id = :cb and not is_system)"),
        {"cb": codebook_id},
    ).scalar()
    if has_own_codes:
        return 0

    candidates = db.execute(
        text("""
            select id, normalized_text, sample_text, frequency_count
            from mention_groups
            where subproject_id = :sp and status = 'pending_review' and normalized_text <> ''
            order by frequency_count desc, normalized_text
        """),
        {"sp": subproject_id},
    ).mappings().all()
    if not candidates:
        return 0

    items = [
        (
            c["sample_text"] or c["normalized_text"],
            embed(c["normalized_text"]),
            c["frequency_count"],
            c["id"],
        )
        for c in candidates
    ]
    clusters = cluster_by_similarity(items, settings.reason_cluster_similarity_threshold)
    big_clusters = [c for c in clusters if c["total_frequency"] >= min_mentions]
    if not big_clusters:
        return 0

    cluster_summaries = [
        (
            f"Representante: {cluster['representative']}. "
            f"Ejemplos centrales: {'; '.join(cluster['central_examples'])}. "
            f"Ejemplos de frontera: {'; '.join(cluster['boundary_examples']) or 'ninguno'}."
        )
        for cluster in big_clusters
    ]
    context_row = db.execute(
        text("""
            select p.name as study, p.external_code,
                   cat.name as product_category, sp.single_code_per_response
              from subprojects sp
              join rounds r on r.id = sp.round_id
              join studies p on p.id = r.study_id
              left join categories cat on cat.id = r.category_id
             where sp.id = :sp
        """),
        {"sp": subproject_id},
    ).mappings().first()
    proposals = propose_reason_codes(cluster_summaries, dict(context_row) if context_row else {})

    next_number = db.execute(
        text("""
            select coalesce(max(code_number), 0) + 1 from codes
            where codebook_id = :cb and coalesce(is_system, false) = false
        """),
        {"cb": codebook_id},
    ).scalar()

    for proposal, cluster in zip(proposals, big_clusters, strict=True):
        label = proposal["label"]
        # 'engine_auto' (no 'engine_semantic'): mismo origin que
        # discover_catalog_from_frequency usa para marcas — el check constraint
        # de `codes` (001_schema_v8.sql) no tiene un valor separado para
        # "generado por clustering semántico" y no hace falta uno nuevo, el
        # significado ("lo creó el motor, no un analista") es el mismo.
        db.execute(
            text("""
                insert into codes (
                  id, codebook_id, code_number, label, definition,
                  inclusion_criteria, exclusion_criteria, examples,
                  origin, approval_status
                )
                values (
                  :id, :cb, :n, :label, :definition,
                  cast(:inclusions as jsonb), cast(:exclusions as jsonb), cast(:examples as jsonb),
                  'engine_auto', 'pending'
                )
            """),
            {
                "id": (code_id := uuid.uuid4()),
                "cb": codebook_id,
                "n": next_number,
                "label": label,
                "definition": proposal["definition"],
                "inclusions": json.dumps(proposal["inclusion_criteria"]),
                "exclusions": json.dumps(proposal["exclusion_criteria"]),
                "examples": json.dumps(proposal["examples"]),
            },
        )
        net_name = proposal["net"].strip()
        net_id = db.execute(
            text("select id from nets where codebook_id = :cb and lower(name) = lower(:name) limit 1"),
            {"cb": codebook_id, "name": net_name},
        ).scalar()
        if net_id is None:
            net_id = uuid.uuid4()
            db.execute(
                text("""
                    insert into nets (id, codebook_id, name, origin, display_order)
                    values (:id, :cb, :name, 'engine_auto', :ord)
                """),
                {"id": net_id, "cb": codebook_id, "name": net_name, "ord": next_number},
            )
        db.execute(
            text("""
                insert into net_codes (id, net_id, code_id, display_order)
                values (:id, :net, :code, :ord)
                on conflict (net_id, code_id) do nothing
            """),
            {"id": uuid.uuid4(), "net": net_id, "code": code_id, "ord": next_number},
        )
        if cluster["member_ids"]:
            db.execute(
                text("""
                    update mention_groups
                       set status = 'suggested', suggested_code_id = :code
                     where id = any(:ids)
                """),
                {"code": code_id, "ids": cluster["member_ids"]},
            )
        next_number += 1

    return len(proposals)
