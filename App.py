import streamlit as st, pandas as pd, plotly.express as px, json, os, re
from openai import OpenAI
from streamlit_sortables import sort_items
from bi_utils import apply_filters, calc_kpi, format_val
from components.chart_builder import add_element_ui

# --- CONFIG ---
st.set_page_config(page_title="Auto-BI Studio", layout="wide")
st.title("🧠 Auto-BI — Interactive Dashboard Studio")

OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
if not OPENAI_API_KEY:
    st.error("❌ Missing OPENAI_API_KEY")
    st.stop()
client = OpenAI(api_key=OPENAI_API_KEY)

# --- STATE ---
for k,v in {"df":None,"elements":[],"filters":{},"theme":"Light","presentation":False}.items():
    if k not in st.session_state: st.session_state[k]=v

# --- SIDEBAR ---
if not st.session_state.presentation:
    st.sidebar.header("📂 Data")
    f = st.sidebar.file_uploader("Upload Excel", type=["xlsx","xls"])
    if f:
        st.session_state.df = pd.read_excel(f)

    st.sidebar.header("🎨 Appearance")
    st.session_state.theme = st.sidebar.radio("Theme",["Light","Dark"],index=0)

    st.sidebar.header("⚙️ Layout Controls")
    if st.sidebar.button("💾 Save dashboard"):
        json.dump(st.session_state.elements, open("dashboard.json","w"))
        st.sidebar.success("Saved dashboard.json")

    if st.sidebar.button("📂 Load dashboard") and os.path.exists("dashboard.json"):
        st.session_state.elements = json.load(open("dashboard.json"))
        st.sidebar.success("Loaded dashboard.json")

    if st.sidebar.button("🧾 Export HTML"):
        html = st.session_state.get("export_html","")
        if html:
            st.sidebar.download_button("Download HTML", data=html, file_name="dashboard.html", mime="text/html")
            st.sidebar.success("✅ HTML export ready")

    # Toggle presentation mode
    if st.sidebar.button("🎤 Presentation Mode"):
        st.session_state.presentation = True
        st.experimental_rerun()

else:
    # Exit presentation mode button
    st.markdown("<div style='text-align:right;'>", unsafe_allow_html=True)
    if st.button("❌ Exit Presentation Mode"):
        st.session_state.presentation = False
        st.experimental_rerun()
    st.markdown("</div>", unsafe_allow_html=True)

# --- MAIN ---
df = st.session_state.df
if df is None:
    st.info("Upload data to start.")
    st.stop()

if not st.session_state.presentation:
    st.markdown("### 🎛 Filters")
    cols = st.columns(min(3,len(df.columns)))
    for i,c in enumerate(df.columns[:3]):
        vals = sorted(df[c].dropna().astype(str).unique())
        sel = cols[i].multiselect(c, vals, default=st.session_state.filters.get(c,[]))
        st.session_state.filters[c]=sel

df_f = apply_filters(df, st.session_state.filters)

# --- ADD ELEMENTS ---
if not st.session_state.presentation:
    with st.expander("➕ Add Element"):
        new_el = add_element_ui(df.columns)
        if new_el and st.button("Add to dashboard"):
            st.session_state.elements.append(new_el)

if not st.session_state.elements:
    st.warning("No elements yet. Use 'Add Element' above.")
    st.stop()

# --- DRAG-AND-DROP ---
if not st.session_state.presentation:
    st.markdown("### 🧩 Canvas Editor")
    order = sort_items([f"{e['type']}_{i}" for i,e in enumerate(st.session_state.elements)],
                       direction="horizontal", key="canvas")
    new_order = []
    for item in order:
        idx = int(item.split("_")[-1])
        new_order.append(st.session_state.elements[idx])
    st.session_state.elements = new_order

export_html = "<html><body style='font-family:sans-serif;'>"

# --- RENDER ELEMENTS ---
for i,el in enumerate(st.session_state.elements):
    t = el.get("type")
    if t == "KPI":
        expr, fmt = el.get("expr"), el.get("format")
        v = calc_kpi(df_f, expr)
        st.metric(el.get("title", expr), format_val(v, fmt))
        export_html += f"<h4>{el.get('title')}</h4><p>{format_val(v,fmt)}</p>"
    elif t == "Chart":
        x,y,chart_t = el.get("x"),el.get("y"),el.get("chart","bar")
        if x not in df.columns or y not in df.columns: continue
        d = df_f.groupby(x)[y].sum().reset_index()
        fig = px.bar(d,x=x,y=y) if chart_t=="bar" else \
              px.line(d,x=x,y=y) if chart_t=="line" else \
              px.pie(d,names=x,values=y)
        fig.update_layout(height=480,width=960,
                          template="plotly_dark" if st.session_state.theme=="Dark" else "plotly_white",
                          title=f"{x} vs {y}")
        st.plotly_chart(fig, use_container_width=True)
        export_html += fig.to_html(include_plotlyjs="cdn")
    elif t == "Table":
        cols = el.get("cols") or df.columns[:5]
        st.dataframe(df_f[list(cols)].head(20))
        export_html += df_f[list(cols)].head(20).to_html(index=False)

export_html += "</body></html>"
st.session_state.export_html = export_html

if not st.session_state.presentation:
    st.markdown("---")
    st.caption("💡 Drag items to reorder. Toggle 'Presentation Mode' for full-screen view.")
