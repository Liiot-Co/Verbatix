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
from app.pipeline.normalize import normalize

from .embed import embed_many


def cluster_by_similarity(
    items: list[tuple], threshold: float
) -> list[dict]:
    """Agrupa de forma reproducible mediante enlace completo.

    Solo se fusionan dos clusters cuando *todos* sus pares superan el umbral.
    Esto evita tanto la dependencia del orden del greedy anterior como el efecto
    cadena de single-link. El representante es el medoide y se conservan ejemplos
    centrales y de frontera para que DeepSeek vea la extensión real del cluster.

    Implementación: la similitud coseno punto-a-punto se calcula UNA vez y las
    fusiones mantienen el complete-link con la recurrencia de Lance-Williams
    —sim(A∪B, C) = min(sim(A,C), sim(B,C))—, que es exacta (min es asociativo).
    Así el mismo resultado que la versión anterior sin recomputar todos los pares
    por iteración: pasa de O(n³·dim) a O(n²), crítico porque una ronda de Razones
    trae cientos de grupos y el clustering corría por minutos bloqueando el GIL (y
    con él el hilo paralelo de Marcas).
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
    n = len(members)
    if n == 0:
        return []

    texts_cf = [str(m["text"]).casefold() for m in members]

    # Similitud coseno de TODOS los pares, una sola vez. Se calcula con el MISMO
    # np.dot por par que usaba la versión anterior (no con matrix @ matrix.Tᵀ):
    # BLAS gemm difiere de np.dot en el último ULP y esos bits, en empates o justo
    # en el umbral, cambiarían qué fusiona el greedy. Con np.dot el resultado es
    # bit-idéntico al original. El costo O(n²) es puntual; lo caro era el bucle de
    # fusiones (antes recomputaba todos los pares por iteración), ya vectorizado.
    matrix = np.vstack([m["vector"] for m in members])
    point_sim = np.empty((n, n), dtype=float)
    for i in range(n):
        row = point_sim[i]
        vi = matrix[i]
        for j in range(i, n):
            value = float(np.dot(vi, matrix[j]))
            row[j] = value
            point_sim[j, i] = value

    # sim[i, j] = complete-link entre los clusters i y j (min de sus pares).
    neg = -np.inf
    sim = point_sim.astype(float, copy=True)
    np.fill_diagonal(sim, neg)
    active = [True] * n
    cluster_members: list[list[int]] = [[i] for i in range(n)]

    while True:
        best_sim = sim.max()
        if best_sim < threshold:
            break
        # Entre los pares con la máxima similitud, se desempata por la MISMA clave
        # estable que la versión O(n³): la unión ordenada de textos. Como el máximo
        # ya es único casi siempre (embeddings reales), este barrido es corto.
        rows, cols = np.where(sim == best_sim)
        best_key = None
        best_i = best_j = -1
        for i, j in zip(rows.tolist(), cols.tolist()):
            if i >= j:
                continue
            key = "|".join(
                sorted(texts_cf[m] for m in cluster_members[i] + cluster_members[j])
            )
            if best_key is None or key < best_key:
                best_key, best_i, best_j = key, i, j

        # Fusiona j en i con la actualización de complete-link (mínimo por columna).
        cluster_members[best_i] = cluster_members[best_i] + cluster_members[best_j]
        merged = np.minimum(sim[best_i, :], sim[best_j, :])
        sim[best_i, :] = merged
        sim[:, best_i] = merged
        sim[best_i, best_i] = neg
        active[best_j] = False
        sim[best_j, :] = neg
        sim[:, best_j] = neg

    output: list[dict] = []
    for ci in range(n):
        if not active[ci]:
            continue
        idxs = cluster_members[ci]
        total_frequency = sum(members[k]["frequency"] for k in idxs)

        def centrality(k: int, _idxs=idxs, _total=total_frequency) -> float:
            return sum(
                float(point_sim[k, o]) * members[o]["frequency"] for o in _idxs
            ) / max(_total, 1)

        ranked = sorted(
            idxs,
            key=lambda k: (-centrality(k), -members[k]["frequency"], texts_cf[k]),
        )
        boundary = sorted(
            idxs,
            key=lambda k: (centrality(k), -members[k]["frequency"], texts_cf[k]),
        )
        central_examples = [members[k]["text"] for k in ranked[:3]]
        boundary_examples = [
            members[k]["text"] for k in boundary[:2]
            if members[k]["text"] not in central_examples
        ]
        output.append({
            "representative": members[ranked[0]]["text"],
            "total_frequency": total_frequency,
            "member_ids": [
                members[k]["member_id"] for k in idxs if members[k]["member_id"] is not None
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

    vectors = embed_many([c["normalized_text"] for c in candidates])
    items = [
        (
            c["sample_text"] or c["normalized_text"],
            vector,
            c["frequency_count"],
            c["id"],
        )
        for c, vector in zip(candidates, vectors)
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
              join studios p on p.id = r.project_id
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

    # DeepSeek puede etiquetar dos clusters de embeddings distintos con la MISMA
    # categoría (p.ej. "Nutrición" saliendo de "es nutritivo" y de "alimenta
    # bien"). Sin deduplicar, cada uno creaba su propio código y el codebook
    # terminaba con "Nutrición" repetido N veces. Se conserva el PRIMER código por
    # label normalizado (marcas hace lo mismo en _canonicalize_brand_draft vía
    # winner_by_label) y las menciones de los clusters posteriores con ese label
    # apuntan a ese único código.
    winner_by_label: dict[str, uuid.UUID] = {}
    for proposal, cluster in zip(proposals, big_clusters, strict=True):
        label = proposal["label"]
        label_key = normalize(label)
        existing_code = winner_by_label.get(label_key)
        if existing_code is not None:
            if cluster["member_ids"]:
                db.execute(
                    text("""
                        update mention_groups
                           set status = 'suggested', suggested_code_id = :code
                         where id = any(:ids)
                    """),
                    {"code": existing_code, "ids": cluster["member_ids"]},
                )
            continue

        code_id = uuid.uuid4()
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
                "id": code_id,
                "cb": codebook_id,
                "n": next_number,
                "label": label,
                "definition": proposal["definition"],
                "inclusions": json.dumps(proposal["inclusion_criteria"]),
                "exclusions": json.dumps(proposal["exclusion_criteria"]),
                "examples": json.dumps(proposal["examples"]),
            },
        )
        winner_by_label[label_key] = code_id
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

    return len(winner_by_label)
