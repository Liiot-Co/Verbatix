import pandas as pd
from pathlib import Path
from typing import Optional


def load_excel(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return pd.read_excel(path, engine="openpyxl")


def list_columns(df: pd.DataFrame) -> list[str]:
    return list(df.columns)


def select_column(
    df: pd.DataFrame, column: str, label: str = "selected"
) -> pd.Series:
    if column not in df.columns:
        raise ValueError(f"Column '{column}' not found in dataframe")
    return df[column].rename(label)


def ingest(
    path: str | Path,
    answer_column: str,
    round_column: Optional[str] = None,
    sheet_name: str = "Hoja1",
) -> pd.DataFrame:
    df = load_excel(path)
    answers = df[answer_column].copy()
    result = pd.DataFrame({"respuesta_original": answers})
    result["respuesta_limpia"] = result["respuesta_original"].astype(str)
    if round_column and round_column in df.columns:
        result["ronda"] = df[round_column].values
    return result
