"""Arma el catálogo de aliases contra el que corre el matcher, leyendo el
codebook más reciente de la ronda (aliases explícitos + labels normalizados
como fallback).
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.pipeline.normalize import normalize, strip_leading_article

from .models import (
    SCORE_THRESHOLD,
    SYSTEM_ALIAS_VARIANTS,
    CodeAlias,
)
from .scoring import COMMON_WORDS, best_brand_candidate


def _brandish_tokens(text_value: str) -> list[str]:
    """Tokens con pinta de nombre de marca: descarta stopwords y partículas
    cortas ('de', 'la'), que no distinguen marcas."""
    return [
        t for t in (text_value or "").split()
        if len(t) >= 3 and t not in COMMON_WORDS
    ]


_VOWELS_SET = set("aeiouáéíóúü")


def _is_junk_brand_seed(text_value: str) -> bool:
    """Un texto que NO debe volverse un código de marca: demasiado corto,
    stopword/artículo ('a', 'no', 'el', 'la'), o teclazo sin vocales. Evita los
    códigos basura como 'A' o 'No' que el descubrimiento creaba desde textos muy
    frecuentes de una o dos letras (el descubrimiento corre antes del prefiltro)."""
    t = (text_value or "").strip()
    if len(t) <= 2 or t in COMMON_WORDS:
        return True
    tokens = [tok for tok in t.split() if tok]
    if tokens and all(len(tok) <= 1 for tok in tokens):
        return True
    compact = "".join(ch for ch in t if not ch.isspace())
    letters = [c for c in compact if c.isalpha()]
    if len(letters) >= 4 and not any(c in _VOWELS_SET for c in letters):
        return True
    return False


def _looks_like_multiple_brands(representative: str, known_single_brands: set[str]) -> bool:
    """Un candidato multipalabra cuyos tokens son, cada uno, una marca por
    separado (p.ej. 'edam laive' = Edam + Laive, 'edan laive') NO debe volverse un
    código fusionado: es una respuesta con dos marcas y quién la resuelve es un
    humano. Se exige que al menos 2 de sus tokens de marca coincidan con marcas ya
    conocidas (del catálogo o de respuestas de una sola palabra en el mismo DAU).
    Una marca legítima de dos palabras ('otto kunz', 'cuisine and co') no dispara
    esto porque sus tokens no aparecen como marcas sueltas."""
    tokens = _brandish_tokens(representative)
    if len(tokens) < 2:
        return False
    return sum(1 for t in tokens if t in known_single_brands) >= 2


def load_catalog_aliases(db: Session, subproject_id: uuid.UUID) -> list[CodeAlias]:
    alias_rows = db.execute(
        text("""
            select ca.code_id::text as code_id, ca.alias_normalized
            from code_aliases ca
            join codes c on c.id = ca.code_id
            join codebooks cb on cb.id = ca.codebook_id
            join subprojects sp on sp.codebook_id = ca.codebook_id
            where sp.id = :sp
              and cb.status in ('approved', 'exported')
              and c.is_active and c.approval_status = 'approved'
              and ca.status = 'approved' and ca.alias_kind in ('positive', 'system')
              and ca.alias_normalized is not null and ca.alias_normalized <> ''
        """),
        {"sp": subproject_id},
    ).mappings().all()

    label_rows = db.execute(
        text("""
            select c.id::text as code_id, c.label
            from codes c
            join codebooks cb on cb.id = c.codebook_id
            join subprojects sp on sp.codebook_id = c.codebook_id
            where sp.id = :sp
              and cb.status in ('approved', 'exported')
              and c.approval_status = 'approved'
              and c.is_active
              and coalesce(c.is_system, false) = false
              and c.label is not null
              and trim(c.label) <> ''
        """),
        {"sp": subproject_id},
    ).mappings().all()

    # Aprendizaje ENTRE RONDAS del mismo proyecto: aliases aprobados en OTRAS
    # rondas de marcas (confirmados por un humano o heredados) se traen al catálogo
    # de esta ronda, remapeados al código actual que comparte el mismo label
    # normalizado. Así una escritura que ya se resolvió antes ("schugur" -> Chugur)
    # se captura sin volver a molestar al analista, aunque la ronda no haya sido
    # homologada explícitamente (la homologación ya los copia vía clone_codebook;
    # esto cubre el resto). Solo suma recall: nunca quita candidatos.
    cross_round_rows = db.execute(
        text("""
            select cur.id::text as code_id, a.alias_normalized
              from subprojects sp
              join rounds r on r.id = sp.round_id
              join codes cur on cur.codebook_id = sp.codebook_id
                            and cur.is_active and cur.approval_status = 'approved'
                            and coalesce(cur.is_system, false) = false
                            and cur.label is not null and trim(cur.label) <> ''
              join rounds r2 on r2.study_id = r.study_id and r2.id <> r.id
              join subprojects sp2 on sp2.round_id = r2.id and sp2.coding_type = 'brands'
              join codebooks cb2 on cb2.id = sp2.codebook_id
                                and cb2.status in ('approved', 'exported')
              join codes oc on oc.codebook_id = cb2.id and oc.is_active
                           and oc.approval_status = 'approved'
                           and coalesce(oc.is_system, false) = false
                           and lower(trim(oc.label)) = lower(trim(cur.label))
              join code_aliases a on a.code_id = oc.id and a.codebook_id = cb2.id
                                 and a.status = 'approved'
                                 and a.alias_kind in ('positive', 'system')
                                 and a.alias_normalized is not null
                                 and a.alias_normalized <> ''
             where sp.id = :sp
        """),
        {"sp": subproject_id},
    ).mappings().all()

    seen: set[tuple[str, str]] = set()
    catalog: list[CodeAlias] = []

    def _add(code_id: str, alias: str) -> None:
        alias = (alias or "").strip()
        if not alias or (code_id, alias) in seen:
            return
        seen.add((code_id, alias))
        catalog.append(CodeAlias(code_id=code_id, alias_normalized=alias))
        # Variante sin artículo inicial: si el código es 'El Prado', también matchea
        # la mención 'prado' (y viceversa). Solo agrega recall, apuntando al mismo
        # código.
        stripped = strip_leading_article(alias)
        if stripped != alias and len(stripped) >= 3 and (code_id, stripped) not in seen:
            seen.add((code_id, stripped))
            catalog.append(CodeAlias(code_id=code_id, alias_normalized=stripped))

    for r in alias_rows:
        _add(r["code_id"], r["alias_normalized"])
    for r in label_rows:
        _add(r["code_id"], normalize(r["label"]))
    for r in cross_round_rows:
        _add(r["code_id"], r["alias_normalized"])
    return catalog


def promote_llm_result_to_alias(
    db: Session,
    code_id: str,
    alias_normalized: str,
    alias_sample: str | None,
    match_score: float,
) -> None:
    """Promociona una marca clasificada por LLM sobre el umbral de promoción a
    alias fuzzy reutilizable, para que rondas futuras la capturen sin volver a
    tocar el LLM. codebook_id se resuelve desde code_id (no se pide al caller)
    porque classify.py ya conoce el code_id pero no arrastra codebook_id.
    Reprocesar el mismo texto no duplica fila: incrementa occurrences.
    """
    alias_normalized = (alias_normalized or "").strip()
    if not alias_normalized:
        return
    db.execute(
        text("""
            insert into code_aliases (id, codebook_id, code_id, alias_normalized,
                                      alias_sample, occurrences, origin, match_score,
                                      status, evidence)
            select gen_random_uuid(), c.codebook_id, :code, :norm, :sample, 1,
                   'llm_promoted', :score, 'pending',
                   jsonb_build_object('source', 'deepseek', 'self_confidence', :score)
            from codes c where c.id = :code
            on conflict (codebook_id, alias_normalized, code_id) do update
              set occurrences = code_aliases.occurrences + 1,
                  evidence = excluded.evidence
        """),
        {"code": code_id, "norm": alias_normalized, "sample": alias_sample, "score": match_score},
    )


def _clean_seed_label(representative: str, members: list) -> str:
    """Label de la semilla: el texto normalizado del representante, o el
    sample_text del encuestado SOLO si no agrega ruido (mismo número de palabras).
    Evita labels sucios tipo 'Edn laive' cuando el encuestado escribió palabras de
    más alrededor de la marca ('laive')."""
    raw_label = representative
    for m in members:
        if (
            m["normalized_text"] == representative
            and m["sample_text"]
            and len(m["sample_text"].split()) <= len(representative.split())
        ):
            raw_label = m["sample_text"]
            break
    return raw_label.strip().capitalize() if raw_label else raw_label


def _find_code_by_label(db: Session, codebook_id, label_key: str) -> str | None:
    """Busca un código YA existente en el libro (cualquier approval_status, activo)
    cuyo label normalizado calce con `label_key`. Sin esto, `discover_new_brands`
    podía minar un código DUPLICADO para una marca que ya tenía código: si ese
    código seguía 'pending' de aprobar, `load_catalog_aliases` no lo trae (solo
    aprobados) y el candidato caía a `pending_review` como si la marca fuera
    nueva. Recorrido en Python porque `label_key` ya pasó por `normalize()`
    (sin tildes/puntuación), que SQL no replica sin duplicar esa lógica."""
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


def _brand_code_numbers(start: int, occupied: set[int] | None = None):
    """Genera números nuevos sin reciclar ni colisionar con filas existentes."""
    used = occupied or set()
    n = start
    while True:
        while n in used or 95 <= n <= 99:
            n += 1
        yield n
        n += 1


def discover_catalog_from_frequency(
    db: Session,
    subproject_id: uuid.UUID,
    min_mentions: int,
    threshold: float = SCORE_THRESHOLD,
) -> list[CodeAlias]:
    """Fallback cuando la ronda no trae codebook: deriva las marcas 'semilla'
    de la frecuencia.

    El mínimo de menciones se evalúa por CLUSTER, no por texto individual:
    variantes/typos de una misma marca se agrupan primero por similitud fuzzy
    entre sí (sin importar la frecuencia de cada una por separado) y luego se
    suman sus frecuencias. Sin esto, una marca real dicha de dos formas
    distintas (p.ej. 'kraf' 1 mención + 'kraft' 1 mención) se perdía entera:
    ninguna de las dos individualmente alcanzaba el mínimo, y al no compararse
    entre sí tampoco se detectaban como la misma marca — quedaban ambas sin
    código, en vez de una sola marca con 2 menciones.

    Filtros de precisión sobre el cluster ya formado:

    - Respuestas de sistema ("no se", "ninguna"...) no se promueven como marcas:
      se vuelven aliases del código de sistema (96/98/99) y el fuzzy las codifica
      directo ahí. Sin esto, al ser de los textos más frecuentes, terminaban como
      marcas falsas en el codebook.
    - Las variantes se agrupan con el scorer multiseñal conservador; WRatio
      aislado no une clusters y los textos de hasta cuatro caracteres quedan
      separados para evitar casos como Bone -> Bonlé.

    Con ese catálogo el fuzzy arrastra los typos poco frecuentes hacia las
    semillas; lo que no se parezca a ninguna sigue al LLM (flujo normal).

    Escribe codes/code_aliases pero no hace commit: el caller confirma junto con
    el resto del run. Idempotente por construcción — una vez creadas las semillas,
    load_catalog_aliases ya devuelve catálogo y este fallback no se vuelve a tomar.
    """
    codebook_id = db.execute(
        text("select codebook_id from subprojects where id = :sp"),
        {"sp": subproject_id},
    ).scalar()
    if codebook_id is None:
        return []

    has_candidates = db.execute(
        text("""
            select exists(
              select 1 from codes
               where codebook_id = :cb and not is_system and is_active
            )
        """),
        {"cb": codebook_id},
    ).scalar()
    if has_candidates:
        return []

    # Sin el corte por frequency_count aquí: se necesita ver TODOS los
    # candidatos para poder agruparlos entre sí antes de decidir qué cluster
    # alcanza el mínimo (ver docstring).
    candidates = db.execute(
        text("""
            select id, normalized_text, sample_text, frequency_count
            from mention_groups
            where subproject_id = :sp
              and status = 'pending_review'
              and normalized_text <> ''
            order by frequency_count desc, normalized_text
        """),
        {"sp": subproject_id},
    ).mappings().all()
    if not candidates:
        return []

    def _persist_alias(
        code_id,
        alias_normalized: str,
        alias_sample: str | None,
        occurrences: int | None,
        *,
        approved_system: bool = False,
    ) -> None:
        db.execute(
            text("""
                insert into code_aliases (id, codebook_id, code_id, alias_normalized,
                                          alias_sample, occurrences, origin,
                                          alias_kind, status, evidence, approved_at)
                values (:id, :cb, :code, :norm, :sample, :occ, 'engine_fuzzy',
                        :kind, :status, cast(:evidence as jsonb),
                        case when :status = 'approved' then now() else null end)
                on conflict (codebook_id, alias_normalized, code_id) do nothing
            """),
            {
                "id": uuid.uuid4(), "cb": codebook_id, "code": code_id,
                "norm": alias_normalized, "sample": alias_sample, "occ": occurrences,
                "kind": "system" if approved_system else "positive",
                "status": "approved" if approved_system else "pending",
                "evidence": '{"source":"bootstrap_frequency"}',
            },
        )

    catalog: list[CodeAlias] = []
    alias_to_code: dict[str, str] = {}

    # Aliases de los códigos de sistema del codebook (96/98/99): capturan las
    # respuestas "no sabe"/"ninguna"/"no recuerda" y sus variantes.
    system_rows = db.execute(
        text("""
            select id::text as code_id, system_type from codes
            where codebook_id = :cb and is_system and system_type is not null
        """),
        {"cb": codebook_id},
    ).mappings().all()
    system_aliases: list[str] = []
    for row in system_rows:
        for variant in SYSTEM_ALIAS_VARIANTS.get(row["system_type"], ()):
            _persist_alias(row["code_id"], variant, None, None, approved_system=True)
            catalog.append(CodeAlias(code_id=row["code_id"], alias_normalized=variant))
            alias_to_code[variant] = row["code_id"]
            system_aliases.append(variant)

    # Numeración correlativa a partir del último code de marca no-system,
    # respetando cualquier código ya presente en el libro.
    # Serializa la asignación de code_number: subprojects corren en threads
    # paralelos (process.py) — sin este lock dos hilos leen el mismo max()
    # antes de que el otro inserte, chocando en codes_codebook_id_code_number_key.
    db.execute(text("select id from codebooks where id = :cb for update"), {"cb": codebook_id})
    next_number = db.execute(
        text("""
            select coalesce(max(code_number), 0) + 1 from codes
            where codebook_id = :cb and coalesce(is_system, false) = false
        """),
        {"cb": codebook_id},
    ).scalar()
    occupied_rows = db.execute(
        text("select code_number from codes where codebook_id = :cb"),
        {"cb": codebook_id},
    ).mappings().all()
    occupied = {row["code_number"] for row in occupied_rows}
    numbers = _brand_code_numbers(next_number, occupied)

    # Fase 1: agrupar candidatos por similitud fuzzy entre sí, sin filtrar
    # todavía por mínimo de menciones. Recorridos en orden de frecuencia desc.
    # (ya viene así de la query) para que el representante de cada cluster sea
    # su miembro más frecuente.
    cluster_reprs: list[str] = []
    clusters: dict[str, list] = {}
    for cand in candidates:
        norm = cand["normalized_text"]

        # Respuesta de sistema disfrazada de marca -> alias de 96/98/99, nunca
        # entra al clustering de marcas.
        if norm in alias_to_code and norm in system_aliases:
            code_id = alias_to_code[norm]
            _persist_alias(
                code_id, norm, cand["sample_text"], cand["frequency_count"],
                approved_system=True,
            )
            catalog.append(CodeAlias(code_id=code_id, alias_normalized=norm))
            continue

        cluster_hit = best_brand_candidate(
            norm,
            [CodeAlias(code_id=representative, alias_normalized=representative) for representative in cluster_reprs],
        )
        if cluster_hit:
            clusters[cluster_hit.code_id].append(cand)
        else:
            clusters[norm] = [cand]
            cluster_reprs.append(norm)

    # Marcas de UNA sola palabra observadas como respuesta suelta: sirven para
    # detectar respuestas que nombran dos marcas ('edam laive' = Edam + Laive) y
    # NO fusionarlas en un código inventado.
    single_word_brands = {rep for rep in cluster_reprs if len(_brandish_tokens(rep)) == 1}

    # Fase 2: solo se promueven a code nuevo los clusters cuya frecuencia
    # SUMADA alcanza el mínimo — el resto sigue como pending_review para el LLM.
    for representative, members in clusters.items():
        total = sum(m["frequency_count"] for m in members)
        if total < min_mentions:
            continue

        # Basura/stopword ('a', 'no', teclazo): nunca es una marca; se deja para el
        # prefiltro/residual, no se crea un código.
        if _is_junk_brand_seed(representative):
            continue

        # Respuesta con dos marcas distintas ('edam laive'): no se crea un código
        # fusionado; sus menciones siguen pending_review para que un humano las
        # revise y elija a cuál marca van (o si son ambas). Se mira TODO el cluster,
        # no solo el representante, por si la forma más frecuente es un typo.
        if any(
            _looks_like_multiple_brands(m["normalized_text"], single_word_brands)
            for m in members
        ):
            continue

        code_id = str(uuid.uuid4())
        formatted_label = _clean_seed_label(representative, members)
        db.execute(
            text("""
                insert into codes (
                  id, codebook_id, code_number, label, definition, examples,
                  origin, approval_status
                )
                values (
                  :id, :cb, :n, :label, :definition, cast(:examples as jsonb),
                  'engine_auto', 'pending'
                )
            """),
            {
                "id": code_id, "cb": codebook_id, "n": next(numbers),
                "label": formatted_label,
                "definition": f"Categoría candidata agrupada desde {total} menciones del DAU.",
                "examples": json.dumps(
                    [m["sample_text"] or m["normalized_text"] for m in members[:5]]
                ),
            },
        )
        for m in members:
            norm = m["normalized_text"]
            _persist_alias(code_id, norm, m["sample_text"], m["frequency_count"])
            catalog.append(CodeAlias(code_id=code_id, alias_normalized=norm))
            alias_to_code[norm] = code_id
        db.execute(
            text("""
                update mention_groups
                   set status = 'suggested', suggested_code_id = :code
                 where id = any(:ids)
            """),
            {"code": code_id, "ids": [m["id"] for m in members]},
        )

    return catalog


def discover_new_brands(
    db: Session, subproject_id: uuid.UUID, min_mentions: int,
) -> int:
    """Crea marcas NUEVAS por frecuencia en rondas que HEREDAN el libro de códigos.

    `discover_catalog_from_frequency` solo corre con libro vacío (scratch). En una
    ronda que hereda/importa el catálogo, una marca real que nunca estuvo en él
    (p.ej. 'wong' con 4 menciones >= mínimo 3) no tenía forma de nacer: caía al
    residual 95. Esta función corre DESPUÉS del fuzzy — sobre lo que quedó
    `pending_review`, es decir, lo que el catálogo existente NO reconoció — agrupa
    por similitud y, para cada cluster cuya frecuencia sumada alcanza el mínimo,
    crea un código nuevo con sus menciones ya clasificadas.

    Paridad con el path DE CERO: una ronda scratch descubre su catálogo por
    frecuencia y, si `auto_approve_scratch_codebook` está activo (default), lo
    auto-aprueba y auto-codifica. Sin esto, una ronda HEREDADA era estrictamente
    PEOR que la misma ronda procesada de cero: las marcas que la de cero
    auto-cerraba, la heredada solo las dejaba `suggested` (sin clasificar). Por eso
    `discover_new_brands` honra la MISMA política:

    - con `auto_approve_scratch_codebook` (default): el código nace `approved`, sus
      aliases `approved` y sus menciones `auto_coded` con `verbatim_codes` activos —
      igual que en scratch. Además los aliases quedan aprobados, así que la SIGUIENTE
      ronda que herede este libro también los reconoce (aprendizaje acumulado).
    - sin el flag (gate humano): el código nace `pending` y sus menciones quedan
      `suggested` para revisión, como antes.

    Los singletons y clusters chicos siguen `pending_review` hacia el LLM. Devuelve
    cuántas menciones agrupó. No hace commit: el caller cierra la transacción del
    subproyecto.
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
    if not row or row["coding_type"] != "brands":
        return 0
    # Las rondas scratch ya descubren su catálogo en discover_catalog_from_frequency.
    if row["codebook_origin"] == "scratch":
        return 0
    codebook_id = row["codebook_id"]
    if codebook_id is None:
        return 0

    candidates = db.execute(
        text("""
            select id, normalized_text, sample_text, frequency_count
              from mention_groups
             where subproject_id = :sp
               and status = 'pending_review'
               and normalized_text <> ''
             order by frequency_count desc, normalized_text
        """),
        {"sp": subproject_id},
    ).mappings().all()
    if not candidates:
        return 0

    # Agrupar los no reconocidos entre sí (mismo scorer conservador que el
    # bootstrap): typos de la misma marca nueva suman su frecuencia.
    cluster_reprs: list[str] = []
    clusters: dict[str, list] = {}
    for cand in candidates:
        norm = cand["normalized_text"]
        hit = best_brand_candidate(
            norm,
            [CodeAlias(code_id=r, alias_normalized=r) for r in cluster_reprs],
        )
        if hit:
            clusters[hit.code_id].append(cand)
        else:
            clusters[norm] = [cand]
            cluster_reprs.append(norm)

    # Serializa la asignación de code_number entre subprojects paralelos —
    # ver comentario equivalente más arriba en este archivo.
    db.execute(text("select id from codebooks where id = :cb for update"), {"cb": codebook_id})
    next_number = db.execute(
        text("""
            select coalesce(max(code_number), 0) + 1 from codes
            where codebook_id = :cb and coalesce(is_system, false) = false
        """),
        {"cb": codebook_id},
    ).scalar() or 1
    occupied = {
        r["code_number"]
        for r in db.execute(
            text("select code_number from codes where codebook_id = :cb"),
            {"cb": codebook_id},
        ).mappings().all()
    }
    numbers = _brand_code_numbers(next_number, occupied)

    # Marcas ya conocidas (del catálogo heredado + respuestas de una sola palabra):
    # sirven para no fusionar una respuesta con dos marcas ('edam laive') en un
    # código nuevo. En rondas heredadas 'edam' y 'laive' suelen ser códigos que ya
    # existen, así que se leen del catálogo, no solo de los candidatos sueltos.
    known_single_brands = {
        _brandish_tokens(a.alias_normalized)[0]
        for a in load_catalog_aliases(db, subproject_id)
        if len(_brandish_tokens(a.alias_normalized)) == 1
    }
    known_single_brands |= {rep for rep in cluster_reprs if len(_brandish_tokens(rep)) == 1}

    # Misma política que el path de cero: si el motor auto-aprueba los catálogos
    # descubiertos por frecuencia, también auto-cierra estas marcas (paridad con
    # scratch); si hay gate humano, quedan como propuesta pendiente.
    auto = settings.auto_approve_scratch_codebook
    code_approval = "approved" if auto else "pending"
    alias_status = "approved" if auto else "pending"
    group_status = "auto_coded" if auto else "suggested"

    grouped = 0
    for representative, members in clusters.items():
        total = sum(m["frequency_count"] for m in members)
        if total < min_mentions:
            continue
        # Basura/stopword ('a', 'no', teclazo): no es una marca.
        if _is_junk_brand_seed(representative):
            continue
        # Respuesta con dos marcas distintas ('edam laive'): no se crea un código
        # fusionado; se deja pending_review para revisión humana (elegir cuál marca).
        if any(
            _looks_like_multiple_brands(m["normalized_text"], known_single_brands)
            for m in members
        ):
            continue
        member_ids = [m["id"] for m in members]
        label = _clean_seed_label(representative, members)
        # Antes de minar código nuevo: ¿ya existe uno con este label en el libro
        # (aprobado o todavía 'pending' de una corrida anterior)? Sin este check,
        # una marca cuyo código real seguía sin aprobar terminaba con DOS códigos
        # para la misma marca (uno viejo pending, uno nuevo aquí) — ver
        # `_find_code_by_label`.
        code_id = _find_code_by_label(db, codebook_id, normalize(label))
        if code_id is None:
            code_id = str(uuid.uuid4())
            definition = (
                f"Marca nueva detectada por frecuencia: {total} menciones no reconocidas "
                f"por el catálogo heredado."
                + ("" if auto else " Pendiente de confirmación.")
            )
            db.execute(
                text("""
                    insert into codes (
                      id, codebook_id, code_number, label, definition, examples,
                      origin, approval_status
                    )
                    values (
                      :id, :cb, :n, :label, :definition, cast(:examples as jsonb),
                      'engine_auto', :approval
                    )
                """),
                {
                    "id": code_id, "cb": codebook_id, "n": next(numbers),
                    "label": label,
                    "definition": definition,
                    "examples": json.dumps(
                        [m["sample_text"] or m["normalized_text"] for m in members[:5]]
                    ),
                    "approval": code_approval,
                },
            )
        db.execute(
            text("""
                insert into code_aliases (id, codebook_id, code_id, alias_normalized,
                                          alias_sample, occurrences, origin,
                                          alias_kind, status, evidence, approved_at)
                values (:id, :cb, :code, :norm, :sample, :occ, 'engine_fuzzy',
                        'positive', :status, '{"source":"discover_new_brands"}'::jsonb,
                        case when :status = 'approved' then now() else null end)
                on conflict (codebook_id, alias_normalized, code_id) do nothing
            """),
            [
                {
                    "id": uuid.uuid4(), "cb": codebook_id, "code": code_id,
                    "norm": m["normalized_text"], "sample": m["sample_text"],
                    "occ": m["frequency_count"], "status": alias_status,
                }
                for m in members
            ],
        )
        db.execute(
            text("""
                update mention_groups
                   set status = :status, suggested_code_id = :code
                 where id = any(:ids)
            """),
            {"status": group_status, "code": code_id, "ids": member_ids},
        )
        if auto:
            # Escribe la clasificación activa (igual que _process_brands): así cuenta
            # como auto-codificada y no cae al residual 95 ni la re-toma el LLM.
            db.execute(
                text("""
                    insert into verbatim_codes (id, verbatim_id, code_id, output_index,
                                                source, confidence_score, matched_alias,
                                                is_active)
                    select gen_random_uuid(), v.id, :code, 1, 'engine_fuzzy', 1.0,
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
        grouped += len(members)

    return grouped
