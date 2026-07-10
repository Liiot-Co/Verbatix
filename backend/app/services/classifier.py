from pathlib import Path

import pandas as pd

from catalog.store import CatalogStore
from classification.classifier import Classifier as ClassifierEngine


def classify_answers(
    file_path: str | Path,
    answer_column: str,
    db_path: str,
) -> list[dict]:
    store = CatalogStore(db_path)
    alias_map = store.alias_map()
    engine = ClassifierEngine(alias_map)

    df = pd.read_excel(file_path, engine="openpyxl")
    answers = df[answer_column].dropna().astype(str).tolist()

    results = []
    for answer in answers:
        match = engine.classify(answer)
        results.append({
            "answer": answer,
            "product": match.product or "—",
            "method": match.method,
            "confidence": match.confidence,
            "status": match.status,
        })

    return results
