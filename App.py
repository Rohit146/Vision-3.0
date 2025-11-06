import streamlit as st, pandas as pd, plotly.express as px, json, re, os
from openai import OpenAI
from bi_utils import apply_filters, calc_kpi, format_val

st.set_page_config(page_title="Auto-BI Prompt Studio", layout="wide")
st.title("🧠 Auto-BI — Prompt-Driven Dashboard Builder")

# --- API key ---
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
if not OPENAI_API_KEY:
    st.error("Missing OPENAI_API_KEY in secrets.")
    st.stop()
client = OpenAI(api_key=OPENAI_API_KEY)

# --- state ---
for k,v in {"df":None,"spec":None,"filters":{},"mode":"Edit","theme":"Light"}.items():
    if k not in st.session_state: st.session_state[k]=v

# --- sidebar controls ---
st.sidebar.header("⚙️ Controls")
mode = st.sidebar.radio("Mode", ["Edit","Presentation"])
st.session_state.mode = mode
theme = st.sidebar.radio("Theme",["Light","Dark"])
st.session_state.theme = theme

f = st.sidebar.file_uploader("Upload Excel", type=["xlsx","xls"])
if f:
    st.session_state.df = pd.read_excel(f)
st.sidebar.divider()

prompt = st.sidebar.text_area("Dashboard prompt",
    placeholder="Example: Show quarterly revenue by region with profit margins.")
if st.sidebar.button("✨ Generate Dashboard") and prompt:
    df = st.session_state.df
    if df is None:
        st.sidebar.warning("Upload data first.")
    else:
        cols = ", ".join(df.columns)
        query = f"""
Create a simple BI dashboard JSON spec for the following prompt:
'{prompt}'
Available columns: [{cols}]
Use structure:
{{"filters":[{{"field":""}}],"kpis":[{{"title":"","expr":"","format":""}}],"charts":[{{"type":"","x":"","y":""}}]}}
Return JSON only.
"""
        r = client.chat.completions.create(model="gpt-4o-mini",
            messages=[{"role":"user","content":query}],
            temperature=0.3)
        txt = re.sub(r"```(json)?|```","",r.choices[0].message.content)
        try:
            st.session_state.spec = json.loads(txt)
        except Exception:
            st.sidebar.error("Invalid JSON from model.")

st.sidebar.divider()
if st.sidebar.button("🧾 Export HTML") and st.session_state.get("spec"):
    html = st.session_state.get("export_html","")
    st.sidebar.download_button("Download HTML", data=html,
        file_name="dashboard.html", mime="text/html")

# --- main content ---
df = st.session_state.df
if df is None:
    st.info("Upload a dataset and enter a dashboard prompt in the sidebar.")
    st.stop()

spec = st.session_state.spec
if not spec:
    st.info("Enter a prompt and click 'Generate Dashboard'.")
    st.stop()

filters = st.session_state.filters
if st.session_state.mode == "Edit":
    st.markdown("### 🎛 Filters")
    for fdef in spec.get("filters", [])[:3]:
        field = fdef.get("field")
        if field in df.columns:
            vals = sorted(df[field].dropna().astype(str).unique())
            sel = st.multiselect(field, vals, default=filters.get(field,[]))
            filters[field] = sel
df_f = apply_filters(df, filters)
st.session_state.filters = filters

# --- render dashboard ---
html_out = "<html><body style='font-family:sans-serif;'>"

# KPIs
if spec.get("kpis"):
    st.markdown("#### 📈 KPIs")
    cols = st.columns(min(4,len(spec["kpis"])))
    for i,k in enumerate(spec["kpis"]):
        expr, fmt = k.get("expr"), k.get("format","auto")
        val = calc_kpi(df_f, expr)
        cols[i%4].metric(k.get("title",expr), format_val(val, fmt))
        html_out += f"<h4>{k.get('title')}</h4><p>{format_val(val,fmt)}</p>"

# Charts
if spec.get("charts"):
    st.markdown("#### 📊 Charts")
    for c in spec["charts"]:
        typ,x,y = c.get("type","bar").lower(), c.get("x"), c.get("y")
        if x not in df.columns or y not in df.columns: continue
        d = df_f.groupby(x)[y].sum().reset_index()
        fig = px.bar(d,x=x,y=y) if typ=="bar" else \
              px.line(d,x=x,y=y) if typ=="line" else \
              px.pie(d,names=x,values=y)
        fig.update_layout(template="plotly_dark" if st.session_state.theme=="Dark" else "plotly_white",
                          height=480,width=960)
        st.plotly_chart(fig,use_container_width=True)
        html_out += fig.to_html(include_plotlyjs="cdn")

st.session_state.export_html = html_out + "</body></html>"

# --- Presentation mode ---
if st.session_state.mode == "Presentation":
    st.markdown(
        """
        <style>
        .stSidebar, header, footer, .stTextInput, .stTextArea, .stSelectbox, .stMultiselect {display:none !important;}
        </style>
        """,
        unsafe_allow_html=True,
    )
