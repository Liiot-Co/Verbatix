from sqlalchemy.orm import Session

from app.models import OfficialBrand, BrandVariation, MarketStudy, Net, Code


SEED_BRANDS: dict[str, list[str]] = {
    "Amazon": ["amzon", "amazn", "amazon prime", "amazn prime", "amazoncom"],
    "Mercado Libre": ["mercadolibre", "meli", "mercado libre", "mercadopago", "ml"],
    "Rappi": ["rapii", "rappii", "rappis"],
    "Uber Eats": ["ubereats", "uber eats", "ubereat"],
    "Netflix": ["netflix", "netfliz", "netflx"],
    "Spotify": ["spotify", "spotyfy", "spotifay"],
    "Apple": ["apple", "aple", "manzana", "iphone", "ipad"],
    "Samsung": ["samsung", "samsug", "samgsung"],
    "LG": ["lg", "elelg", "lg electronics"],
    "Sony": ["sony", "soni", "sony entertainment"],
    "Coca-Cola": ["coca cola", "coca-cola", "cocacola", "coka"],
    "Pepsi": ["pepsi", "pepsi cola", "pepsicola"],
    "Nestle": ["nestle", "nestlé", "nestle mx"],
    "Unilever": ["unilever", "unilevr", "unilever mx"],
    "P&G": ["pg", "procter", "procter gamble", "pg products"],
    "Bimbo": ["bimbo", "bimb", "bimbo mx"],
    "Lala": ["lala", "lala mx", "lalas"],
    "Alpura": ["alpura", "alpur", "alpura mx"],
    "Corona": ["corona", "corona extra", "cerveza corona"],
    "Modelo": ["modelo", "modelo especial", "cerveza modelo"],
    "Heineken": ["heineken", "heineken mx", "heineken cerveza"],
    "Jumex": ["jumex", "jumex mx", "jumex jugo"],
    "Bonafont": ["bonafont", "bonafont mx", "bonafont agua"],
    "Sabritas": ["sabritas", "sabritas mx", "sabritita"],
    "Gamesa": ["gamesa", "gamesa mx", "gamesas"],
    "Kellogg": ["kellogg", "kelloggs", "kellogg mx"],
    "Nutrisa": ["nutrisa", "nutrisa mx", "nutrisas"],
    "Farmacias del Ahorro": ["farmacias del ahorro", "farma ahorro", "ahorro"],
    "Walmart": ["walmart", "wal mart", "walmex"],
    "OXXO": ["oxxo", "oxxo mx", "oxxo tienda"],
}


def seed_brands(db: Session) -> None:
    existing = db.query(OfficialBrand.name).all()
    existing_names = {name for (name,) in existing}

    for brand_name, variations in SEED_BRANDS.items():
        if brand_name not in existing_names:
            brand = OfficialBrand(name=brand_name)
            db.add(brand)
            db.flush()
        else:
            brand = db.query(OfficialBrand).filter_by(name=brand_name).first()

        existing_vars = {
            v.variation_text
            for v in db.query(BrandVariation)
            .filter_by(official_brand_id=brand.id)
            .all()
        }

        for var_text in variations:
            if var_text.lower() not in existing_vars:
                db.add(BrandVariation(
                    variation_text=var_text.lower(),
                    official_brand_id=brand.id,
                ))

    db.commit()


SEED_CODEBOOK: dict[str, list[dict]] = {
    "Producto": [
        {"name": "Calidad", "keywords": "calidad,durabilidad,resistente"},
        {"name": "Precio", "keywords": "precio,caro,costoso,barato"},
        {"name": "Disponibilidad", "keywords": "stock,disponible,agotado"},
    ],
    "Servicio": [
        {"name": "Atencion al cliente", "keywords": "atencion,servicio,trato,amable"},
        {"name": "Tiempo de entrega", "keywords": "entrega,demora,rapido,tardanza"},
    ],
}


def seed_demo_study(db: Session) -> None:
    study = MarketStudy(name="Marcas Retail LATAM Q2", client="Demo")
    db.add(study)
    db.flush()

    for net_name, codes in SEED_CODEBOOK.items():
        net = Net(name=net_name, study_id=study.id)
        db.add(net)
        db.flush()
        for c in codes:
            db.add(Code(name=c["name"], study_id=study.id, net_id=net.id, keywords=c["keywords"]))

    db.commit()
