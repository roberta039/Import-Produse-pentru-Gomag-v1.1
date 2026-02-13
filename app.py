import os
import tempfile
def _secret_get(path, default=None):
    """Read secrets by trying multiple formats.
    path can be tuple for nested keys, or string for top-level key.
    """
    # st.secrets nested
    try:
        if isinstance(path, tuple):
            cur = st.secrets
            for p in path:
                if p in cur:
                    cur = cur[p]
                else:
                    return default
            return cur
        else:
            return st.secrets.get(path, default)
    except Exception:
        return default


def _get_gomag_creds():
    # Preferred (legacy in this project): [GOMAG] BASE_URL/USERNAME/PASSWORD
    base_url = _secret_get(("GOMAG", "BASE_URL")) or _secret_get("GOMAG_BASE_URL") or _secret_get(("gomag", "base_url"))
    email = _secret_get(("GOMAG", "USERNAME")) or _secret_get("GOMAG_EMAIL") or _secret_get(("gomag", "email"))
    password = _secret_get(("GOMAG", "PASSWORD")) or _secret_get("GOMAG_PASSWORD") or _secret_get(("gomag", "password"))

    # Some users used keys email/password under [GOMAG]
    if not email:
        email = _secret_get(("GOMAG", "EMAIL"))
    if not password:
        password = _secret_get(("GOMAG", "PASS")) or _secret_get(("GOMAG", "PAROLA"))

    base_url = (str(base_url).strip() if base_url else "")
    email = (str(email).strip() if email else "")
    password = (str(password).strip() if password else "")

    if not (base_url and email and password):
        return None

    # IMPORTANT: gomag_ui.py expects GomagCreds(base_url, email, password)
    return GomagCreds(base_url=base_url, email=email, password=password)

import pandas as pd
import streamlit as st

from src.export_gomag import save_xlsx, to_gomag_dataframe
from src.gomag_ui import GomagCreds, fetch_categories, import_file
from src.pipeline import scrape_products
from src.utils import detect_url_column

# --- Load source-site creds into env (used by scrapers) ---
try:
    os.environ["PSI_USER"] = str(st.secrets.get("SOURCES", {}).get("PSI_USER", "")).strip()
    os.environ["PSI_PASS"] = str(st.secrets.get("SOURCES", {}).get("PSI_PASS", "")).strip()
    os.environ["XD_USER"] = str(st.secrets.get("SOURCES", {}).get("XD_USER", "")).strip()
    os.environ["XD_PASS"] = str(st.secrets.get("SOURCES", {}).get("XD_PASS", "")).strip()
except Exception:
    pass

st.set_page_config(page_title="Gomag Importer", layout="wide")

# =====================
# Debug artifacts panel (sidebar)
# =====================
with st.sidebar.expander("Debug (download artifacts)", expanded=False):
    dbg_dir = "debug_artifacts"
    if os.path.isdir(dbg_dir):
        files = sorted([f for f in os.listdir(dbg_dir) if os.path.isfile(os.path.join(dbg_dir, f))])
        if not files:
            st.info("Nu exista fisiere in debug_artifacts/.")
        else:
            st.write(f"Gasite {len(files)} fisiere in {dbg_dir}/")
            for fn in files:
                path = os.path.join(dbg_dir, fn)
                try:
                    with open(path, "rb") as fh:
                        data = fh.read()
                    mime = "application/octet-stream"
                    if fn.lower().endswith(".html"):
                        mime = "text/html"
                    elif fn.lower().endswith(".png"):
                        mime = "image/png"
                    elif fn.lower().endswith(".txt"):
                        mime = "text/plain"
                    st.download_button(
                        label=f"Download {fn}",
                        data=data,
                        file_name=fn,
                        mime=mime,
                        key=f"dl_{fn}",
                    )
                except Exception as e:
                    st.error(f"Nu pot citi {fn}: {e}")
    else:
        st.info("Folderul debug_artifacts/ nu exista (inca). Dupa o rulare, vor aparea aici fisierele.")

st.title("Import produse in Gomag")
st.caption("Flux: Excel -> preluare date -> tabel intermediar -> genereaza XLSX import -> (optional) browser automation import in Gomag")

with st.sidebar:
    st.divider()
    st.header("Gomag")
    gomag_enabled = st.checkbox("Activeaza conectare Gomag (Playwright)", value=False)
    if gomag_enabled:
    try:
    creds = _get_gomag_creds()
    if creds is None:
        raise RuntimeError("missing")
    st.success("Secrets Gomag incarcate.")
    except Exception:
    creds = None
    st.error("Lipsesc secrets Gomag. Completeaza in Streamlit Cloud -> Settings -> Secrets.")
    else:
        creds = None

    st.subheader("1) Incarca Excel cu link-uri")
    uploaded = st.file_uploader("Excel (.xlsx)", type=["xlsx"])

    if "drafts" not in st.session_state:
    st.session_state["drafts"] = []
    if "df_edit" not in st.session_state:
    st.session_state["df_edit"] = None
    if "categories" not in st.session_state:
    st.session_state["categories"] = []

    if uploaded:
    df = pd.read_excel(uploaded)
    url_col = detect_url_column(df.columns)
    if not url_col:
        st.error("Nu am gasit coloana URL. Foloseste una din: url / link / product_url")
        st.stop()

    urls = df[url_col].dropna().astype(str).tolist()
    st.write(f"Gasite **{len(urls)}** link-uri in coloana **{url_col}**.")
    st.dataframe(df.head(20), use_container_width=True)

    colA, colB = st.columns([1, 1])
    with colA:
        if st.button("2) Preia date din link-uri", type="primary"):
            with st.spinner("Scrape in curs (poate dura)..."):
                drafts = scrape_products(urls)
            st.session_state["drafts"] = drafts
            st.success(f"Am preluat {len(drafts)} produse.")
    with colB:
        if creds and st.button("Incarca categorii din Gomag"):
            with st.spinner("Citesc categoriile din Gomag..."):
                try:
                    cats = fetch_categories(creds)
                    st.session_state["categories"] = cats
                    st.success(f"Gasite {len(cats)} categorii.")
                except Exception as e:
                    st.error(f"Eroare la citire categorii: {e}")

    drafts = st.session_state.get("drafts", [])
    if drafts:
    st.subheader("3) Tabel intermediar (verifica / corecteaza)")
    df_products = pd.DataFrame(drafts)
    st.session_state["df_edit"] = st.data_editor(df_products, use_container_width=True, num_rows="dynamic")

    st.subheader("4) Genereaza fisier import Gomag")
    df_final = st.session_state["df_edit"] if st.session_state.get("df_edit") is not None else df_products
    gomag_df = to_gomag_dataframe(df_final, categories=st.session_state.get("categories", []))

    st.dataframe(gomag_df.head(50), use_container_width=True)

    tmpdir = tempfile.mkdtemp()
    out_xlsx = os.path.join(tmpdir, "gomag_import.xlsx")
    save_xlsx(gomag_df, out_xlsx)

    with open(out_xlsx, "rb") as f:
        st.download_button("Descarca XLSX pentru Gomag", f, file_name="gomag_import.xlsx")

    if creds:
        st.subheader("5) Import in Gomag (browser automation)")
        if st.button("Import in Gomag acum", type="primary"):
            with st.spinner("Incarc fisierul si pornesc importul in Gomag..."):
                msg = import_file(creds, out_xlsx)
            st.success(msg)
