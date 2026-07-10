import re
import unicodedata
import pandas as pd
from collections import Counter
from typing import Optional


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def clean_text(text: str) -> str:
    text = str(text).lower()
    text = strip_accents(text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_column(df: pd.DataFrame, column: str = "respuesta_original") -> pd.DataFrame:
    df = df.copy()
    df["respuesta_limpia"] = df[column].astype(str).apply(clean_text)
    return df


def drop_empty(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)
    df = df[df["respuesta_limpia"].str.strip() != ""].copy()
    df = df[~df["respuesta_limpia"].isin({"", "ninguno", "ninguna", "no", "nada", "none", "si", "sí"})]
    return df


def extract_ngrams(text: str, n: int) -> list[str]:
    tokens = text.split()
    if len(tokens) < n:
        return []
    return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def extract_all_ngrams(
    series: pd.Series, max_n: int = 3
) -> dict[int, Counter]:
    result: dict[int, Counter] = {}
    for n in range(1, max_n + 1):
        counter: Counter = Counter()
        for text in series:
            for ngram in extract_ngrams(text, n):
                counter[ngram] += 1
        result[n] = counter
    return result


def compute_document_frequency(series: pd.Series, max_n: int = 3) -> dict[int, Counter]:
    result: dict[int, Counter] = {}
    for n in range(1, max_n + 1):
        counter: Counter = Counter()
        for text in series:
            tokens = text.split()
            seen = set()
            for i in range(len(tokens) - n + 1):
                ngram = " ".join(tokens[i : i + n])
                if ngram not in seen:
                    counter[ngram] += 1
                    seen.add(ngram)
        result[n] = counter
    return result


def run_pipeline(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "respuesta_limpia" not in df.columns or df["respuesta_limpia"].equals(df.get("respuesta_original")):
        df = clean_column(df)
    df = drop_empty(df)
    return df
