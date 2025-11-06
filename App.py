import streamlit as st
import pandas as pd
import json, re, os
from dotenv import load_dotenv
from openai import OpenAI
from streamlit.components.v1 import html as st_html

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

st.set_page_config(page_title="Auto BI (HTML)", layout="wide")
st.title("📊 Auto BI — HTML Dashboard Generator (16:9, Cross-filtering)")

# ---------- Session ----------
if "spec" not in st.session_state:
    st.session_state.spec = ""
if "df_by_sheet" not in st.session_state:
    st.session_state.df_by_sheet = None
if "profile" not in st.session_state:
    st.session_state.profile = None

# ---------- Sidebar ----------
with st.sidebar:
    st.header("Data")
    f = st.file_uploader("Upload Excel", type=["xlsx", "xls"])
    role = st.selectbox(
        "Role",
        ["Finance Analyst", "Sales Leader", "Operations Manager", "BI Developer"],
    )
    goal = st.text_area(
        "Business Goal",
        placeholder="e.g., Quarterly sales performance by region & product with risks and actions.",
    )
    gen = st.button("✨ Generate Spec")
    reset = st.button("🧹 Reset")

if reset:
    st.session_state.clear()
    st.rerun()

def load_excel(file):
    return pd.read_excel(file, sheet_name=None)

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

ROLE_CONTEXT = {
    "Finance Analyst": "Focus on revenue, margin, costs, profitability, YoY/YoY trends, risks and cashflow signals.",
    "Sales Leader": "Focus on bookings, pipeline, win-rate, top regions/products, new vs returning, YoY growth.",
    "Operations Manager": "Focus on throughput, lead time, utilization, on-time %, defects, supplier/plant performance.",
    "BI Developer": "Focus on balanced visuals, canonical KPIs, simple dims, deployable layout.",
}

SCHEMA_NOTE = """
Return ONLY valid JSON with:
{
 "Pages":[
  {
   "name":"string",
   "Story":[{"section":"Overview|Performance|Trends|Risks|Recommendations","text":"string"}],
   "Filters":[{"field":"string"}],
   "KPIs":[{"title":"string","agg":"sum|avg|min|max|count|distinct","field":"string","format":"auto"}],
   "Layout":[
     {"section":"string","elements":[
        {"type":"Bar|Line|Pie|Table","x":"string(optional)","y":"string(optional)","color":"string(optional)","agg":"sum|avg|min|max|count|distinct(optional)"}
     ]}
   ]
  }
 ]
}
"""

def extract_json(text: str) -> str:
    if not text:
        return "{}"
    text = re.sub(r"```(json)?", "", text)
    text = re.sub(r"```", "", text)
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return "{}"
    cleaned = re.sub(r",(\s*[}\]])", r"\1", m.group(0))
    return cleaned.strip()

def generate_spec(goal: str, profile: dict, role: str) -> str:
    if not client:
        return ""
    prof_text = "\n".join(
        [
            f"Sheet {k}: numeric={v['numeric']} categorical={v['categorical']}"
            for k, v in profile.items()
        ]
    )
    prompt = f"""
You are a {role}. {ROLE_CONTEXT.get(role,"")}
Using this data:
{prof_text}

Business goal:
{goal}

Create a corporate dashboard spec with STORY: Overview, Performance, Trends, Risks, Recommendations.
Include Filters, KPIs, and Layout visuals.
{SCHEMA_NOTE}
"""
    r = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.25,
    )
    return extract_json(r.choices[0].message.content)

# ---------- Load Data ----------
if f:
    dfs = load_excel(f)
    st.session_state.df_by_sheet = dfs
    st.session_state.profile = profile_from_excel(dfs)
    st.success(f"Loaded {len(dfs)} sheet(s).")

# ---------- Generate ----------
if gen and st.session_state.df_by_sheet and goal.strip():
    with st.spinner("Generating BI Spec..."):
        spec = generate_spec(goal, st.session_state.profile, role)
        if not spec or spec == "{}":
            st.error("Spec generation failed. Set OPENAI_API_KEY or try again.")
        else:
            st.session_state.spec = spec

# ---------- Editor ----------
st.subheader("🧩 BI Spec (JSON, live-editable)")
st.session_state.spec = st.text_area(
    "Edit JSON Spec", value=st.session_state.spec, height=260
)

# ---------- Validate JSON / fallback ----------
try:
    json.loads(extract_json(st.session_state.spec))
    st.success("✅ JSON valid.")
except Exception:
    st.warning("⚠️ Invalid JSON. Loading minimal fallback.")
    st.session_state.spec = json.dumps(
        {
            "Pages": [
                {
                    "name": "Story Dashboard",
                    "Story": [
                        {"section": "Overview", "text": "Executive highlights."},
                        {"section": "Performance", "text": "KPIs and region performance."},
                        {"section": "Trends", "text": "Time trends and mix."},
                        {"section": "Risks", "text": "Weak spots."},
                        {"section": "Recommendations", "text": "Actions to take."},
                    ],
                    "Filters": [{"field": "Region"}],
                    "KPIs": [
                        {
                            "title": "Total Sales",
                            "agg": "sum",
                            "field": "Sales",
                            "format": "auto",
                        },
                        {
                            "title": "Avg Profit",
                            "agg": "avg",
                            "field": "Profit",
                            "format": "auto",
                        },
                    ],
                    "Layout": [
                        {
                            "section": "Performance",
                            "elements": [{"type": "Bar", "x": "Region", "y": "Sales"}],
                        },
                        {
                            "section": "Trends",
                            "elements": [{"type": "Line", "x": "Month", "y": "Profit"}],
                        },
                        {
                            "section": "Mix",
                            "elements": [{"type": "Pie", "x": "Category", "y": "Sales"}],
                        },
                    ],
                }
            ]
        },
        indent=2,
    )

# ---------- Choose data ----------
if not st.session_state.df_by_sheet:
    st.info("Upload an Excel file to preview dashboard.")
    st.stop()

sheet = st.selectbox(
    "Active Sheet for the dashboard:", list(st.session_state.df_by_sheet.keys())
)
df = st.session_state.df_by_sheet[sheet].copy()

# Limit rows
MAX_ROWS = 5000
if len(df) > MAX_ROWS:
    df = df.head(MAX_ROWS)

# ---------- Prepare payload ----------
def to_js_rows(df: pd.DataFrame):
    def conv(v):
        if pd.isna(v):
            return None
        if isinstance(v, (pd.Timestamp, pd.Timedelta)):
            return str(v)
        return v

    return [{col: conv(row[col]) for col in df.columns} for _, row in df.iterrows()]

payload = {"columns": list(df.columns), "rows": to_js_rows(df)}

# ---------- Render dashboard ----------
spec_obj = json.loads(extract_json(st.session_state.spec))
active_page = (spec_obj.get("Pages") or [{}])[0]

# --------------- HTML ----------------
DASH_HTML = """<div id='app' style='display:flex;justify-content:center;'>
  <div id='board' style='width:960px;aspect-ratio:16/9;border:1px solid #e9ecef;border-radius:12px;padding:12px;font-family:Inter,system-ui;'>
    <h3>Auto BI Story Dashboard</h3>
    <div id='chart' style='width:100%;height:540px;'></div>
  </div>
</div>
<script src='https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js'></script>
<script>
  const data = window.DASH_DATA;
  const rows = data.rows;
  const cols = data.columns;
  const el = document.getElementById('chart');
  const chart = echarts.init(el);
  if (cols.length >= 2) {
    const x = cols[0], y = cols[1];
    const agg = {};
    rows.forEach(r=>{
      const key = r[x]; const val = +r[y];
      if (!agg[key]) agg[key]=0;
      if (!isNaN(val)) agg[key]+=val;
    });
    const sorted = Object.entries(agg).sort((a,b)=>a[0]>b[0]?1:-1);
    chart.setOption({
      xAxis:{type:'category',data:sorted.map(d=>d[0])},
      yAxis:{type:'value'},
      series:[{type:'bar',data:sorted.map(d=>d[1])}],
      grid:{left:40,right:20,top:40,bottom:40}
    });
  }
</script>
"""

st_html(
    f"""
    <script>
      window.DASH_SPEC = {json.dumps(active_page, ensure_ascii=False)};
      window.DASH_DATA = {json.dumps(payload, ensure_ascii=False)};
    </script>
    {DASH_HTML}
    """,
    height=720,
    scrolling=False,
)
