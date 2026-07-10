# Handoff → OpenCode | Stage 4 — Learning Loop + Multi-Round

**Rol:** backend-dev  
**No tocar:** `frontend/`  
**Stack nuevo:** SQLAlchemy (sync) o SQLModel + uvicorn + FastAPI existente

---

## O2 — Modelos SQLAlchemy + migración

`backend/app/models.py`

```python
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()

class Round(Base):
    __tablename__ = "rounds"
    id         = Column(Integer, primary_key=True)
    name       = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    responses  = relationship("SurveyResponse", back_populates="round")

class OfficialBrand(Base):
    __tablename__ = "official_brands"
    id         = Column(Integer, primary_key=True)
    name       = Column(String, unique=True, nullable=False)
    variations = relationship("BrandVariation", back_populates="brand")

class BrandVariation(Base):
    __tablename__ = "brand_variations"
    id               = Column(Integer, primary_key=True)
    variation_text   = Column(String, nullable=False, index=True)
    official_brand_id= Column(Integer, ForeignKey("official_brands.id"))
    brand            = relationship("OfficialBrand", back_populates="variations")

class SurveyResponse(Base):
    __tablename__ = "survey_responses"
    id               = Column(Integer, primary_key=True)
    round_id         = Column(Integer, ForeignKey("rounds.id"), nullable=False)
    original_text    = Column(Text, nullable=False)
    extracted_term   = Column(String)
    confidence       = Column(Float, default=0.0)
    status           = Column(String, default="requires_human")  # auto_approved | requires_human | generic | rejected
    official_brand_id= Column(Integer, ForeignKey("official_brands.id"), nullable=True)
    round            = relationship("Round", back_populates="responses")
    brand            = relationship("OfficialBrand")
```

`backend/app/database.py` — engine SQLite + `create_all()` en startup.

---

## O3 — Seed inicial

`backend/app/seed.py` — ejecutable standalone.

Poblar `official_brands` con al menos 30 marcas: Amazon, Mercado Libre, Rappi, Uber Eats, Netflix, Spotify, Apple, Samsung, LG, Sony, Coca-Cola, Pepsi, Nestlé, Unilever, P&G, Bimbo, Lala, Alpura, Corona, Modelo, Heineken, Jumex, Bonafont, Sabritas, Gamesa, Kellogg, Nutrisa, Farmacias del Ahorro, Walmart, OXXO.

Poblar `brand_variations` con alias comunes: "amzon"→Amazon, "mercadolibre"→Mercado Libre, "meli"→Mercado Libre, "rapii"→Rappi, "ubereats"→Uber Eats, etc.

Ejecutar seed en `lifespan` de FastAPI si las tablas están vacías.

---

## O4 — Endpoints de Round

```
POST /api/rounds       body: {name: str}  → Round
GET  /api/rounds       → list[Round + counts]
```

`GET /api/rounds` response incluye `total`, `auto_approved`, `requires_human` calculados con COUNT + GROUP BY desde `survey_responses`.

---

## O5 — Pipeline actualizado

`backend/app/services/pipeline.py`

```python
def classify_text(text: str, db: Session) -> dict:
    # 1. Genéricos (tabla generics existente o lista hardcoded)
    # 2. BrandVariation lookup: query db, RapidFuzz WRatio vs variation_text
    #    → score ≥ 85 → auto_approved, official_brand_id = variation.official_brand_id
    # 3. spaCy NER → extraer PROPN
    # 4. RapidFuzz vs official_brands.name directamente
    #    → score ≥ 85 → auto_approved; < 85 → requires_human
    return {
        "extracted_term": str,
        "official_brand_id": int | None,
        "confidence": float,
        "status": str,
    }
```

`POST /api/upload` ahora requiere `round_id: int` en el form. Crea `SurveyResponse` por cada fila.

Response schema para frontend (campo `suggested_brand` = `official_brand.name` si resuelto):
```json
{
  "round_id": 1,
  "total": 150,
  "auto_approved": 98,
  "requires_human": 40,
  "generic": 12,
  "items": [{
    "id": 1,
    "original_text": "compré en Amzon",
    "extracted_term": "Amzon",
    "suggested_brand": "Amazon",
    "official_brand_id": 1,
    "confidence": 0.91,
    "status": "auto_approved"
  }]
}
```

---

## O6 — POST /resolve-anomaly ← NÚCLEO

`backend/app/routers/resolve.py`

```python
@router.post("/api/resolve-anomaly")
def resolve(body: ResolveRequest, db: Session):
    # body: {response_id: int, resolved_brand: str}

    # 1. Buscar o crear OfficialBrand por nombre exacto
    # 2. Insertar BrandVariation(variation_text=response.extracted_term, official_brand_id)
    #    solo si no existe ya esa variación
    # 3. Actualizar SurveyResponse: status="manual_resolved", official_brand_id
    # 4. CASCADE: buscar todos los SurveyResponse del mismo round con
    #    status="requires_human" y extracted_term similar (RapidFuzz ≥ 85)
    #    → actualizarlos a status="auto_approved", official_brand_id
    # 5. Devolver:
    return {
        "resolved": SurveyResponseItem,
        "cascade_resolved": list[SurveyResponseItem],  # los auto-resueltos
    }
```

---

## O7 — GET /export/{round_id}

```python
@router.get("/api/export/{round_id}")
def export_round(round_id: int, db: Session):
    rows = db.query(SurveyResponse, OfficialBrand)\
             .join(OfficialBrand, isouter=True)\
             .filter(SurveyResponse.round_id == round_id)\
             .all()
    # Generar CSV: original_text, extracted_term, official_brand (o ""), confidence, status
    # Devolver StreamingResponse con content-type text/csv
```

---

## Contrato exacto para Claude

Claude construye el frontend consumiendo exactamente estos endpoints. No cambiar nombres de campos.

| Campo frontend | Fuente DB |
|---|---|
| `item.id` | `survey_responses.id` |
| `item.original_text` | `survey_responses.original_text` |
| `item.extracted_term` | `survey_responses.extracted_term` |
| `item.suggested_brand` | `official_brands.name` (join) |
| `item.confidence` | `survey_responses.confidence` |
| `item.status` | `survey_responses.status` |
| `round.id` | `rounds.id` |
| `cascade_resolved[]` | lista de items auto-resueltos por el cascade |
