"""C3 — Streamlit UI + dashboard (OWNER: cursor).

Glues the cursor lane together:

    upload survey -> (discovery) -> review candidates -> approve products/aliases
                  -> classify answers -> per-round dashboard

The discovery lane (``src/discovery/*``, owned by opencode) is imported
defensively: if it is not ready yet, the UI still runs and you can review any
candidates already persisted in the catalog and classify answers.

Run:
    streamlit run src/ui/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Make ``src`` importable when launched via ``streamlit run src/ui/app.py``.
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from catalog.store import CatalogStore  # noqa: E402
from classification.classifier import Classifier  # noqa: E402

DB_PATH = str(_SRC.parent / "data" / "catalog.sqlite")


def _discovery():
    """Return the opencode discovery entrypoint, or ``None`` if not ready yet.

    Expected (eventual) contract:
        discovery.discover(df, answer_column, round_name) -> list[dict]
        where each dict has term/frequency/document_frequency/ngram.
    """
    try:
        import discovery  # type: ignore

        return getattr(discovery, "discover", None)
    except Exception:
        return None


@st.cache_resource
def get_store() -> CatalogStore:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    return CatalogStore(DB_PATH)


def page_upload(store: CatalogStore) -> None:
    st.header("1. Upload & discover")
    discover = _discovery()
    if discover is None:
        st.warning(
            "No se pudo cargar `discovery.discover`. Instala dependencias "
            "(`pip install -r requirements.txt`) y reinicia Streamlit."
        )
    file = st.file_uploader("Survey Excel (.xlsx / .xls)", type=["xlsx", "xls"])
    if not file:
        return
    try:
        import pandas as pd

        df = pd.read_excel(file)
    except Exception as exc:  # pragma: no cover - UI feedback path
        st.error(f"Could not read Excel: {exc}")
        return

    st.write("Preview:", df.head())
    answer_col = st.selectbox("Open-answer column", list(df.columns))
    round_name = st.text_input("Round name", value=file.name.rsplit(".", 1)[0])

    if st.button("Run discovery", disabled=discover is None):
        round_id = store.add_round(round_name)
        rows = discover(df, answer_col, round_name)  # type: ignore[misc]
        n = store.bulk_add_candidates(rows, round_id=round_id)
        st.success(f"Stored {n} candidates for round '{round_name}'.")


def page_review(store: CatalogStore) -> None:
    st.header("2. Review candidates")
    pending = store.list_candidates(status="pending_review")
    if not pending:
        st.success("No candidates pending review.")
        return

    products = store.list_products()
    product_labels = {p.name: p.id for p in products}

    for cand in pending:
        with st.container(border=True):
            st.markdown(
                f"**{cand.term}**  ·  freq={cand.frequency}  ·  "
                f"df={cand.document_frequency}  ·  {cand.ngram}-gram"
            )
            cols = st.columns(4)
            if cols[0].button("New product", key=f"np-{cand.id}"):
                store.approve_candidate_as_product(cand.id)
                _rerun()
            if cols[1].button("Reject (noise)", key=f"rj-{cand.id}"):
                store.reject_candidate(cand.id)
                _rerun()
            if cols[2].button("Ambiguous", key=f"am-{cand.id}"):
                store.mark_candidate_ambiguous(cand.id)
                _rerun()
            if product_labels:
                target = cols[3].selectbox(
                    "alias of…",
                    ["—"] + list(product_labels),
                    key=f"al-{cand.id}",
                )
                if target != "—" and cols[3].button("Link alias", key=f"lk-{cand.id}"):
                    store.approve_candidate_as_alias(cand.id, product_labels[target])
                    _rerun()


def page_classify(store: CatalogStore) -> None:
    st.header("3. Classify answers")
    clf = Classifier(store.alias_map())
    st.caption(f"matcher: {clf.matcher} · products: {len(store.list_products())}")

    text = st.text_area("Paste answers (one per line)")
    if st.button("Classify") and text.strip():
        import pandas as pd

        results = []
        for line in text.splitlines():
            if not line.strip():
                continue
            m = clf.classify(line)
            results.append(
                {
                    "answer": line,
                    "product": m.product or "—",
                    "method": m.method,
                    "confidence": m.confidence,
                    "status": m.status,
                }
            )
        st.dataframe(pd.DataFrame(results), use_container_width=True)


def page_dashboard(store: CatalogStore) -> None:
    st.header("4. Catalog dashboard")
    entries = store.catalog()
    if not entries:
        st.info("Catalog is empty — approve some candidates first.")
        return
    import pandas as pd

    table = pd.DataFrame(
        [{"product": e.product, "aliases": len(e.aliases)} for e in entries]
    ).sort_values("aliases", ascending=False)
    st.metric("Products", len(entries))
    st.metric("Aliases", int(table["aliases"].sum()))
    st.bar_chart(table.set_index("product")["aliases"])
    st.dataframe(table, use_container_width=True)


def _rerun() -> None:
    # Streamlit renamed the API across versions.
    getattr(st, "rerun", getattr(st, "experimental_rerun", lambda: None))()


def main() -> None:
    st.set_page_config(page_title="classification-app", layout="wide")
    st.title("Product discovery & classification")
    store = get_store()
    page = st.sidebar.radio(
        "Step",
        ["Upload & discover", "Review candidates", "Classify", "Dashboard"],
    )
    if page == "Upload & discover":
        page_upload(store)
    elif page == "Review candidates":
        page_review(store)
    elif page == "Classify":
        page_classify(store)
    else:
        page_dashboard(store)


if __name__ == "__main__":
    main()
