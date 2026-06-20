import re
import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st
from rapidfuzz import fuzz

DB_PATH = "supplier_master.db"
ASSENT_TEAL = "#00A3A3"
ASSENT_DARK = "#004F59"
ASSENT_BG = "#F7F9FA"
ASSENT_GREEN = "#79B829"
ASSENT_ORANGE = "#F59E0B"
ASSENT_RED = "#DC2626"

COMMON_SUFFIXES = {
    "limited", "ltd", "inc", "incorporated", "corp", "corporation", "company",
    "co", "llc", "plc", "gmbh", "sarl", "sa", "ag", "bv", "pte", "pty",
    "ltda", "private", "holdings", "group", "the"
}

st.set_page_config(page_title="Assent Supplier Master Database", page_icon="🏢", layout="wide")

st.markdown(f"""
<style>
.stApp {{ background: {ASSENT_BG}; }}
.main-header {{ background: linear-gradient(90deg, {ASSENT_DARK}, {ASSENT_TEAL}); padding: 24px 32px; border-radius: 18px; color: white; margin-bottom: 20px; box-shadow: 0 8px 24px rgba(0,0,0,.12); }}
.main-header h1 {{ margin: 0; font-size: 34px; font-weight: 800; }}
.main-header p {{ margin: 6px 0 0 0; font-size: 16px; opacity: .95; }}
.metric-card {{ background: white; padding: 20px; border-radius: 16px; border-left: 6px solid {ASSENT_TEAL}; box-shadow: 0 4px 14px rgba(0,0,0,.06); min-height: 108px; }}
.metric-label {{ color: #5B6770; font-size: 13px; text-transform: uppercase; letter-spacing: .06em; font-weight: 700; }}
.metric-value {{ color: {ASSENT_DARK}; font-size: 34px; font-weight: 800; margin-top: 6px; }}
div[data-testid="stSidebar"] {{ background: white; border-right: 1px solid #E6ECEF; }}
.stButton>button {{ border-radius: 10px; border: 1px solid {ASSENT_TEAL}; background: {ASSENT_TEAL}; color: white; font-weight: 700; }}
.stDownloadButton>button {{ border-radius: 10px; border: 1px solid {ASSENT_DARK}; background: {ASSENT_DARK}; color: white; font-weight: 700; }}
</style>
""", unsafe_allow_html=True)


def connect():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    conn = connect()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS suppliers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        supplier_uid TEXT UNIQUE,
        company_name TEXT NOT NULL,
        normalized_name TEXT NOT NULL,
        dba_name TEXT,
        website TEXT,
        domain TEXT,
        country TEXT,
        address TEXT,
        city TEXT,
        state_region TEXT,
        postal_code TEXT,
        tax_id TEXT,
        registration_number TEXT,
        duns_number TEXT,
        lei_number TEXT,
        status TEXT DEFAULT 'Active',
        source_file TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS import_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_name TEXT,
        uploaded_records INTEGER,
        new_records INTEGER,
        exact_duplicates INTEGER,
        likely_duplicates INTEGER,
        imported_records INTEGER,
        imported_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS duplicate_review (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        upload_batch TEXT,
        uploaded_company_name TEXT,
        uploaded_domain TEXT,
        uploaded_country TEXT,
        uploaded_tax_id TEXT,
        uploaded_registration_number TEXT,
        matched_supplier_id INTEGER,
        matched_company_name TEXT,
        match_type TEXT,
        match_score INTEGER,
        action_taken TEXT DEFAULT 'Pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    for sql in [
        "CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers(company_name);",
        "CREATE INDEX IF NOT EXISTS idx_suppliers_normalized ON suppliers(normalized_name);",
        "CREATE INDEX IF NOT EXISTS idx_suppliers_domain ON suppliers(domain);",
        "CREATE INDEX IF NOT EXISTS idx_suppliers_country ON suppliers(country);",
        "CREATE INDEX IF NOT EXISTS idx_suppliers_tax ON suppliers(tax_id);",
        "CREATE INDEX IF NOT EXISTS idx_suppliers_reg ON suppliers(registration_number);",
        "CREATE INDEX IF NOT EXISTS idx_suppliers_duns ON suppliers(duns_number);",
        "CREATE INDEX IF NOT EXISTS idx_suppliers_lei ON suppliers(lei_number);",
    ]:
        cur.execute(sql)
    conn.commit()
    conn.close()


def normalize_company_name(name):
    if pd.isna(name) or str(name).strip() == "":
        return ""
    value = str(name).lower().strip()
    value = re.sub(r"[^\w\s]", " ", value)
    words = [w for w in value.split() if w not in COMMON_SUFFIXES]
    return " ".join(words).strip()


def normalize_domain(website):
    if pd.isna(website) or str(website).strip() == "":
        return ""
    value = str(website).lower().strip()
    value = value.replace("https://", "").replace("http://", "").replace("www.", "")
    return value.split("/")[0].strip()


def clean_value(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def get_value(row, column):
    if column and column != "Not mapped":
        return clean_value(row.get(column, ""))
    return ""


def make_supplier_uid(name, domain, tax_id, registration_number):
    return str(abs(hash("|".join([normalize_company_name(name), domain or "", tax_id or "", registration_number or ""]))))


@st.cache_data(ttl=30)
def load_supplier_snapshot():
    conn = connect()
    df = pd.read_sql_query("""
        SELECT id, company_name, normalized_name, dba_name, website, domain, country,
               tax_id, registration_number, duns_number, lei_number, status,
               source_file, created_at, updated_at
        FROM suppliers
    """, conn)
    conn.close()
    return df


def detect_duplicate(row_data, existing_df):
    checks = [
        ("tax_id", row_data["tax_id"], "Exact duplicate: Tax ID"),
        ("registration_number", row_data["registration_number"], "Exact duplicate: Registration #"),
        ("duns_number", row_data["duns_number"], "Exact duplicate: DUNS"),
        ("lei_number", row_data["lei_number"], "Exact duplicate: LEI"),
        ("domain", row_data["domain"], "Exact duplicate: Website/domain"),
        ("normalized_name", row_data["normalized_name"], "Exact duplicate: Company name"),
    ]
    for field, value, match_type in checks:
        if value and not existing_df.empty:
            matches = existing_df[existing_df[field].fillna("").astype(str).str.lower() == str(value).lower()]
            if not matches.empty:
                m = matches.iloc[0]
                return "Exact Duplicate", match_type, 100, int(m["id"]), m["company_name"]

    normalized_name = row_data["normalized_name"]
    if normalized_name and not existing_df.empty:
        candidates = existing_df[existing_df["normalized_name"].fillna("").str[:1] == normalized_name[:1]].head(1000)
        best_score, best = 0, None
        for _, cand in candidates.iterrows():
            score = fuzz.token_sort_ratio(normalized_name, cand.get("normalized_name", "") or "")
            if score > best_score:
                best_score, best = score, cand
        if best is not None and best_score >= 88:
            return "Likely Duplicate", "Likely duplicate: Fuzzy company name", int(best_score), int(best["id"]), best["company_name"]

    return "New Supplier", "No strong match", 0, None, ""


def prepare_upload_dataframe(df, mapping):
    rows = []
    for _, row in df.iterrows():
        company_name = get_value(row, mapping["company_name"])
        if not company_name:
            continue
        website = get_value(row, mapping["website"])
        domain = normalize_domain(website)
        data = {
            "company_name": company_name,
            "normalized_name": normalize_company_name(company_name),
            "dba_name": get_value(row, mapping["dba_name"]),
            "website": website,
            "domain": domain,
            "country": get_value(row, mapping["country"]),
            "address": get_value(row, mapping["address"]),
            "city": get_value(row, mapping["city"]),
            "state_region": get_value(row, mapping["state_region"]),
            "postal_code": get_value(row, mapping["postal_code"]),
            "tax_id": get_value(row, mapping["tax_id"]),
            "registration_number": get_value(row, mapping["registration_number"]),
            "duns_number": get_value(row, mapping["duns_number"]),
            "lei_number": get_value(row, mapping["lei_number"]),
        }
        data["supplier_uid"] = make_supplier_uid(data["company_name"], data["domain"], data["tax_id"], data["registration_number"])
        rows.append(data)
    return pd.DataFrame(rows)


def insert_new_suppliers(new_df, source_file):
    if new_df.empty:
        return 0
    conn = connect()
    inserted = 0
    for _, row in new_df.iterrows():
        before = conn.total_changes
        conn.execute("""
            INSERT OR IGNORE INTO suppliers (
                supplier_uid, company_name, normalized_name, dba_name, website, domain,
                country, address, city, state_region, postal_code, tax_id,
                registration_number, duns_number, lei_number, source_file
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row["supplier_uid"], row["company_name"], row["normalized_name"], row["dba_name"], row["website"], row["domain"],
            row["country"], row["address"], row["city"], row["state_region"], row["postal_code"], row["tax_id"],
            row["registration_number"], row["duns_number"], row["lei_number"], source_file
        ))
        if conn.total_changes > before:
            inserted += 1
    conn.commit()
    conn.close()
    load_supplier_snapshot.clear()
    return inserted


def save_duplicate_review(review_df, batch_name):
    if review_df.empty:
        return
    conn = connect()
    for _, row in review_df.iterrows():
        conn.execute("""
            INSERT INTO duplicate_review (
                upload_batch, uploaded_company_name, uploaded_domain, uploaded_country,
                uploaded_tax_id, uploaded_registration_number, matched_supplier_id,
                matched_company_name, match_type, match_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            batch_name, row.get("company_name", ""), row.get("domain", ""), row.get("country", ""),
            row.get("tax_id", ""), row.get("registration_number", ""), row.get("matched_supplier_id", None),
            row.get("matched_company_name", ""), row.get("match_type", ""), int(row.get("match_score", 0))
        ))
    conn.commit()
    conn.close()


def update_import_history(file_name, uploaded, new_count, exact_count, likely_count, imported):
    conn = connect()
    conn.execute("""
        INSERT INTO import_history (file_name, uploaded_records, new_records, exact_duplicates, likely_duplicates, imported_records)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (file_name, uploaded, new_count, exact_count, likely_count, imported))
    conn.commit()
    conn.close()


def metric_card(label, value):
    st.markdown(f"""
    <div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div></div>
    """, unsafe_allow_html=True)


def csv_download(df):
    return df.to_csv(index=False).encode("utf-8")


init_db()

st.markdown("""
<div class="main-header">
<h1>Assent Supplier Master Database</h1>
<p>Upload, search, review duplicates, and manage supplier/company records in one place.</p>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### Assent Supplier Database")
    page = st.radio("Navigation", ["Dashboard", "Upload Suppliers", "Duplicate Review", "Search Database", "All Suppliers", "Import History"], label_visibility="collapsed")
    st.markdown("---")
    st.caption("Supplier/company master-data management")

if page == "Dashboard":
    conn = connect()
    total = pd.read_sql_query("SELECT COUNT(*) AS n FROM suppliers", conn)["n"][0]
    dup_pending = pd.read_sql_query("SELECT COUNT(*) AS n FROM duplicate_review WHERE action_taken='Pending'", conn)["n"][0]
    imports = pd.read_sql_query("SELECT COUNT(*) AS n FROM import_history", conn)["n"][0]
    recent = pd.read_sql_query("SELECT company_name, country, domain, source_file, created_at FROM suppliers ORDER BY id DESC LIMIT 12", conn)
    conn.close()
    c1, c2, c3, c4 = st.columns(4)
    with c1: metric_card("Total Suppliers", f"{total:,}")
    with c2: metric_card("Pending Duplicates", f"{dup_pending:,}")
    with c3: metric_card("CSV Imports", f"{imports:,}")
    with c4: metric_card("Capacity Target", "200k+")
    st.markdown("### Recently Added Suppliers")
    st.dataframe(recent, use_container_width=True, hide_index=True)

elif page == "Upload Suppliers":
    st.markdown("### Upload supplier CSV")
    st.info("Upload your file, map columns, preview duplicate results, then import only the new suppliers.")
    uploaded = st.file_uploader("Upload CSV", type=["csv"])
    if uploaded:
        try:
            raw_df = pd.read_csv(uploaded)
        except UnicodeDecodeError:
            uploaded.seek(0)
            raw_df = pd.read_csv(uploaded, encoding="latin-1")
        st.markdown("#### Uploaded file preview")
        st.dataframe(raw_df.head(50), use_container_width=True, hide_index=True)
        columns = ["Not mapped"] + list(raw_df.columns)
        with st.expander("Map columns", expanded=True):
            c1, c2, c3 = st.columns(3)
            with c1:
                company_col = st.selectbox("Company name", columns, index=1 if len(columns) > 1 else 0)
                dba_col = st.selectbox("DBA / alternate name", columns)
                website_col = st.selectbox("Website", columns)
                country_col = st.selectbox("Country", columns)
            with c2:
                address_col = st.selectbox("Address", columns)
                city_col = st.selectbox("City", columns)
                state_col = st.selectbox("State/Region", columns)
                postal_col = st.selectbox("Postal code", columns)
            with c3:
                tax_col = st.selectbox("Tax ID", columns)
                reg_col = st.selectbox("Registration number", columns)
                duns_col = st.selectbox("DUNS number", columns)
                lei_col = st.selectbox("LEI number", columns)
        mapping = {"company_name": company_col, "dba_name": dba_col, "website": website_col, "country": country_col, "address": address_col, "city": city_col, "state_region": state_col, "postal_code": postal_col, "tax_id": tax_col, "registration_number": reg_col, "duns_number": duns_col, "lei_number": lei_col}
        if company_col == "Not mapped":
            st.warning("Please map the company name column.")
        elif st.button("Analyze duplicates before import"):
            prepared = prepare_upload_dataframe(raw_df, mapping)
            existing = load_supplier_snapshot()
            rows = []
            progress = st.progress(0)
            for i, row in prepared.iterrows():
                classification, match_type, match_score, matched_id, matched_name = detect_duplicate(row, existing)
                combined = row.to_dict()
                combined.update({"classification": classification, "match_type": match_type, "match_score": match_score, "matched_supplier_id": matched_id, "matched_company_name": matched_name})
                rows.append(combined)
                if len(prepared) > 0 and i % 100 == 0:
                    progress.progress(min((i + 1) / len(prepared), 1.0))
            progress.progress(1.0)
            st.session_state["upload_results"] = pd.DataFrame(rows)
            st.session_state["upload_file_name"] = uploaded.name

        if "upload_results" in st.session_state:
            results_df = st.session_state["upload_results"]
            new_count = int((results_df["classification"] == "New Supplier").sum())
            exact_count = int((results_df["classification"] == "Exact Duplicate").sum())
            likely_count = int((results_df["classification"] == "Likely Duplicate").sum())
            c1, c2, c3, c4 = st.columns(4)
            with c1: metric_card("Uploaded Records", f"{len(results_df):,}")
            with c2: metric_card("New Suppliers", f"{new_count:,}")
            with c3: metric_card("Exact Duplicates", f"{exact_count:,}")
            with c4: metric_card("Likely Duplicates", f"{likely_count:,}")
            display_cols = ["classification", "company_name", "country", "domain", "tax_id", "registration_number", "matched_company_name", "match_type", "match_score"]
            st.markdown("#### Duplicate analysis")
            st.dataframe(results_df[display_cols], use_container_width=True, hide_index=True)
            st.download_button("Download duplicate analysis", csv_download(results_df[display_cols]), file_name="supplier_duplicate_analysis.csv", mime="text/csv")
            import_choice = st.radio("Import decision", ["Import only new suppliers", "Import new suppliers and likely duplicates as new records", "Cancel import"])
            if st.button("Confirm import"):
                if import_choice == "Cancel import":
                    st.warning("Import cancelled.")
                else:
                    if import_choice == "Import only new suppliers":
                        to_import = results_df[results_df["classification"] == "New Supplier"]
                    else:
                        to_import = results_df[results_df["classification"].isin(["New Supplier", "Likely Duplicate"])]
                    imported = insert_new_suppliers(to_import, st.session_state.get("upload_file_name", uploaded.name))
                    dup_df = results_df[results_df["classification"].isin(["Exact Duplicate", "Likely Duplicate"])]
                    save_duplicate_review(dup_df, st.session_state.get("upload_file_name", uploaded.name))
                    update_import_history(st.session_state.get("upload_file_name", uploaded.name), len(results_df), new_count, exact_count, likely_count, imported)
                    st.success(f"Import complete. {imported:,} supplier records added.")

elif page == "Duplicate Review":
    st.markdown("### Duplicate Review Center")
    conn = connect()
    review = pd.read_sql_query("SELECT id, upload_batch, uploaded_company_name, uploaded_country, uploaded_domain, matched_supplier_id, matched_company_name, match_type, match_score, action_taken, created_at FROM duplicate_review ORDER BY created_at DESC LIMIT 1000", conn)
    conn.close()
    if review.empty:
        st.success("No duplicate records are currently waiting for review.")
    else:
        metric_card("Pending Duplicate Reviews", f"{int((review['action_taken'] == 'Pending').sum()):,}")
        st.dataframe(review, use_container_width=True, hide_index=True)
        st.download_button("Export duplicate review list", csv_download(review), file_name="duplicate_review.csv", mime="text/csv")

elif page == "Search Database":
    st.markdown("### Search supplier database")
    query = st.text_input("Search by company, DBA, domain, website, country, tax ID, registration #, DUNS, or LEI")
    if query:
        conn = connect()
        like = f"%{query}%"
        exact_domain = normalize_domain(query)
        exact_name = normalize_company_name(query)
        results = pd.read_sql_query("""
            SELECT id, company_name, dba_name, country, website, domain, tax_id, registration_number, duns_number, lei_number, status, source_file, updated_at
            FROM suppliers
            WHERE company_name LIKE ? OR dba_name LIKE ? OR normalized_name LIKE ? OR website LIKE ? OR domain LIKE ? OR country LIKE ? OR tax_id LIKE ? OR registration_number LIKE ? OR duns_number LIKE ? OR lei_number LIKE ?
            ORDER BY CASE WHEN domain = ? THEN 0 WHEN normalized_name = ? THEN 1 ELSE 2 END, company_name
            LIMIT 1000
        """, conn, params=[like, like, like, like, like, like, like, like, like, like, exact_domain, exact_name])
        conn.close()
        st.write(f"Found **{len(results):,}** matching records.")
        st.dataframe(results, use_container_width=True, hide_index=True)
        st.download_button("Export search results", csv_download(results), file_name="supplier_search_results.csv", mime="text/csv")

elif page == "All Suppliers":
    st.markdown("### All supplier records")
    conn = connect()
    total = pd.read_sql_query("SELECT COUNT(*) AS n FROM suppliers", conn)["n"][0]
    suppliers = pd.read_sql_query("SELECT id, company_name, dba_name, country, website, domain, tax_id, registration_number, duns_number, lei_number, status, source_file, created_at, updated_at FROM suppliers ORDER BY id DESC LIMIT 2000", conn)
    conn.close()
    st.caption(f"Showing latest 2,000 of {total:,} records.")
    st.dataframe(suppliers, use_container_width=True, hide_index=True)
    st.download_button("Export displayed suppliers", csv_download(suppliers), file_name="supplier_records.csv", mime="text/csv")

elif page == "Import History":
    st.markdown("### Import history")
    conn = connect()
    history = pd.read_sql_query("SELECT file_name, uploaded_records, new_records, exact_duplicates, likely_duplicates, imported_records, imported_at FROM import_history ORDER BY imported_at DESC", conn)
    conn.close()
    st.dataframe(history, use_container_width=True, hide_index=True)
