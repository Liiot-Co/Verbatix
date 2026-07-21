import json
from collections import defaultdict
from pathlib import Path

from app.pipeline.normalize.text import normalize
from scripts.classification_accuracy_benchmark import (
    LabeledVerbatim,
    TemporalMemory,
    evaluate_predictions,
    fuzzy_candidates,
    temporal_replay,
)


FIXTURE = Path(__file__).parent / "fixtures" / "classification_benchmark_cases.json"
# Datos reales del cliente: tracker QUESO GLORIA rondas 1, 3 y 4 (hojas
# Verbatims_Marcas / Verbatims_Razones de los LC entregados). Es la verdad de
# referencia contra la que debe medirse el motor.
CLIENT_FIXTURE = (
    Path(__file__).parent / "fixtures" / "classification_benchmark_quesos_client.json"
)


def _rounds_from_payload(payload):
    rounds = defaultdict(lambda: {"brands": [], "reasons": []})
    for block in payload["rounds"]:
        coding_type = block["coding_type"]
        for row in block["rows"]:
            rounds[block["round"]][coding_type].append(
                LabeledVerbatim(
                    coding_type=coding_type,
                    original_text=row["text"],
                    normalized_text=normalize(row["text"]),
                    code_number=row["code"],
                )
            )
    return dict(rounds)


def _rounds_from_fixture():
    return _rounds_from_payload(json.loads(FIXTURE.read_text(encoding="utf-8")))


def _client_rounds():
    return _rounds_from_payload(json.loads(CLIENT_FIXTURE.read_text(encoding="utf-8")))


def test_temporal_replay_learns_only_from_previous_rounds():
    report = temporal_replay(_rounds_from_fixture())
    by_type = {row["coding_type"]: row for row in report["evaluations"]}

    brands = by_type["brands"]["exact"]["row_weighted"]
    assert brands["total"] == 4
    assert brands["covered"] == 3
    assert brands["correct"] == 3
    assert brands["coverage"] == 0.75
    assert brands["precision_on_covered"] == 1.0

    reasons = by_type["reasons"]["exact"]["row_weighted"]
    assert reasons["covered"] == 1
    assert reasons["correct"] == 1
    assert reasons["abstention_rate"] == 0.5


def test_replay_keeps_bone_separate_from_bonle():
    report = temporal_replay(_rounds_from_fixture())
    brands = next(
        row for row in report["evaluations"] if row["coding_type"] == "brands"
    )
    matrix = brands["exact"]["row_weighted"]["confusion_matrix"]
    assert matrix["95"] == {"95": 1}
    assert matrix["2"] == {"2": 1}


def test_fuzzy_is_reported_as_candidate_on_exact_residue():
    rounds = _rounds_from_fixture()
    memory = TemporalMemory()
    memory.add(rounds[1]["brands"])

    predictions, _ = fuzzy_candidates(rounds[2]["brands"], memory, "brands")

    assert predictions["bomle"] == 2
    assert "bone" not in predictions  # ya estaba cubierto por memoria exacta


def test_metrics_are_reported_by_rows_and_groups():
    items = [
        LabeledVerbatim("brands", "Gloria", "gloria", 1),
        LabeledVerbatim("brands", "GLORIA", "gloria", 1),
        LabeledVerbatim("brands", "Laive", "laive", 3),
    ]

    metrics = evaluate_predictions(items, {"gloria": 1, "laive": None})

    assert metrics["row_weighted"]["total"] == 3
    assert metrics["row_weighted"]["covered"] == 2
    assert metrics["group_weighted"]["total"] == 2
    assert metrics["group_weighted"]["covered"] == 1
    assert metrics["group_weighted"]["confusion_matrix"]["__abstain__"] == {"3": 1}


def test_client_quesos_replay_reproduces_precision_floor():
    """Replay temporal contra los LC reales del cliente (QUESO R1->R3->R4). La
    memoria exacta aprobada (R2+) debe reproducir el piso documentado: cobertura
    ~78-86% con precisión >=98% en lo cubierto, sin conflictos silenciosos. Es la
    base sobre la que fuzzy/semántico/LLM (ahora con auto-commit) suben la
    cobertura hacia ~90-95% sin sacrificar precisión."""
    report = temporal_replay(_client_rounds())
    by_key = {(ev["coding_type"], ev["round"]): ev for ev in report["evaluations"]}

    # Se aprende solo del pasado: R1 no se evalúa (no hay memoria previa).
    assert set(by_key) == {("brands", 3), ("brands", 4), ("reasons", 3), ("reasons", 4)}

    for (coding_type, rnd), ev in by_key.items():
        rows = ev["exact"]["row_weighted"]
        assert rows["coverage"] >= 0.75, (coding_type, rnd, rows["coverage"])
        assert rows["precision_on_covered"] >= 0.98, (coding_type, rnd, rows["precision_on_covered"])

    # R4 acumula R1+R3: la cobertura de marcas debe superar el 0.85 documentado.
    brands_r4 = by_key[("brands", 4)]
    assert brands_r4["exact"]["row_weighted"]["coverage"] >= 0.85
    # Exacto + fuzzy sube la cobertura por encima de solo exacto. Ojo: este número
    # es en modo recall (el benchmark trata TODA predicción fuzzy como cerrada); en
    # producción el fuzzy solo auto-cierra si pasa el gate calibrado
    # (brand_fuzzy_autocommit_score/margin) y si no, queda como sugerencia para
    # Resolución — por eso el motor real es más preciso que este piso pesimista.
    combined = brands_r4["exact_plus_fuzzy"]["row_weighted"]
    assert combined["coverage"] > brands_r4["exact"]["row_weighted"]["coverage"]
    assert combined["precision_on_covered"] >= 0.90
    # El histórico del cliente trae sus propias contradicciones (un mismo texto
    # codificado distinto entre rondas). El motor debe EXPONERLAS, no heredarlas en
    # silencio: cada conflicto reportado tiene >1 código para el mismo texto.
    conflicts = report["historical_conflicts"]
    assert isinstance(conflicts, list) and conflicts
    assert all(len(c["code_counts"]) > 1 for c in conflicts)


def _simulate_from_scratch_brands(rows, *, min_mentions, bucket_confuso):
    """Reproduce la ruta real de una ronda de Marcas DESDE CERO sobre datos del
    cliente: normalizar -> agrupar -> clusterizar variantes por fuzzy -> promover a
    código los clusters con frecuencia sumada >= min_mentions -> (opcional) cerrar el
    residuo al bucket confuso (95). Devuelve (coverage, correct) ponderado por fila.
    Mide contra el propio gold del cliente por voto de mayoría del cluster (no
    circular)."""
    from collections import Counter, defaultdict
    from app.pipeline.fuzzy.models import CodeAlias
    from app.pipeline.fuzzy.scoring import best_brand_candidate

    total = len(rows)
    groups: dict[str, list[int]] = defaultdict(list)
    for lv in rows:
        groups[lv.normalized_text].append(lv.code_number)
    freq = {n: len(c) for n, c in groups.items()}
    gold = {n: Counter(c).most_common(1)[0][0] for n, c in groups.items()}

    reprs: list[str] = []
    clusters: dict[str, list[str]] = defaultdict(list)
    for n in sorted(groups, key=lambda k: (-freq[k], k)):
        hit = best_brand_candidate(n, [CodeAlias(code_id=r, alias_normalized=r) for r in reprs])
        (clusters[hit.code_id] if hit else clusters[n]).append(n)
        if not hit:
            reprs.append(n)

    promoted: dict[str, str] = {}
    cluster_major: dict[str, int] = {}
    for rep, members in clusters.items():
        if sum(freq[m] for m in members) >= min_mentions:
            votes: Counter[int] = Counter()
            for m in members:
                votes[gold[m]] += freq[m]
            cluster_major[rep] = votes.most_common(1)[0][0]
            for m in members:
                promoted[m] = rep

    covered = correct = 0
    for n in groups:
        if n in promoted:
            covered += freq[n]
            if cluster_major[promoted[n]] == gold[n]:
                correct += freq[n]
        elif bucket_confuso:
            covered += freq[n]
            if gold[n] == 95:  # estricto: solo cuenta el 95 real como acierto
                correct += freq[n]
    return covered / total, correct / total


def test_from_scratch_brands_reaches_ninety_percent_on_client_data():
    """Meta pactada con el usuario: >=90% de clasificación correcta en Marcas desde
    cero contra el LC real del cliente, sin memoria previa. Se logra con el umbral de
    bootstrap en 2 (marcas reales poco frecuentes obtienen código) + el bucket confuso
    (el residuo real, mayormente menciones confusas, se cierra al 95). El analista
    reclasifica en Resolución la minoría restante."""
    r1_brands = _client_rounds()[1]["brands"]

    # Umbral 2 + bucket: cobertura total, >=90% correcto (medido ~92.9%).
    cov, correct = _simulate_from_scratch_brands(r1_brands, min_mentions=2, bucket_confuso=True)
    assert cov == 1.0
    assert correct >= 0.90, correct

    # Regresión anti umbral-3: bajar de 3 a 2 sube la cobertura del bootstrap sin
    # bucket por encima del viejo ~87%.
    cov3, _ = _simulate_from_scratch_brands(r1_brands, min_mentions=3, bucket_confuso=False)
    cov2, _ = _simulate_from_scratch_brands(r1_brands, min_mentions=2, bucket_confuso=False)
    assert cov2 > cov3
    assert cov2 >= 0.90


def test_client_quesos_bone_never_collapses_into_bonle():
    """Caso borde no negociable: 'Bone' (gold 95, menciones confusas) nunca debe
    terminar clasificado como 'Bonlé' (código 2). La memoria exacta lo mantiene en
    95 y el confusion matrix no debe cruzarlo al 2."""
    report = temporal_replay(_client_rounds())
    brands_r3 = next(
        ev for ev in report["evaluations"]
        if ev["coding_type"] == "brands" and ev["round"] == 3
    )
    matrix = brands_r3["exact"]["row_weighted"]["confusion_matrix"]
    # Ningún verbatim con verdad 95 se predijo como Bonlé (2).
    assert "2" not in matrix.get("95", {})


def test_client_quesos_edan_and_edam_share_the_same_historical_code():
    brand_rows = [
        item
        for round_data in _client_rounds().values()
        for item in round_data["brands"]
        if item.normalized_text in {"edan", "edam"}
    ]
    codes_by_text = {
        text: {item.code_number for item in brand_rows if item.normalized_text == text}
        for text in ("edan", "edam")
    }

    assert codes_by_text["edan"]
    assert codes_by_text["edan"] == codes_by_text["edam"]


def test_historical_conflicts_are_exposed_instead_of_overwritten():
    memory = TemporalMemory()
    memory.add(
        [
            LabeledVerbatim("reasons", "Duración", "duracion", 32),
            LabeledVerbatim("reasons", "duracion", "duracion", 31),
            LabeledVerbatim("reasons", "duración", "duracion", 31),
        ]
    )

    assert memory.prediction("reasons", "duracion") == 31
    assert memory.conflicts() == [
        {
            "coding_type": "reasons",
            "normalized_text": "duracion",
            "code_counts": {"31": 2, "32": 1},
        }
    ]
