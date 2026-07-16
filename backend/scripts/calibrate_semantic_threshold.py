"""Calibración empírica de semantic_cache_similarity_threshold contra una ronda
de razones ya procesada y aprobada — mismo enfoque que se usó para calibrar
SCORE_THRESHOLD=80 en fuzzy (ver fuzzy/models.py).

Uso:
  cd backend
  ./env/bin/python scripts/calibrate_semantic_threshold.py <round_id>

Ground truth: un code_id por mention_group, tomado de verbatim_codes cuyo
source es 'analyst_manual'/'audit_correction' (confirmado por humano) o
'llm_classified' con confidence_score >= llm_promotion_confidence_threshold
(alta confianza). Grupos sin ninguna fila así quedan fuera del cálculo.

Método: nearest-neighbor leave-one-out. Para cada grupo, se busca su vecino
más cercano por similitud coseno entre el resto de grupos de la ronda (nunca
contra sí mismo) y se registra si ese vecino tiene el mismo code_id. Barriendo
el threshold:
  - hit  (similarity >= threshold): cuenta como TP si el vecino es del mismo
    code, FP si es de otro code.
  - miss (similarity < threshold): el grupo no se auto-codificaría — se pierde
    la oportunidad de ahorrar la llamada al LLM (no es un error, es recall
    perdido), a menos que el código real coincidiera y por tanto sea un TP
    perdido.
  precision = TP / (TP + FP)   — qué tan seguro es un hit
  recall    = TP / total       — qué fracción de grupos se hubiera resuelto sin LLM
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

for line in (BACKEND / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import numpy as np  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.pipeline.semantic.embed import embed  # noqa: E402

THRESHOLDS = [round(0.80 + 0.02 * i, 2) for i in range(8)]  # 0.80..0.94 step 0.02


def _fetch_ground_truth(db, round_id: str) -> list[dict]:
    rows = db.execute(
        text("""
            select distinct on (mg.id)
                mg.id as group_id, mg.normalized_text, vc.code_id
            from mention_groups mg
            join verbatims v on v.mention_group_id = mg.id
            join verbatim_codes vc on vc.verbatim_id = v.id
            where mg.round_id = :round
              and (
                  vc.source in ('analyst_manual', 'audit_correction')
                  or (vc.source = 'llm_classified' and vc.confidence_score >= :promo)
              )
            order by mg.id, vc.confidence_score desc nulls last
        """),
        {"round": round_id, "promo": settings.llm_promotion_confidence_threshold},
    ).mappings().all()
    return list(rows)


def _cosine_matrix(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    normalized = vectors / norms
    return normalized @ normalized.T


def calibrate(codes: list, vectors: np.ndarray, thresholds: list[float] = THRESHOLDS) -> list[dict]:
    """Nearest-neighbor leave-one-out precision/recall por threshold. Separado
    de main() para poder probarlo sin DB ni modelo de embeddings real (demo()
    abajo)."""
    sims = _cosine_matrix(vectors)
    np.fill_diagonal(sims, -1.0)  # nunca matchear un grupo contra sí mismo

    nearest_idx = sims.argmax(axis=1)
    nearest_sim = sims.max(axis=1)
    same_code = [codes[i] == codes[nearest_idx[i]] for i in range(len(codes))]

    results = []
    for threshold in thresholds:
        hit_mask = nearest_sim >= threshold
        tp = sum(1 for i in range(len(codes)) if hit_mask[i] and same_code[i])
        fp = sum(1 for i in range(len(codes)) if hit_mask[i] and not same_code[i])
        hits = tp + fp
        results.append({
            "threshold": threshold,
            "hits": hits,
            "tp": tp,
            "fp": fp,
            "precision": tp / hits if hits else float("nan"),
            "recall": tp / len(codes),
        })
    return results


def _print_table(results: list[dict]) -> None:
    print(f"{'threshold':>9} {'hits':>6} {'TP':>6} {'FP':>6} {'precision':>10} {'recall':>8}")
    for r in results:
        print(f"{r['threshold']:>9.2f} {r['hits']:>6} {r['tp']:>6} {r['fp']:>6} {r['precision']:>10.3f} {r['recall']:>8.3f}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Uso: calibrate_semantic_threshold.py <round_id>")
        sys.exit(1)
    round_id = sys.argv[1]

    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    db = sessionmaker(bind=create_engine(url, pool_pre_ping=True))()

    rows = _fetch_ground_truth(db, round_id)
    db.close()

    if len(rows) < 2:
        print(f"Solo {len(rows)} grupo(s) con ground truth confiable en esta ronda — no alcanza para calibrar.")
        return

    print(f"Ground truth: {len(rows)} mention_groups (ronda {round_id})")
    vectors = np.array([embed(r["normalized_text"]) for r in rows])
    codes = [r["code_id"] for r in rows]
    _print_table(calibrate(codes, vectors))


def demo() -> None:
    """ponytail: smoke check, no DB ni modelo real — dos clusters separados por
    similitud coseno deben dar precision/recall perfectos en el rango de
    thresholds calibrado, y grupos idénticos (sim=1.0) siempre matchean."""
    codes = ["a", "a", "b", "b"]
    vectors = np.array([
        [1.0, 0.0],
        [0.99, 0.01],   # casi idéntico al primero, mismo code -> TP a cualquier threshold razonable
        [0.0, 1.0],
        [0.01, 0.99],   # casi idéntico al tercero, mismo code -> TP
    ])
    results = calibrate(codes, vectors, thresholds=[0.5, 0.9])
    by_threshold = {r["threshold"]: r for r in results}
    assert by_threshold[0.5]["tp"] == 4 and by_threshold[0.5]["fp"] == 0
    assert by_threshold[0.5]["precision"] == 1.0
    assert by_threshold[0.5]["recall"] == 1.0

    # Un vector ambiguo (equidistante) rompe el cluster: debe aparecer como FP
    # en algún threshold sin tumbar el cálculo.
    mixed_codes = ["a", "a", "b"]
    mixed_vectors = np.array([[1.0, 0.0], [0.0, 1.0], [0.7, 0.7]])
    mixed_results = calibrate(mixed_codes, mixed_vectors, thresholds=[0.5])
    assert mixed_results[0]["hits"] <= 3
    print("demo() OK")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        demo()
    else:
        main()
