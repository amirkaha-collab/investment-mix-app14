# -*- coding: utf-8 -*-
import math
import re
import hmac
import pandas as pd
import numpy as np
import streamlit as st

# -----------------------------
# Page config
# -----------------------------
st.set_page_config(
    page_title="מנוע תמהילי קרנות השתלמות",
    page_icon="📊",
    layout="wide",
)

# -----------------------------
# RTL + Theme (desktop light, mobile dark) + UI polish
# -----------------------------
st.markdown(
    """
<style>
/* RTL base */
html, body, [class*="css"]  { direction: rtl; text-align: right; }

/* Make tabs RTL */
div[data-baseweb="tab-list"] { direction: rtl; }

/* Wide layout padding */
.block-container { padding-top: 1.2rem; padding-bottom: 2rem; }

/* KPI cards */
.kpi-wrap { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.kpi {
  border-radius: 16px;
  padding: 14px 16px;
  border: 1px solid rgba(0,0,0,0.10);
  background: rgba(255,255,255,0.92);
}
.kpi h4 { margin: 0 0 6px 0; font-size: 0.95rem; opacity: 0.9; }
.kpi .big { font-size: 1.35rem; font-weight: 700; line-height: 1.2; }
.kpi .sub { margin-top: 6px; font-size: 0.9rem; opacity: 0.85; }

/* Table: widen name columns and reduce row height a bit */
div[data-testid="stDataFrame"] { direction: rtl; }
div[data-testid="stDataFrame"] .stDataFrame { direction: rtl; }
table { direction: rtl; }
thead tr th { text-align: right !important; }
tbody tr td { text-align: right !important; }

/* Slider tick labels visibility */
div[data-testid="stSlider"] label { font-weight: 600; }

/* Mobile dark mode */
@media (max-width: 768px) {
  body { background: #0b0f14; color: #e6edf3; }
  .kpi { background: rgba(16, 23, 33, 0.92); border: 1px solid rgba(255,255,255,0.10); }
  .stMarkdown, .stText, .stCaption, .stAlert, label, p, span, div { color: #e6edf3 !important; }
  /* Inputs */
  input, textarea { background: #121a24 !important; color: #e6edf3 !important; }
}
</style>
""",
    unsafe_allow_html=True,
)

# -----------------------------
# Helpers
# -----------------------------
CANON = {
    "stocks": "מניות",
    "foreign": "חו״ל",
    "fx": "מט״ח",
    "illiquid": "לא סחיר",
    "sharpe": "שארפ",
    "israel": "ישראל",
}

PARAM_ALIASES = {
    "stocks": [r"חשיפה\s*למניות", r"סך\s*חשיפה\s*למניות"],
    "foreign": [r"מושקעים\s*בחו\"ל", r"בחו\"ל", r"חשיפה\s*לחו\"ל"],
    "illiquid": [r"לא\s*סחיר", r"נכסים\s*לא\s*סחירים"],
    "fx": [r"מט\"ח", r"חשיפה\s*למט\"ח"],
    "sharpe": [r"שארפ", r"Sharpe"],
    # "israel" is computed by rule
}

def parse_pct(x):
    """Convert cell to float percentage (0-100)."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    s = str(x).strip()
    s = s.replace(",", "")
    if s.endswith("%"):
        s = s[:-1].strip()
    # handle weird minus sign
    s = s.replace("−", "-")
    try:
        return float(s)
    except:
        return np.nan

def normalize_param_name(param):
    s = str(param).strip()
    for key, pats in PARAM_ALIASES.items():
        for p in pats:
            if re.search(p, s):
                return key
    # fallback
    return None

def extract_manager_name(col_name: str) -> str:
    s = str(col_name).strip()
    # Prefer split by "קרן השתלמות"
    if "קרן השתלמות" in s:
        left = s.split("קרן השתלמות")[0].strip()
        return left if left else s
    # Else split by "השתלמות"
    if "השתלמות" in s:
        left = s.split("השתלמות")[0].strip()
        return left if left else s
    # Otherwise first 2 words
    parts = s.split()
    return " ".join(parts[:2]) if parts else s

def load_holdings_excel(file) -> tuple[pd.DataFrame, list[str]]:
    """Return long dataframe with one row per (sheet, fund column) and canonical metrics."""
    xl = pd.ExcelFile(file)
    sheets = xl.sheet_names
    rows = []
    for sh in sheets:
        df = xl.parse(sh)
        if df.empty:
            continue
        # Find the parameter column: usually first column named 'פרמטר'
        param_col = None
        for c in df.columns:
            if str(c).strip() == "פרמטר":
                param_col = c
                break
        if param_col is None:
            # try first column
            param_col = df.columns[0]
        # map row index to canonical param key
        param_keys = df[param_col].apply(normalize_param_name)
        # Build a mapping canonical -> row index
        idx_map = {}
        for i, k in enumerate(param_keys.tolist()):
            if k and k not in idx_map:
                idx_map[k] = i
        # We require at least foreign and illiquid to be meaningful
        if "foreign" not in idx_map or "illiquid" not in idx_map:
            continue

        for c in df.columns:
            if c == param_col:
                continue
            series = df[c]
            rec = {
                "sheet": sh,
                "fund_name": str(c).strip(),
                "manager": extract_manager_name(c),
                "stocks": parse_pct(series.iloc[idx_map["stocks"]]) if "stocks" in idx_map else np.nan,
                "foreign": parse_pct(series.iloc[idx_map["foreign"]]) if "foreign" in idx_map else np.nan,
                "illiquid": parse_pct(series.iloc[idx_map["illiquid"]]) if "illiquid" in idx_map else np.nan,
                "fx": parse_pct(series.iloc[idx_map["fx"]]) if "fx" in idx_map else np.nan,
                "sharpe": parse_pct(series.iloc[idx_map["sharpe"]]) if "sharpe" in idx_map else np.nan,
            }
            # Israel rule (computed)
            if not np.isnan(rec["foreign"]):
                rec["israel"] = 100.0 - rec["foreign"]
            else:
                rec["israel"] = np.nan
            # Keep only rows with some numeric content
            if all(np.isnan(rec[k]) for k in ["stocks","foreign","illiquid","fx","sharpe"]):
                continue
            rows.append(rec)

    out = pd.DataFrame(rows)
    # standardize to numeric
    for k in ["stocks","foreign","illiquid","fx","sharpe","israel"]:
        if k in out.columns:
            out[k] = pd.to_numeric(out[k], errors="coerce")
    return out, sheets

def load_service_scores_excel(file) -> dict:
    """Return mapping manager -> service score (0-100)."""
    df = pd.read_excel(file)
    if df.empty:
        return {}
    # Try to detect columns
    cols = [str(c).strip() for c in df.columns]
    manager_col = None
    score_col = None
    for c in cols:
        if "מנהל" in c or "גוף" in c or "חברה" in c:
            manager_col = c
            break
    for c in cols:
        if "שירות" in c or "ציון" in c or "score" in c.lower():
            score_col = c
            break
    if manager_col is None:
        manager_col = cols[0]
    if score_col is None:
        score_col = cols[1] if len(cols) > 1 else cols[0]
    df2 = df.rename(columns={manager_col: "manager", score_col: "service"})
    df2["manager"] = df2["manager"].astype(str).str.strip()
    df2["service"] = df2["service"].apply(lambda x: float(x) if pd.notna(x) else np.nan)
    scores = {}
    for _, r in df2.iterrows():
        if pd.isna(r["service"]):
            continue
        scores[str(r["manager"]).strip()] = float(r["service"])
    return scores

def default_service_scores(managers: list[str]) -> dict:
    # Placeholder: everyone 50 unless defined
    return {m: 50.0 for m in managers}

def score_combo(metrics: dict, targets: dict, objective: str, service_score: float) -> float:
    """
    Lower is better for 'דיוק' score, higher is better for 'שארפ'/'שירות'/'מקסום מט״ח'
    We return a unified 'primary_score' where lower is better by negating where needed.
    """
    if objective == "דיוק":
        # L1 distance on selected targets
        dist = 0.0
        for k, t in targets.items():
            if t is None or math.isnan(t):
                continue
            v = metrics.get(k, np.nan)
            if np.isnan(v):
                dist += 9999.0
            else:
                dist += abs(v - t)
        return dist
    if objective == "שארפ":
        v = metrics.get("sharpe", np.nan)
        return -(v if not np.isnan(v) else -9999.0)
    if objective == "שירות":
        return -(service_score if not np.isnan(service_score) else -9999.0)
    if objective == "מקסום מט״ח":
        v = metrics.get("fx", np.nan)
        return -(v if not np.isnan(v) else -9999.0)
    # fallback
    return 0.0

def weighted_metrics(rows: list[dict], weights: list[float]) -> dict:
    m = {}
    keys = ["stocks","foreign","israel","fx","illiquid","sharpe"]
    w = np.array(weights, dtype=float)
    w = w / w.sum()
    for k in keys:
        vals = np.array([r.get(k, np.nan) for r in rows], dtype=float)
        if np.all(np.isnan(vals)):
            m[k] = np.nan
        else:
            # nan-safe weighted mean: ignore nan by renormalizing
            mask = ~np.isnan(vals)
            if mask.sum() == 0:
                m[k] = np.nan
            else:
                ww = w[mask]
                ww = ww / ww.sum()
                m[k] = float(np.sum(vals[mask] * ww))
    return m

def weighted_service(managers: list[str], weights: list[float], service_scores: dict) -> float:
    w = np.array(weights, dtype=float)
    w = w / w.sum()
    vals = np.array([service_scores.get(m, np.nan) for m in managers], dtype=float)
    mask = ~np.isnan(vals)
    if mask.sum() == 0:
        return np.nan
    ww = w[mask]
    ww = ww / ww.sum()
    return float(np.sum(vals[mask] * ww))

def generate_weights(n: int, step: int):
    """Generate weights that sum to 100 with given step."""
    step = int(step)
    if n == 1:
        yield (100,)
        return
    if n == 2:
        for a in range(0, 101, step):
            yield (a, 100 - a)
        return
    # n == 3
    for a in range(0, 101, step):
        for b in range(0, 101 - a, step):
            c = 100 - a - b
            if c < 0:
                continue
            if c % step != 0:
                continue
            yield (a, b, c)

def find_best_solutions(
    df_long: pd.DataFrame,
    n_funds: int,
    step: int,
    manager_mode: str,
    objective: str,
    targets: dict,
    max_illiquid: float,
    service_scores: dict,
    exclude_managers: set[str] | None = None,
    top_k: int = 2000,
):
    """
    Brute force search (stable/יסודי).
    Returns list of candidate dicts sorted by primary objective.
    """
    exclude_managers = exclude_managers or set()
    items = df_long.copy()
    items = items[~items["manager"].isin(exclude_managers)].reset_index(drop=True)

    # Remove rows without required metrics for targets if targets provided
    # but we still keep wide; scoring penalizes missing.

    records = items.to_dict("records")
    candidates = []

    # choose combos
    # For stability, we iterate deterministically
    for combo_idx in itertools.combinations(range(len(records)), n_funds):
        rows = [records[i] for i in combo_idx]
        managers = [r["manager"] for r in rows]

        if manager_mode == "פיזור בין מנהלים":
            if len(set(managers)) != n_funds:
                continue
        else:  # same manager only
            if len(set(managers)) != 1:
                continue

        for wts in generate_weights(n_funds, step):
            if sum(wts) != 100:
                continue
            # quick prune: if all weight on missing? no

            metrics = weighted_metrics(rows, list(wts))
            ill = metrics.get("illiquid", np.nan)
            if not np.isnan(max_illiquid) and not np.isnan(ill) and ill > max_illiquid + 1e-9:
                continue

            s_service = weighted_service(managers, list(wts), service_scores)
            primary = score_combo(metrics, targets, objective, s_service)

            # Compute accuracy score always (for KPI)
            acc = score_combo(metrics, targets, "דיוק", s_service)

            candidates.append({
                "rows": rows,
                "weights": list(wts),
                "metrics": metrics,
                "service": s_service,
                "primary_score": primary,
                "accuracy_score": acc,
            })

    # Sort by objective: primary_score is already "lower is better"
    candidates.sort(key=lambda x: x["primary_score"])
    return candidates[:top_k]

def pick_distinct_manager_solution(cands, used_managers: set[str]):
    for c in cands:
        mans = {r["manager"] for r in c["rows"]}
        if mans.isdisjoint(used_managers):
            return c
    return None

def format_solution_row(sol, rank_label: str, objective_name: str):
    rows = sol["rows"]
    wts = sol["weights"]
    metrics = sol["metrics"]
    managers = [r["manager"] for r in rows]
    funds = [r["fund_name"] for r in rows]
    sheets = [r["sheet"] for r in rows]
    combo_txt = " + ".join([f"{wts[i]}% • {funds[i]} ({sheets[i]})" for i in range(len(rows))])
    managers_txt = " + ".join([f"{wts[i]}% • {managers[i]}" for i in range(len(rows))])

    return {
        "דירוג": rank_label,
        "אובייקטיב": objective_name,
        "שילוב (מסלול/קופה)": combo_txt,
        "מנהלים": managers_txt,
        "חו״ל": metrics.get("foreign", np.nan),
        "ישראל": metrics.get("israel", np.nan),
        "מניות": metrics.get("stocks", np.nan),
        "מט״ח": metrics.get("fx", np.nan),
        "לא סחיר": metrics.get("illiquid", np.nan),
        "שארפ": metrics.get("sharpe", np.nan),
        "ציון שירות": sol.get("service", np.nan),
        "Score סטייה": sol.get("accuracy_score", np.nan),
    }

def advantage_text(sol, kind: str, best_acc: float):
    acc = sol.get("accuracy_score", np.nan)
    sharpe = sol["metrics"].get("sharpe", np.nan)
    svc = sol.get("service", np.nan)
    if kind == "primary":
        return f"הכי מדויק ליעד, סטייה כוללת {acc:.2f}"
    if kind == "sharpe":
        # delta sharpe is relative to primary, we can mention
        return f"שארפ משוקלל גבוה, סטייה כוללת {acc:.2f}"
    if kind == "service":
        return f"ציון שירות משוקלל הגבוה ביותר, סטייה כוללת {acc:.2f}"
    return ""

def color_row(row, best_row_idx: int, illiquid_limit: float, high_dev: float):
    styles = [""] * len(row)
    # Row-level highlighting by rank is handled in dataframe styling
    return styles

def style_results_df(df: pd.DataFrame, illiquid_limit: float, dev_warn: float, best_rank_value: str):
    def _style(row):
        # Base
        bg = ""
        if row["דירוג"] == best_rank_value:
            bg = "background-color: rgba(46, 204, 113, 0.20);"  # green tint
        # Illiquid breach
        if pd.notna(illiquid_limit) and pd.notna(row["לא סחיר"]) and row["לא סחיר"] > illiquid_limit:
            bg = "background-color: rgba(231, 76, 60, 0.25);"   # red tint
        # Deviation warning
        if pd.notna(dev_warn) and pd.notna(row["Score סטייה"]) and row["Score סטייה"] > dev_warn:
            # only if not red
            if "231, 76, 60" not in bg:
                bg = "background-color: rgba(243, 156, 18, 0.22);"  # orange tint
        return [bg] * len(row)
    return df.style.apply(_style, axis=1).format({
        "חו״ל": "{:.2f}",
        "ישראל": "{:.2f}",
        "מניות": "{:.2f}",
        "מט״ח": "{:.2f}",
        "לא סחיר": "{:.2f}",
        "שארפ": "{:.3f}",
        "ציון שירות": "{:.1f}",
        "Score סטייה": "{:.2f}",
    })

# -----------------------------
# Password gate
# -----------------------------
def check_password():
    # Prefer Streamlit secrets
    secret = None
    try:
        secret = st.secrets.get("APP_PASSWORD", None)
    except Exception:
        secret = None
    if not secret:
        secret = "1234"  # default placeholder; change via Streamlit secrets in deployment

    if "auth_ok" not in st.session_state:
        st.session_state.auth_ok = False

    if st.session_state.auth_ok:
        return True

    st.markdown("## 🔒 כניסה")
    st.caption("הזן סיסמה כדי להמשיך.")
    pw = st.text_input("סיסמה", type="password", placeholder="••••")
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("כניסה", use_container_width=True):
            if hmac.compare_digest(str(pw), str(secret)):
                st.session_state.auth_ok = True
                st.rerun()
            else:
                st.error("סיסמה שגויה.")
    with col2:
        st.info("בפריסה ל-Streamlit Cloud מומלץ להגדיר APP_PASSWORD ב-Secrets, ולא להשאיר את ברירת המחדל.")
    st.stop()

check_password()

# -----------------------------
# Header
# -----------------------------
st.markdown("# 📊 מנוע תמהילי קרנות השתלמות")
st.markdown(
    "אפליקציה זו קוראת **רק** את קובץ האקסל שתעלה (Single Source of Truth), "
    "ומחפשת שילובי קופות (1–3) עם משקלים שמסכמים ל-100% לפי היעדים שלך. "
    "כולל **כלל ישראל**: *ישראל = 100 − חו״ל*."
)

# -----------------------------
# Uploads
# -----------------------------
with st.sidebar:
    st.markdown("### העלאת קבצים")
    holdings_file = st.file_uploader("קובץ אקסל מסלולים/חשיפות", type=["xlsx"], accept_multiple_files=False)
    service_file = st.file_uploader("קובץ אקסל דירוג שירות (אופציונלי)", type=["xlsx"], accept_multiple_files=False)
    st.markdown("---")
    st.markdown("### תצורה")
    n_funds = st.radio("כמה קופות לשלב?", [1, 2, 3], horizontal=True, index=1)
    manager_mode = st.radio("בחירת מנהלים", ["פיזור בין מנהלים", "אותו מנהל בלבד"], index=0)
    step = st.select_slider("צעד משקלים (%)", options=[1,2,5,10], value=5, help="לדוגמה: צעד 5% => 0,5,10,...")
    st.markdown("---")
    st.markdown("### דירוג")
    objective = st.selectbox("דירוג ראשי", ["דיוק", "שארפ", "שירות", "מקסום מט״ח"], index=0)
    st.markdown("---")
    st.markdown("### ספים")
    dev_warn = st.slider("סף אזהרת סטייה (Score)", min_value=0.0, max_value=30.0, value=6.0, step=0.5)
    st.caption("הצבע הכתום מופיע אם סטיית היעד גבוהה מהסף הזה.")

if not holdings_file:
    st.warning("כדי להתחיל – העלה קובץ אקסל מסלולים/חשיפות בצד שמאל.")
    st.stop()

# -----------------------------
# Load data
# -----------------------------
@st.cache_data(show_spinner=False)
def _cached_load_holdings(file_bytes):
    import io
    bio = io.BytesIO(file_bytes)
    return load_holdings_excel(bio)

@st.cache_data(show_spinner=False)
def _cached_load_service(file_bytes):
    import io
    bio = io.BytesIO(file_bytes)
    return load_service_scores_excel(bio)

with st.spinner("טוען נתונים מהאקסל..."):
    df_long, sheet_names = _cached_load_holdings(holdings_file.getvalue())

if df_long.empty:
    st.error("לא הצלחתי לזהות טבלאות תקינות בקובץ. ודא שבכל גיליון יש עמודת 'פרמטר' ושורות חשיפה מרכזיות.")
    st.stop()

# Show count of investment tracks recognized (sheets)
st.markdown(
    f"**סך מסלולי ההשקעה שזוהו בקובץ:** `{len(sheet_names)}`  &nbsp;|&nbsp; "
    f"**סך קופות (מנהל×מסלול) שזוהו:** `{len(df_long)}`"
)

# Service scores
if service_file:
    service_scores = _cached_load_service(service_file.getvalue())
else:
    service_scores = default_service_scores(sorted(df_long["manager"].unique().tolist()))

# Fill any missing managers with default placeholder
for m in df_long["manager"].unique().tolist():
    service_scores.setdefault(m, 50.0)

# -----------------------------
# Tabs
# -----------------------------
tab1, tab2, tab3 = st.tabs(["הגדרות יעד", "תוצאות (3 חלופות)", "פירוט חישוב / שקיפות"])

with tab1:
    st.subheader("הגדרות יעד")
    st.caption("הגדר יעדים באחוזים. ישראל מחושבת אוטומטית כמשלים ל-100% חו״ל.")
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        target_foreign = st.slider("יעד חו״ל (%)", 0.0, 120.0, 60.0, step=0.5)
    with c2:
        target_stocks = st.slider("יעד מניות (%)", 0.0, 120.0, 40.0, step=0.5)
    with c3:
        target_fx = st.slider("יעד מט״ח (%)", 0.0, 150.0, 25.0, step=0.5)
    with c4:
        max_illiquid = st.slider("מקסימום לא סחיר (%)", 0.0, 60.0, 20.0, step=0.5)

    st.markdown("#### מה נכנס ליעד הדיוק?")
    colA, colB, colC, colD = st.columns(4)
    with colA:
        use_foreign = st.checkbox("כלול חו״ל", value=True)
    with colB:
        use_stocks = st.checkbox("כלול מניות", value=True)
    with colC:
        use_fx = st.checkbox("כלול מט״ח", value=False)
    with colD:
        use_illiquid_target = st.checkbox("כלול לא סחיר כיעד (בנוסף למגבלה)", value=False)
        target_illiquid = st.slider("יעד לא סחיר (%)", 0.0, 60.0, 20.0, step=0.5, disabled=not use_illiquid_target)

    targets = {
        "foreign": target_foreign if use_foreign else np.nan,
        "stocks": target_stocks if use_stocks else np.nan,
        "fx": target_fx if use_fx else np.nan,
        "illiquid": target_illiquid if use_illiquid_target else np.nan,
    }

    st.markdown("---")
    run = st.button("חשב / חפש חלופות", type="primary", use_container_width=True)

with tab2:
    st.subheader("תוצאות (3 חלופות)")
    st.caption("חלופה 1 לפי הדירוג הראשי, חלופה 2 לפי שארפ, חלופה 3 לפי שירות. נשמרת דרישה להרכב מנהלים שונה בין חלופות ככל שניתן.")
    placeholder_results = st.empty()

with tab3:
    st.subheader("פירוט חישוב / שקיפות")
    with st.expander("פתח פירוט (לשקיפות מלאה)", expanded=False):
        st.write("**Single Source of Truth:** הנתונים נקראים רק מהקובץ שהעלית.")
        st.write("**כלל ישראל:** ישראל מחושבת אוטומטית כ-100 − חו״ל.")
        st.write("**שיטת חיפוש:** חיפוש כוח-גס יציב/יסודי (Brute Force) על כל צירופי הקופות בגודל 1–3 ועל כל חלוקות המשקל לפי הצעד שבחרת.")
        st.write("**מגבלה קשיחה:** לא סחיר משוקלל חייב להיות ≤ המגבלה שהוגדרה.")
        st.write("**Score סטייה (דיוק):** סכום סטיות מוחלטות (L1) של הפרמטרים שסימנת כיעד.")
        st.write("**דירוגים:**")
        st.write("- דירוג ראשי לפי בחירתך (דיוק/שארפ/שירות/מקסום מט״ח).")
        st.write("- חלופה 2 תמיד מחושבת לפי שארפ (בכפוף למגבלות).")
        st.write("- חלופה 3 תמיד מחושבת לפי שירות (בכפוף למגבלות).")
        st.write("**שונות מנהלים בין חלופות:** לאחר בחירת חלופה 1, חלופות 2–3 מחפשות פתרונות עם מנהלים אחרים (ללא חפיפה). אם אין פתרון כזה, האפליקציה תציג את הטוב ביותר האפשרי ותציין זאת.")

# -----------------------------
# Compute on click
# -----------------------------
if "last_results" not in st.session_state:
    st.session_state.last_results = None

def compute_all():
    with st.spinner("מחשב שילובים... (יציב/יסודי)"):
        # Primary candidates
        primary_cands = find_best_solutions(
            df_long=df_long,
            n_funds=n_funds,
            step=int(step),
            manager_mode=manager_mode,
            objective=objective,
            targets=targets,
            max_illiquid=float(max_illiquid),
            service_scores=service_scores,
            exclude_managers=set(),
            top_k=3000,
        )
        if not primary_cands:
            return None, "לא נמצאו שילובים שעומדים במגבלת הלא-סחיר ובשאר הסינונים. נסה להגדיל צעד משקלים או לשנות מגבלות."

        sol1 = primary_cands[0]
        used = {r["manager"] for r in sol1["rows"]}

        # Sharpe alternative (distinct managers)
        sharpe_cands = find_best_solutions(
            df_long=df_long,
            n_funds=n_funds,
            step=int(step),
            manager_mode=manager_mode,
            objective="שארפ",
            targets=targets,
            max_illiquid=float(max_illiquid),
            service_scores=service_scores,
            exclude_managers=set(),
            top_k=3000,
        )
        sol2 = pick_distinct_manager_solution(sharpe_cands, used)
        sol2_note = None
        if sol2 is None:
            sol2 = sharpe_cands[0] if sharpe_cands else None
            sol2_note = "לא נמצא פתרון ללא חפיפת מנהלים מול חלופה 1, מוצג הטוב ביותר האפשרי."

        if sol2:
            used2 = used | {r["manager"] for r in sol2["rows"]}
        else:
            used2 = used

        # Service alternative (distinct managers from 1 and 2)
        service_cands = find_best_solutions(
            df_long=df_long,
            n_funds=n_funds,
            step=int(step),
            manager_mode=manager_mode,
            objective="שירות",
            targets=targets,
            max_illiquid=float(max_illiquid),
            service_scores=service_scores,
            exclude_managers=set(),
            top_k=3000,
        )
        sol3 = pick_distinct_manager_solution(service_cands, used2)
        sol3_note = None
        if sol3 is None:
            sol3 = service_cands[0] if service_cands else None
            sol3_note = "לא נמצא פתרון ללא חפיפת מנהלים מול חלופות 1–2, מוצג הטוב ביותר האפשרי."

        # Build result table (full, no mini tables)
        rows_out = []
        if sol1:
            r1 = format_solution_row(sol1, "חלופה 1", objective)
            r1["יתרון"] = advantage_text(sol1, "primary", sol1["accuracy_score"])
            rows_out.append(r1)
        if sol2:
            r2 = format_solution_row(sol2, "חלופה 2", "שארפ")
            r2["יתרון"] = advantage_text(sol2, "sharpe", sol1["accuracy_score"])
            rows_out.append(r2)
        if sol3:
            r3 = format_solution_row(sol3, "חלופה 3", "שירות")
            r3["יתרון"] = advantage_text(sol3, "service", sol1["accuracy_score"])
            rows_out.append(r3)

        df_out = pd.DataFrame(rows_out)

        # Notes
        notes = [n for n in [sol2_note, sol3_note] if n]
        return df_out, (" | ".join(notes) if notes else None)

def render_results(df_out, notes):
    # KPI cards per alternative
    # We render 3*3 KPI blocks (one per alternative)
    for i, row in df_out.iterrows():
        st.markdown(f"### {row['דירוג']} • ({row['אובייקטיב']})")
        st.markdown(
            f"""
<div class="kpi-wrap">
  <div class="kpi">
    <h4>Score (סטייה מהיעד)</h4>
    <div class="big">{row['Score סטייה']:.2f}</div>
    <div class="sub">ככל שנמוך יותר — מדויק יותר</div>
  </div>
  <div class="kpi">
    <h4>חשיפות (חו״ל / מניות / מט״ח / לא סחיר)</h4>
    <div class="big">{row['חו״ל']:.1f}% • {row['מניות']:.1f}% • {row['מט״ח']:.1f}% • {row['לא סחיר']:.1f}%</div>
    <div class="sub">ישראל מחושבת: {row['ישראל']:.1f}%</div>
  </div>
  <div class="kpi">
    <h4>שארפ משוקלל</h4>
    <div class="big">{row['שארפ']:.3f}</div>
    <div class="sub">ציון שירות: {row['ציון שירות']:.1f}</div>
  </div>
</div>
""",
            unsafe_allow_html=True
        )
        st.markdown("")

    st.markdown("#### טבלה מלאה")
    # Put advantage column first-ish for readability
    col_order = [
        "דירוג","אובייקטיב","יתרון",
        "שילוב (מסלול/קופה)","מנהלים",
        "Score סטייה","חו״ל","ישראל","מניות","מט״ח","לא סחיר","שארפ","ציון שירות"
    ]
    df_out2 = df_out[col_order].copy()

    styled = style_results_df(df_out2, illiquid_limit=float(max_illiquid), dev_warn=float(dev_warn), best_rank_value="חלופה 1")
    st.dataframe(
        styled,
        use_container_width=True,
        height=220,
        column_config={
            "שילוב (מסלול/קופה)": st.column_config.TextColumn(width="large"),
            "מנהלים": st.column_config.TextColumn(width="large"),
            "יתרון": st.column_config.TextColumn(width="large"),
        },
    )
    if notes:
        st.info(notes)

# Trigger compute
if "run_requested" not in st.session_state:
    st.session_state.run_requested = False

# If clicked in tab1
try:
    if run:
        st.session_state.run_requested = True
except Exception:
    pass

if st.session_state.run_requested:
    df_out, note = compute_all()
    if df_out is None:
        st.session_state.last_results = None
        with tab2:
            placeholder_results.error(note or "לא נמצאו תוצאות.")
    else:
        st.session_state.last_results = (df_out, note)
        st.session_state.run_requested = False
        st.rerun()

# Show last results in tab2 if exists
with tab2:
    if st.session_state.last_results is None:
        placeholder_results.info("כשתלחץ על 'חשב / חפש חלופות' בטאב הראשון — יופיעו כאן 3 חלופות.")
    else:
        df_out, note = st.session_state.last_results
        render_results(df_out, note)
