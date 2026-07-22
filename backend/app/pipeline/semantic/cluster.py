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
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.pipeline.llm.client import propose_reason_codes
from app.pipeline.normalize import normalize

from .embed import embed_many


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _propose_reason_codes_parallel(
    cluster_summaries: list[str], context: dict, existing_nets: list[str] | None = None,
) -> list[dict]:
    """Trocea `cluster_summaries` y llama a DeepSeek en paralelo, igual que
    classify_round ya hace para clasificar (ver pipeline/llm/classify.py).

    Sin esto, un estudio con decenas de clusters (84 medidos en producción)
    mandaba TODOS en un solo request: el modelo tenía que generar
    net+label+definición+inclusion/exclusion+ejemplos completos para cada uno
    en una sola respuesta — la llamada más lenta de todo el pipeline de
    Razones, más lenta que cualquier batch de classify_round (que solo pide
    una decisión corta por item). Trocear + paralelizar no cambia qué se le
    pide al modelo por cluster, solo cuántos le pide de una sentada.

    `existing_nets` (nets ya persistidos en el codebook ANTES de esta corrida)
    se manda IDÉNTICO a todos los lotes para que reutilicen el mismo
    vocabulario en vez de inventar sinónimos cada uno por su cuenta — ver el
    docstring de `_build_reason_codebook_prompt`. No cierra el caso de dos
    lotes que en la MISMA corrida inventan un net nuevo cada uno para la misma
    idea (ninguno ve lo que el otro acaba de proponer, corren en paralelo):
    ese remanente lo resuelve un humano en Resolución, igual que cualquier
    propuesta del motor.
    """
    batches = list(_chunks(cluster_summaries, settings.reason_discovery_batch_size))
    if len(batches) <= 1:
        return propose_reason_codes(cluster_summaries, context, existing_nets)

    results_by_batch: dict[int, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=settings.llm_parallel_requests) as pool:
        futures = {
            pool.submit(propose_reason_codes, batch, context, existing_nets): index
            for index, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            results_by_batch[futures[future]] = future.result()

    ordered: list[dict] = []
    for index in range(len(batches)):
        ordered.extend(results_by_batch[index])
    return ordered


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


def _existing_net_names(db: Session, codebook_id) -> list[str]:
    """Nets ya persistidos en el codebook, para dárselos al LLM como vocabulario
    a reutilizar (ver `_build_reason_codebook_prompt`) en vez de que invente un
    sinónimo por cada corrida ("Aroma" / "Sabor y Aroma", "Tamaño" /
    "Tamaño/Cantidad" — fragmentación observada en producción)."""
    return db.execute(
        text("select name from nets where codebook_id = :cb order by display_order, name"),
        {"cb": codebook_id},
    ).scalars().all()


def _find_code_by_label(db: Session, codebook_id, label_key: str) -> str | None:
    """Mismo check que `fuzzy/catalog._find_code_by_label` (marcas), para Razones:
    evita minar un código duplicado cuando ya existe uno con ese label — p.ej.
    'pending' de una corrida anterior e invisible para el codebook que ve
    classify_round (que solo lee `approval_status = 'approved'`)."""
    if not label_key:
        return None
    rows = db.execute(
        text("""
            select id, label from codes
            where codebook_id = :cb and is_active
              and coalesce(is_system, false) = false
        """),
        {"cb": codebook_id},
    ).mappings().all()
    for row in rows:
        if normalize(row["label"]) == label_key:
            return str(row["id"])
    return None


def discover_new_reasons(db: Session, subproject_id: uuid.UUID, min_mentions: int) -> int:
    """Categorías de Razón NUEVAS por similitud semántica, en rondas que HEREDAN
    el libro (no scratch).

    `discover_reason_catalog` solo corre con libro vacío (scratch): una vez que
    el codebook tiene contenido propio, se vuelve no-op (ver su docstring). Eso
    dejaba a las rondas heredadas SIN forma de descubrir una categoría real que
    nunca estuvo en el libro importado — classify_round solo puede elegir entre
    los codes ya aprobados de ESE codebook, así que una idea nueva ("empaque
    práctico" en un estudio que nunca la codificó) caía entera al residual 97
    "Otras menciones" en vez de proponerse como categoría. Mismo problema que
    resolvió `discover_new_brands` para Marcas — esta función es su paralelo.

    Corre sobre lo que quedó `pending_review` ANTES del caché semántico / LLM
    (mismo lugar del pipeline que discover_new_brands respecto al fuzzy de
    Marcas — ver `_process_subproject`), agrupa por embeddings + DeepSeek
    (igual que el bootstrap) y, por cada cluster cuya frecuencia sumada alcanza
    el mínimo, reusa un código existente con el mismo label si lo hay
    (`_find_code_by_label`) o propone uno nuevo. Los clusters chicos siguen
    `pending_review` hacia caché/LLM sin tocarse. No hace commit: el caller
    cierra la transacción del subproyecto.
    """
    row = db.execute(
        text("""
            select sp.codebook_id, sp.coding_type, cb.origin as codebook_origin
              from subprojects sp
              join codebooks cb on cb.id = sp.codebook_id
             where sp.id = :sp
        """),
        {"sp": subproject_id},
    ).mappings().first()
    if not row or row["coding_type"] != "reasons":
        return 0
    # Las rondas scratch ya descubren su catálogo en discover_reason_catalog.
    if row["codebook_origin"] == "scratch":
        return 0
    codebook_id = row["codebook_id"]
    if codebook_id is None:
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
        (c["sample_text"] or c["normalized_text"], vector, c["frequency_count"], c["id"])
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
              join studies p on p.id = r.study_id
              left join categories cat on cat.id = r.category_id
             where sp.id = :sp
        """),
        {"sp": subproject_id},
    ).mappings().first()
    proposals = _propose_reason_codes_parallel(
        cluster_summaries, dict(context_row) if context_row else {},
        existing_nets=_existing_net_names(db, codebook_id),
    )

    next_number = db.execute(
        text("""
            select coalesce(max(code_number), 0) + 1 from codes
            where codebook_id = :cb and coalesce(is_system, false) = false
        """),
        {"cb": codebook_id},
    ).scalar() or 1

    # Misma política que discover_new_brands: paridad con scratch si el motor
    # auto-aprueba lo descubierto por frecuencia; sin el flag, gate humano.
    auto = settings.auto_approve_scratch_codebook
    code_approval = "approved" if auto else "pending"
    group_status = "auto_coded" if auto else "suggested"

    grouped = 0
    winner_by_label: dict[str, str] = {}
    for proposal, cluster in zip(proposals, big_clusters, strict=True):
        label = proposal["label"]
        label_key = normalize(label)
        member_ids = cluster["member_ids"]
        if not member_ids:
            continue

        # Dedup en dos niveles: contra lo ya minado EN ESTE batch (DeepSeek
        # etiquetando dos clusters igual) y contra lo que YA existe en el libro
        # (una corrida anterior, quizás todavía 'pending').
        code_id = winner_by_label.get(label_key) or _find_code_by_label(db, codebook_id, label_key)
        if code_id is None:
            code_id = str(uuid.uuid4())
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
                      'engine_auto', :approval
                    )
                """),
                {
                    "id": code_id, "cb": codebook_id, "n": next_number,
                    "label": label,
                    "definition": proposal["definition"],
                    "inclusions": json.dumps(proposal["inclusion_criteria"]),
                    "exclusions": json.dumps(proposal["exclusion_criteria"]),
                    "examples": json.dumps(proposal["examples"]),
                    "approval": code_approval,
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
            next_number += 1
        winner_by_label[label_key] = code_id

        db.execute(
            text("""
                update mention_groups
                   set status = :status, suggested_code_id = :code
                 where id = any(:ids)
            """),
            {"status": group_status, "code": code_id, "ids": member_ids},
        )
        if auto:
            # Escribe la clasificación activa (igual que discover_new_brands): así
            # cuenta como auto-codificada y no cae al residual 97 ni la re-toma el LLM.
            db.execute(
                text("""
                    insert into verbatim_codes (id, verbatim_id, code_id, output_index,
                                                source, confidence_score, matched_alias,
                                                is_active)
                    select gen_random_uuid(), v.id, :code, 1, 'semantic_cache', 1.0,
                           v.normalized_text, true
                    from verbatims v where v.mention_group_id = any(:ids)
                    on conflict (verbatim_id, code_id) do update set is_active = true
                """),
                {"code": code_id, "ids": member_ids},
            )
            db.execute(
                text("""
                    update verbatims set coding_status = 'auto_coded'
                     where mention_group_id = any(:ids)
                """),
                {"ids": member_ids},
            )
        grouped += len(member_ids)

    return grouped


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
              join studies p on p.id = r.study_id
              left join categories cat on cat.id = r.category_id
             where sp.id = :sp
        """),
        {"sp": subproject_id},
    ).mappings().first()
    proposals = _propose_reason_codes_parallel(
        cluster_summaries, dict(context_row) if context_row else {},
        existing_nets=_existing_net_names(db, codebook_id),
    )

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
