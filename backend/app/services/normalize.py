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
