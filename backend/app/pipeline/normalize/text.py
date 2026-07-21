import re
import unicodedata


def normalize(text: str) -> str:
    """ minúsculas, sin tildes, sin puntuación, espacios colapsados.

    Misma regla para marcas y razones. No modifica el texto original guardado en BD.
    """
    if not text:
        return ""
    text = str(text).lower().strip()
    nfkd = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in nfkd if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_LEADING_ARTICLES = ("el", "la", "los", "las")


def strip_leading_article(text_value: str) -> str:
    """Quita un artículo inicial ('el paira' -> 'paira', 'el prado' -> 'prado')
    para el matcheo de marcas. NO se usa al normalizar de entrada — solo al comparar
    contra el catálogo — para que 'El Prado' y 'prado' calcen sin inventar reglas en
    la normalización base. Conserva el texto si al quitar el artículo quedaría muy
    corto (evita romper marcas cortas)."""
    t = (text_value or "").strip()
    parts = t.split(" ", 1)
    if len(parts) == 2 and parts[0] in _LEADING_ARTICLES and len(parts[1].strip()) >= 3:
        return parts[1].strip()
    return t
