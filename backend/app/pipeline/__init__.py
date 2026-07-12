"""Pipeline: ingest (excel) -> normalize -> fuzzy (marcas) -> llm (razones/leftover).

Cada etapa vive en su propio subpaquete; `process.py` es el único punto que
las conoce todas y decide el orden. Ver docs/ideas/verbatix-sharpen.md para
el diseño del motor de razones.
"""

from app.pipeline.llm import classify_studio
from app.pipeline.process import process_studio

__all__ = ["classify_studio", "process_studio"]
