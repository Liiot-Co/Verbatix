import unicodedata
import re

import spacy
from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.models import BrandVariation, Code, OfficialBrand

_nlp = spacy.load("es_core_news_sm")

GENERICS: set[str] = {
    "queso", "leche", "yogur", "cereales", "pan", "aceite", "arroz",
    "pasta", "agua", "jugo", "cerveza", "vino", "cafe", "te",
    "chocolate", "galletas", "papas", "fideos", "pollo", "carne",
    "pescado", "jabon", "shampoo", "detergente", "crema",
    "pasta dental", "panales", "toallas", "papel higienico",
    "suavizante", "supermercado", "farmacia",
    "panaderia", "carniceria", "verduleria", "local", "negocio",
    "producto", "otro", "ninguno", "varios",
    "diversas marcas", "no recuerda", "no sabe", "generico",
    "no se", "ns", "na", "n/a",
}

SHORT_GENERICS: set[str] = GENERICS | {"tienda", "marca", "compre en", "compra"}

_SHORT_THRESHOLD = 4  # tokens; below → match directly, above → extract first


def _clean(text: str) -> str:
    text = text.lower().strip()
    nfkd = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in nfkd if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_proper_tokens(text: str) -> str | None:
    doc = _nlp(text)
    tokens = [
        tok.text for tok in doc
        if tok.pos_ == "PROPN" or tok.ent_type_ in ("ORG", "PRODUCT", "GPE")
    ]
    return " ".join(tokens) if tokens else None


def _is_generic(clean: str) -> bool:
    words = clean.split()
    if len(words) <= 4 and clean in SHORT_GENERICS:
        return True
    for g in GENERICS:
        if fuzz.ratio(clean, g) >= 92:
            return True
    return False


def _match_variations(term: str, db: Session) -> tuple[float, "BrandVariation | None"]:
    variations = db.query(BrandVariation).all()
    best, score = None, 0
    for var in variations:
        s = fuzz.WRatio(term, var.variation_text)
        if s > score:
            score, best = s, var
    return score, best


def _match_brands(term: str, db: Session) -> tuple[float, "OfficialBrand | None"]:
    brands = db.query(OfficialBrand).all()
    best, score = None, 0
    for b in brands:
        s = fuzz.WRatio(term, b.name)
        if s > score:
            score, best = s, b
    return score, best


def _resolve_brand(term: str, db: Session, min_score: int = 85) -> dict | None:
    """Try variations then brands on `term`. Return result dict or None."""
    var_score, best_var = _match_variations(term, db)
    if best_var and var_score >= min_score:
        brand = db.query(OfficialBrand).get(best_var.official_brand_id)
        return {
            "extracted_term": term,
            "official_brand_id": brand.id if brand else None,
            "suggested_brand": brand.name if brand else None,
            "confidence": round(var_score / 100.0, 3),
            "status": "auto_approved",
        }

    brand_score, best_brand = _match_brands(term, db)
    if best_brand and brand_score >= min_score:
        return {
            "extracted_term": term,
            "official_brand_id": best_brand.id,
            "suggested_brand": best_brand.name,
            "confidence": round(brand_score / 100.0, 3),
            "status": "auto_approved",
        }
    return None


def classify_text(text: str, db: Session) -> dict:
    clean = _clean(text)
    words = clean.split()
    is_short = len(words) <= _SHORT_THRESHOLD

    # 1. Short text: try direct variation/brand match before anything else
    if is_short:
        result = _resolve_brand(clean, db)
        if result:
            return result

    # 2. Generic check
    if _is_generic(clean):
        return {
            "extracted_term": clean,
            "official_brand_id": None,
            "suggested_brand": None,
            "confidence": 1.0,
            "status": "generic",
        }

    # 3. spaCy NER extraction
    extracted = _extract_proper_tokens(clean)

    # 4. Match on extracted tokens (if found)
    if extracted:
        result = _resolve_brand(extracted, db)
        if result:
            return result

    # 5. Long text fallback: try direct match only with higher confidence bar
    if not is_short:
        result = _resolve_brand(clean, db, min_score=90)
        if result:
            result["extracted_term"] = extracted or clean
            return result

    best_conf = 0.0
    if extracted:
        s, _ = _match_brands(extracted, db)
        best_conf = round(s / 100.0, 3)

    return {
        "extracted_term": extracted or clean,
        "official_brand_id": None,
        "suggested_brand": None,
        "confidence": best_conf,
        "status": "requires_human",
    }


_CODE_MATCH_THRESHOLD = 80


def classify_codes(text: str, study_id: int | None, db: Session) -> list[dict]:
    """Fuzzy-match `text` against the codebook of `study_id`. Additive: does not
    touch classify_text / brand classification."""
    if not study_id:
        return []

    clean = _clean(text)
    codes = db.query(Code).filter(Code.study_id == study_id).all()

    matches = []
    for code in codes:
        score = fuzz.WRatio(clean, code.name.lower())
        if code.keywords:
            for kw in code.keywords.split(","):
                kw = kw.strip().lower()
                if kw:
                    score = max(score, fuzz.partial_ratio(clean, kw))
        if score >= _CODE_MATCH_THRESHOLD:
            matches.append({
                "code_id": code.id,
                "name": code.name,
                "confidence": round(score / 100.0, 3),
            })

    matches.sort(key=lambda m: -m["confidence"])
    return matches
