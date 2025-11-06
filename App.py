import streamlit as st
import pandas as pd
import plotly.express as px
import json, re, os
from openai import OpenAI
from bi_utils import apply_filters, calc_kpi, format_val

# --- CONFIG ---
st.set_page_config(page_title="Auto-BI Smart Studio", layout="wide")
st.title("🧠 Auto-BI — Smart Dashboard Generator")

# --- API KEY ---
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
if not OPENAI_API_KEY:
    st.error("❌ Missing OPENAI_API_KEY in secrets.")
    st.stop()
client = OpenAI(api_key=OPENAI_API_KEY)

# --- STATE ---
for k,v in {"df":None,"spec":None,"filters":{},"mode":"Edit","theme":"Light"}.items():
    if k not in st.session_state: st.session_state[k]=v

# --- HELPER: detect column types ---
def detect_column_roles(df):
    roles = {}
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]):
            roles[c] = "numeric"
        elif pd.api.types.is_datetime64_any_dtype(df[c]):
            roles[c] = "date"
        else:
            roles[c] = "categorical"
    return roles

# --- HELPER: choose best chart type ---
def suggest_chart_type(x_type, y_type):
    if x_type == "date" and y_type == "numeric":
        return "line"
    if x_type == "categorical" and y_type == "numeric":
        return "bar"
    if x_type == "categorical" and y_type == "categorical":
        return "pie"
    if x_type == "numeric" and y_type == "numeric":
        return "scatter"
    if y_type == "numeric" and not x_type:
        return "histogram"
    return "bar"

# --- SIDEBAR ---
st.sidebar.header("⚙️ Controls")
st.session_state.mode = st.sidebar.radio("Mode", ["Edit","Presentation"], index=0)
st.session_state.theme = st.sidebar.radio("Theme", ["Light","Dark"], index=0)

file = st.sidebar.file_uploader("Upload Excel", type=["xlsx","xls"])
if file:
    st.session_state.df = pd.read_excel(file)

st.sidebar.divider()
prompt = st.sidebar.text_area("💬 Dashboard prompt",
    placeholder="Example: Compare sales and profit across regions and quarters.")

# --- GENERATE SPEC USING PROMPT ---
if st.sidebar.button("✨ Generate Dashboard") and prompt:
    df = st.session_state.df
    if df is None:
        st.sidebar.warning("Upload data first.")
    else:
        cols = ", ".join(df.columns)
        query = f"""
You are a BI analyst. Create a JSON dashboard spec for this prompt:
'{prompt}'
Columns: [{cols}]
Use structure:
{{"filters":[{{"field":""}}],"kpis":[{{"title":"","expr":"","format":""}}],"charts":[{{"x":"","y":""}}]}}
Return valid JSON only.
"""
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":query}],
            temperature=0.3
        )
        txt = re.sub(r"```(json)?|```","",r.choices[0].message.content)
        try:
            st.session_state.spec = json.loads(txt)
            st.success("✅ Dashboard spec generated successfully!")
        except Exception:
            st.sidebar.error("Invalid JSON from model.")

st.sidebar.divider()
if st.sidebar.button("🧾 Export HTML") and st.session_state.get("spec"):
    html = st.session_state.get("export_html","")
    if html:
        st.sidebar.download_button("Download HTML", data=html,
            file_name="dashboard.html", mime="text/html")

# --- MAIN ---
df = st.session_state.df
if df is None:
    st.info("Upload a dataset and enter a dashboard prompt in the sidebar.")
    st.stop()

spec = st.session_state.spec
if not spec:
    st.info("Enter a prompt and click 'Generate Dashboard'.")
    st.stop()

filters = st.session_state.filters
roles = detect_column_roles(df)

# --- FILTERS ---
if st.session_state.mode == "Edit" and spec.get("filters"):
    st.markdown("### 🎛 Filters")
    fcols = st.columns(min(3, len(spec["filters"])))
    for i, fdef in enumerate(spec["filters"][:3]):
        field = fdef.get("field")
        if field in df.columns:
            vals = sorted(df[field].dropna().astype(str).unique())
            sel = fcols[i].multiselect(field, vals, default=filters.get(field, []))
            filters[field] = sel
df_f = apply_filters(df, filters)
st.session_state.filters = filters

# --- RENDER DASHBOARD ---
html_out = "<html><body style='font-family:sans-serif;'>"

# KPIs
if spec.get("kpis"):
    st.markdown("#### 📈 KPIs")
    kpi_cols = st.columns(min(4, len(spec["kpis"])))
    for i, k in enumerate(spec["kpis"]):
        expr, fmt = k.get("expr"), k.get("format", "auto")
        val = calc_kpi(df_f, expr)
        kpi_cols[i % 4].metric(k.get("title", expr), format_val(val, fmt))
        html_out += f"<h4>{k.get('title')}</h4><p>{format_val(val,fmt)}</p>"

# CHARTS
if spec.get("charts"):
    st.markdown("#### 📊 Charts")
    charts = spec["charts"]
    ncols = 2 if len(charts) > 1 else 1
    chart_rows = [charts[i:i+ncols] for i in range(0, len(charts), ncols)]

    for row in chart_rows:
        cols = st.columns(len(row))
        for idx, chart_def in enumerate(row):
            with cols[idx]:
                x, y = chart_def.get("x"), chart_def.get("y")
                if not x or not y or x not in df.columns or y not in df.columns:
                    continue
                x_type, y_type = roles.get(x, "categorical"), roles.get(y, "numeric")
                typ = suggest_chart_type(x_type, y_type)

                d = df_f.groupby(x)[y].sum().reset_index()

                if typ == "bar":
                    fig = px.bar(d, x=x, y=y)
                elif typ == "line":
                    fig = px.line(d, x=x, y=y)
                elif typ == "pie":
                    fig = px.pie(d, names=x, values=y)
                elif typ == "scatter":
                    fig = px.scatter(df_f, x=x, y=y)
                elif typ == "histogram":
                    fig = px.histogram(df_f, x=y)
                else:
                    fig = px.bar(d, x=x, y=y)

                fig.update_layout(
                    template="plotly_dark" if st.session_state.theme == "Dark" else "plotly_white",
                    height=400,
                    margin=dict(l=10, r=10, t=40, b=30),
                    title=f"{x} vs {y} ({typ.capitalize()})"
                )
                st.plotly_chart(fig, use_container_width=True)
                html_out += fig.to_html(include_plotlyjs="cdn")

html_out += "</body></html>"
st.session_state.export_html = html_out

# --- Presentation mode CSS ---
if st.session_state.mode == "Presentation":
    st.markdown("""
    <style>
    .stSidebar, header, footer, .stTextInput, .stTextArea, .stSelectbox, .stMultiselect, .stButton, .stRadio {display:none !important;}
    div[data-testid="stToolbar"] {display: none !important;}
    .block-container {padding-top: 1rem !important;}
    </style>
    """, unsafe_allow_html=True)
    st.markdown("<h4 style='text-align:center; color:gray;'>🎤 Presentation Mode</h4>", unsafe_allow_html=True)
