import streamlit as st
import pandas as pd
import plotly.express as px
import json, re, io, os
from datetime import datetime
from openai import OpenAI

# --- SETUP ---
st.set_page_config(page_title="Auto BI (Streamlit)", layout="wide")
st.title("📊 Auto BI — Prompt-to-Dashboard Studio")

# Get API key from secrets or env
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
if not OPENAI_API_KEY:
    st.error("⚠️ Missing OpenAI API Key. Add it in `.streamlit/secrets.toml` or environment.")
    st.stop()
client = OpenAI(api_key=OPENAI_API_KEY)

# --- SESSION STATE ---
for key, default in {
    "df": None,
    "profile": None,
    "spec": None,
    "filters": {},
    "bookmarks": {}
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# --- FUNCTIONS ---
def profile_from_excel(dfs):
    prof = {}
    for name, df in dfs.items():
        prof[name] = {
            "rows": int(df.shape[0]),
            "cols": int(df.shape[1]),
            "numeric": df.select_dtypes(include="number").columns.tolist(),
            "categorical": df.select_dtypes(exclude="number").columns.tolist(),
        }
    return prof

def clean_json(text: str):
    text = re.sub(r"```(json)?|```", "", text)
    m = re.search(r"\{[\s\S]*\}", text)
    if not m: return {}
    try:
        return json.loads(re.sub(r",(\s*[}\]])", r"\1", m.group(0)))
    except:
        return {}

def generate_spec(goal, role, profile):
    prof_text = "\n".join([f"{s}: numeric={p['numeric']} categorical={p['categorical']}" for s,p in profile.items()])
    prompt = f"""
Act as a {role}.
Using this data:
{prof_text}

Goal:
{goal}

Create a BI dashboard spec in JSON with:
- pages:[{{
   name, 
   story (overview, performance, trends, risks, recommendations),
   filters:[{{field}}],
   kpis:[{{title, expr, format}}],
   layout:[{{section, elements:[{{type, x, y, agg}}]}}]
}}]
Return only JSON.
"""
    r = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}],
        temperature=0.3
    )
    return clean_json(r.choices[0].message.content)

def generate_insight(title, data):
    try:
        prompt = f"Write a one-line executive insight for this chart titled '{title}' based on summarized data: {data}. Keep it concise and analytical."
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user","content":prompt}],
            temperature=0.5
        )
        return r.choices[0].message.content.strip()
    except:
        return ""

def apply_filters(df, filters):
    out = df.copy()
    for col, vals in filters.items():
        if col in out.columns and vals:
            out = out[out[col].astype(str).isin(vals)]
    return out


# --- SIDEBAR ---
with st.sidebar:
    st.header("Data & Goal")
    f = st.file_uploader("Upload Excel file", type=["xlsx","xls"])
    role = st.selectbox("Role", ["Finance Analyst","Sales Leader","Operations Manager","BI Developer"])
    goal = st.text_area("Business Goal", placeholder="e.g., Quarterly sales by region and category with profit trends")
    if st.button("✨ Generate Dashboard Spec"):
        if f and goal.strip():
            dfs = pd.read_excel(f, sheet_name=None)
            st.session_state.df = dfs
            st.session_state.profile = profile_from_excel(dfs)
            st.session_state.spec = generate_spec(goal, role, st.session_state.profile)
            st.session_state.filters = {}
            st.success("✅ Dashboard spec generated successfully!")
        else:
            st.warning("Please upload data and enter a goal first.")

    # Bookmark buttons
    st.markdown("### 🔖 Bookmarks")
    title = st.text_input("Bookmark name")
    if st.button("Save current filters") and title:
        st.session_state.bookmarks[title] = st.session_state.filters.copy()
    if st.session_state.bookmarks:
        sel = st.selectbox("Load bookmark", ["(None)"] + list(st.session_state.bookmarks.keys()))
        if sel != "(None)":
            st.session_state.filters = st.session_state.bookmarks[sel]
            st.info(f"Loaded bookmark: {sel}")


# --- MAIN ---
if not st.session_state.spec:
    st.info("Upload data and click *Generate Dashboard Spec* to get started.")
    st.stop()

spec = st.session_state.spec
if "pages" not in spec or not spec["pages"]:
    st.error("Spec invalid or empty.")
    st.stop()

page = spec["pages"][0]
sheet = list(st.session_state.df.keys())[0]
df = st.session_state.df[sheet]

# Apply filters
df_filt = apply_filters(df, st.session_state.filters)

st.markdown(f"### 🏢 {page.get('name','Dashboard')} — {sheet}")

# Filters UI
if "filters" in page and page["filters"]:
    st.markdown("#### 🎛 Filters")
    cols = st.columns(len(page["filters"]))
    for i,f in enumerate(page["filters"]):
        field = f.get("field")
        if field in df.columns:
            vals = sorted(df[field].dropna().astype(str).unique().tolist())
            cur = st.session_state.filters.get(field, [])
            chosen = cols[i].multiselect(field, vals, default=cur)
            st.session_state.filters[field] = chosen

# KPI cards
if "kpis" in page and page["kpis"]:
    st.markdown("#### 📈 KPIs")
    cols = st.columns(min(4, len(page["kpis"])))
    for i,k in enumerate(page["kpis"]):
        expr = k.get("expr")
        title = k.get("title", expr)
        val = None
        if expr:
            try:
                if expr.startswith("SUM("):
                    col = expr[4:-1]
                    val = df_filt[col].sum()
                elif expr.startswith("AVG("):
                    col = expr[4:-1]
                    val = df_filt[col].mean()
                elif expr.startswith("COUNT("):
                    col = expr[6:-1]
                    val = df_filt[col].count()
                else:
                    val = 0
            except:
                val = 0
        fmt = k.get("format")
        if fmt == "pct" and val:
            val = f"{val*100:.2f}%"
        elif fmt == "currency":
            val = f"₹{val:,.0f}"
        else:
            val = f"{val:,.0f}"
        cols[i%4].metric(title, val)

# Charts
if "layout" in page:
    st.markdown("#### 📊 Visuals")
    layout = page["layout"]
    for sec in layout:
        st.markdown(f"##### {sec.get('section','')}")
        for el in sec.get("elements", []):
            x, y, typ = el.get("x"), el.get("y"), el.get("type","bar").lower()
            if x not in df.columns or y not in df.columns:
                continue
            data = df_filt.groupby(x)[y].sum().reset_index()
            fig = None
            if typ == "bar":
                fig = px.bar(data, x=x, y=y, title=f"{x} vs {y}")
            elif typ == "line":
                fig = px.line(data, x=x, y=y, title=f"{x} vs {y}")
            elif typ == "pie":
                fig = px.pie(data, names=x, values=y, title=f"{x} Share")
            elif typ == "table":
                st.dataframe(df_filt[[x,y]].head(20))
            if fig:
                fig.update_layout(height=480, width=960, margin=dict(l=20,r=20,t=40,b=40))
                st.plotly_chart(fig, use_container_width=True)
                with st.spinner("Generating narrative insight..."):
                    insight = generate_insight(f"{x} vs {y}", data.head(10).to_dict())
                    if insight:
                        st.caption(f"🧠 {insight}")

# Story
if "story" in page:
    st.markdown("#### 🧭 Story")
    for s in page["story"]:
        st.markdown(f"**{s['section']}**: {s['text']}")
