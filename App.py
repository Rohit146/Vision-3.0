import streamlit as st
import pandas as pd
import json, re, os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

st.set_page_config(page_title="Auto BI (HTML)", layout="wide")
st.title("📊 Auto BI — HTML Dashboard Generator (16:9, Cross-filtering)")

# ---------- Session ----------
if "spec" not in st.session_state: st.session_state.spec = ""
if "df_by_sheet" not in st.session_state: st.session_state.df_by_sheet = None
if "profile" not in st.session_state: st.session_state.profile = None

# ---------- Sidebar ----------
with st.sidebar:
    st.header("Data")
    f = st.file_uploader("Upload Excel", type=["xlsx","xls"])
    role = st.selectbox("Role", ["Finance Analyst","Sales Leader","Operations Manager","BI Developer"])
    goal = st.text_area("Business Goal", placeholder="e.g., Quarterly sales performance by region & product with risks and actions.")
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
            "categorical": df.select_dtypes(exclude="number").columns.tolist()
        }
    return prof

ROLE_CONTEXT = {
    "Finance Analyst": "Focus on revenue, margin, costs, profitability, YoY/YoY trends, risks and cashflow signals.",
    "Sales Leader": "Focus on bookings, pipeline, win-rate, top regions/products, new vs returning, YoY growth.",
    "Operations Manager": "Focus on throughput, lead time, utilization, on-time %, defects, supplier/plant performance.",
    "BI Developer": "Focus on balanced visuals, canonical KPIs, simple dims, deployable layout."
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
    if not text: return "{}"
    text = re.sub(r"```(json)?", "", text)
    text = re.sub(r"```", "", text)
    m = re.search(r"\{[\s\S]*\}", text)
    if not m: return "{}"
    cleaned = re.sub(r",(\s*[}\]])", r"\1", m.group(0))
    return cleaned.strip()

def generate_spec(goal: str, profile: dict, role: str) -> str:
    if not client: return ""
    prof_text = "\n".join([f"Sheet {k}: numeric={v['numeric']} categorical={v['categorical']}" for k,v in profile.items()])
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
        messages=[{"role":"user","content":prompt}],
        temperature=0.25
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
st.session_state.spec = st.text_area("Edit JSON Spec", value=st.session_state.spec, height=260)

# Validate / fallback
try:
    json.loads(extract_json(st.session_state.spec))
    st.success("✅ JSON valid.")
except Exception as e:
    st.warning("⚠️ Invalid JSON. Loading a minimal fallback.")
    st.session_state.spec = json.dumps({
        "Pages":[{
            "name":"Story Dashboard",
            "Story":[
                {"section":"Overview","text":"Executive highlights."},
                {"section":"Performance","text":"KPIs and region performance."},
                {"section":"Trends","text":"Time trends and mix."},
                {"section":"Risks","text":"Weak spots."},
                {"section":"Recommendations","text":"Actions to take."}
            ],
            "Filters":[{"field":"Region"}],
            "KPIs":[
                {"title":"Total Sales","agg":"sum","field":"Sales","format":"auto"},
                {"title":"Avg Profit","agg":"avg","field":"Profit","format":"auto"}
            ],
            "Layout":[
              {"section":"Performance","elements":[{"type":"Bar","x":"Region","y":"Sales"}]},
              {"section":"Trends","elements":[{"type":"Line","x":"Month","y":"Profit"}]},
              {"section":"Mix","elements":[{"type":"Pie","x":"Category","y":"Sales"}]}
            ]
        }]}
    }, indent=2)

# ---------- Data selection ----------
if not st.session_state.df_by_sheet:
    st.info("Upload an Excel file to preview dashboard.")
    st.stop()

sheet = st.selectbox("Active Sheet for the dashboard:", list(st.session_state.df_by_sheet.keys()))
df = st.session_state.df_by_sheet[sheet].copy()

# Limit rows for front-end payload size (tunable)
MAX_ROWS = 5000
if len(df) > MAX_ROWS:
    df = df.head(MAX_ROWS)

# ---------- HTML Renderer ----------
DASH_HTML = """
<div id="app" style="display:flex;justify-content:center;">
  <div id="board" style="width:960px;aspect-ratio:16/9;border:1px solid #e9ecef;border-radius:12px;padding:12px;font-family:Inter, system-ui, -apple-system, Segoe UI, Roboto;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
      <h2 style="margin:6px 0;font-weight:600;">📊 Auto BI — Story Dashboard</h2>
      <div>
        <button id="btnReset" style="padding:6px 10px;border:1px solid #ddd;border-radius:8px;background:#fff;cursor:pointer;">Reset Filters</button>
        <button id="btnExport" style="padding:6px 10px;border:1px solid #ddd;border-radius:8px;background:#fff;cursor:pointer;">Export CSV</button>
      </div>
    </div>

    <!-- Story -->
    <div id="story" style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px;"></div>

    <!-- Filters -->
    <div id="filters" style="display:flex;gap:8px;flex-wrap:wrap;margin:6px 0;"></div>

    <!-- KPIs -->
    <div id="kpis" style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:6px 0;"></div>

    <!-- Sections -->
    <div id="sections" style="display:grid;grid-template-columns:1fr 1fr;gap:8px;"></div>
  </div>
</div>

<!-- ECharts -->
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<script>
(function(){
  const SPEC = window.DASH_SPEC;
  const RAW = window.DASH_DATA;

  // ---------- Helpers ----------
  const deepCopy = o => JSON.parse(JSON.stringify(o || {}));
  let data = deepCopy(RAW.rows);
  const columns = RAW.columns;
  let filters = {};   // { field: Set(values) }

  function uniqueValues(field){
    const set = new Set();
    data.forEach(r => { if(r[field] !== null && r[field] !== undefined) set.add(String(r[field])); });
    return Array.from(set).sort();
  }

  function applyFilters(){
    const keys = Object.keys(filters);
    if(keys.length === 0) return deepCopy(RAW.rows);
    return RAW.rows.filter(r => {
      return keys.every(f => {
        const v = r[f];
        if (v === null || v === undefined) return false;
        return filters[f].has(String(v));
      });
    });
  }

  function aggregate(rows, x, y, agg){
    agg = (agg || "sum").toLowerCase();
    const groups = {};
    rows.forEach(r => {
      const k = String(r[x]);
      const val = Number(r[y]);
      if(!(k in groups)) groups[k] = [];
      if(!isNaN(val)) groups[k].push(val);
    });
    const out = [];
    Object.entries(groups).forEach(([k, arr])=>{
      let v = 0;
      if(agg === "avg") v = arr.reduce((a,b)=>a+b,0)/arr.length;
      else if(agg === "min") v = Math.min(...arr);
      else if(agg === "max") v = Math.max(...arr);
      else if(agg === "count") v = arr.length;
      else if(agg === "distinct") v = new Set(arr).size;
      else v = arr.reduce((a,b)=>a+b,0);
      out.push({x:k,y:v});
    });
    return out.sort((a,b)=> (a.x > b.x ? 1 : -1));
  }

  function numberFormat(v){
    if (v === null || v === undefined || isNaN(v)) return "N/A";
    const abs = Math.abs(v);
    if (abs >= 1e9) return (v/1e9).toFixed(2)+"B";
    if (abs >= 1e6) return (v/1e6).toFixed(2)+"M";
    if (abs >= 1e3) return (v/1e3).toFixed(2)+"K";
    return new Intl.NumberFormat().format(v);
  }

  function toCSV(rows){
    const header = columns.join(",");
    const body = rows.map(r => columns.map(c => JSON.stringify(r[c] ?? "")).join(",")).join("\\n");
    return header + "\\n" + body;
  }

  // ---------- UI Builders ----------
  function buildStory(page){
    const host = document.getElementById("story");
    host.innerHTML = "";
    (page.Story || []).forEach(s=>{
      const card = document.createElement("div");
      card.style.padding="10px";
      card.style.border="1px solid #eee";
      card.style.borderRadius="10px";
      card.style.background="#fafafa";
      card.innerHTML = "<div style='font-weight:600;margin-bottom:4px;'>"+(s.section||"")+"</div><div style='opacity:0.8;font-size:12px;'>"+(s.text||"")+"</div>";
      host.appendChild(card);
    });
  }

  function buildFilters(page){
    const host = document.getElementById("filters");
    host.innerHTML = "";
    (page.Filters || []).forEach(f=>{
      const field = f.field;
      if (!columns.includes(field)) return;
      const wrap = document.createElement("div");
      wrap.style.border="1px solid #eee";
      wrap.style.borderRadius="8px";
      wrap.style.padding="6px 8px";
      const lab = document.createElement("div");
      lab.innerText = field;
      lab.style.fontSize="12px";
      lab.style.opacity="0.7";
      const sel = document.createElement("select");
      sel.multiple = true;
      sel.size = 4;
      sel.style.minWidth="150px";
      uniqueValues(field).forEach(v=>{
        const opt = document.createElement("option");
        opt.value = v; opt.innerText = v;
        sel.appendChild(opt);
      });
      sel.addEventListener("change", ()=>{
        const picks = Array.from(sel.selectedOptions).map(o=>o.value);
        if (picks.length) filters[field] = new Set(picks);
        else delete filters[field];
        renderPage(page);
      });
      wrap.appendChild(lab);
      wrap.appendChild(sel);
      host.appendChild(wrap);
    });
  }

  function buildKPIs(page){
    const host = document.getElementById("kpis");
    host.innerHTML = "";
    const rows = applyFilters();
    (page.KPIs || []).forEach(k=>{
      const card = document.createElement("div");
      card.style.border="1px solid #f0f0f0";
      card.style.borderRadius="10px";
      card.style.padding="10px";
      card.style.background="#fff";
      card.style.textAlign="center";
      let val="N/A";
      if (columns.includes(k.field)){
        const nums = rows.map(r=> Number(r[k.field])).filter(v=>!isNaN(v));
        if (nums.length){
          if (k.agg==="avg") val = nums.reduce((a,b)=>a+b,0)/nums.length;
          else if (k.agg==="min") val = Math.min(...nums);
          else if (k.agg==="max") val = Math.max(...nums);
          else if (k.agg==="count") val = nums.length;
          else if (k.agg==="distinct") val = new Set(nums).size;
          else val = nums.reduce((a,b)=>a+b,0);
          val = numberFormat(val);
        }
      }
      card.innerHTML = "<div style='font-size:12px;opacity:0.7;'>"+(k.title||k.field)+"</div><div style='font-size:22px;font-weight:700;'>"+val+"</div>";
      host.appendChild(card);
    });
  }

  function buildSections(page){
    const host = document.getElementById("sections");
    host.innerHTML = "";
    (page.Layout || []).forEach(sec=>{
      const secWrap = document.createElement("div");
      secWrap.style.gridColumn = "span 1";
      const title = document.createElement("div");
      title.innerText = sec.section || "Visuals";
      title.style.fontWeight = "600";
      title.style.margin = "6px 0";
      secWrap.appendChild(title);

      (sec.elements || []).forEach(el=>{
        const box = document.createElement("div");
        box.style.border="1px solid #eee";
        box.style.borderRadius="10px";
        box.style.background="#fff";
        box.style.padding="6px";
        box.style.marginBottom="8px";
        box.style.height="260px"; // 16:9 grid: two rows (approx), total ~540px
        const div = document.createElement("div");
        div.style.width="100%";
        div.style.height="100%";
        box.appendChild(div);
        secWrap.appendChild(box);

        if (el.type === "Table"){
          // simple table preview of filtered data (x,y only)
          const rows = applyFilters();
          const cols = [el.x, el.y].filter(Boolean).filter(c=>columns.includes(c));
          div.style.overflow="auto";
          const tbl = document.createElement("table");
          tbl.style.width="100%";
          tbl.style.borderCollapse="collapse";
          tbl.innerHTML = "<thead><tr>"+cols.map(c=>"<th style='text-align:left;border-bottom:1px solid #eee;padding:4px;'>"+c+"</th>").join("")+"</tr></thead>";
          const tb = document.createElement("tbody");
          rows.slice(0,100).forEach(r=>{
            const tr = document.createElement("tr");
            tr.innerHTML = cols.map(c=>"<td style='padding:4px;border-bottom:1px solid #fafafa;'>"+(r[c] ?? "")+"</td>").join("");
            tb.appendChild(tr);
          });
          tbl.appendChild(tb);
          div.appendChild(tbl);
        } else {
          // ECharts
          const chart = echarts.init(div, null, {renderer: 'canvas'});
          const rows = applyFilters();
          const x = el.x, y = el.y;
          const agg = (el.agg || "sum").toLowerCase();
          let series = [];
          let option = { grid: { left: 40, right: 20, top: 30, bottom: 40 } };

          if (el.type === "Pie"){
            const aggData = aggregate(rows, x, y, agg);
            option = {
              title: { text: "", left: "center" },
              tooltip: { trigger: 'item' },
              series: [{
                type: 'pie',
                radius: ['40%','70%'],
                data: aggData.map(d=>({name: d.x, value: d.y}))
              }]
            };
          } else {
            const aggData = aggregate(rows, x, y, agg);
            option = {
              tooltip: { trigger: 'axis' },
              xAxis: { type: 'category', data: aggData.map(d=>d.x) },
              yAxis: { type: 'value' },
              series: [{ type: (el.type || "Bar").toLowerCase(), data: aggData.map(d=>d.y) }]
            };
          }

          chart.setOption(option);

          // cross-filter on click (category)
          chart.on('click', params=>{
            if (!params || params.name==null) return;
            if (!filters[x]) filters[x] = new Set();
            const name = String(params.name);
            if (filters[x].has(name)) filters[x].delete(name); else filters[x].add(name);
            if (filters[x].size===0) delete filters[x];
            renderPage(page);
          });

          // resize on container changes
          new ResizeObserver(()=>chart.resize()).observe(div);
        }
      });

      host.appendChild(secWrap);
    });
  }

  function renderPage(page){
    // filtered data snapshot used by KPI/Charts
    data = applyFilters();
    buildStory(page);
    buildKPIs(page);
    buildSections(page);
  }

  // Toolbar
  document.getElementById("btnReset").addEventListener("click", ()=>{
    filters = {};
    renderPage(SPEC.Pages[0]);
  });
  document.getElementById("btnExport").addEventListener("click", ()=>{
    const rows = applyFilters();
    const csv = toCSV(rows);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], {type:"text/csv"}));
    a.download = 'filtered_data.csv';
    a.click();
  });

  // Init
  renderPage(SPEC.Pages[0] || {});
})();
</script>
"""

# ---- Send data + spec to HTML ----
spec_obj = json.loads(extract_json(st.session_state.spec))
active_page = (spec_obj.get("Pages") or [{}])[0]

# Make a JSON-friendly table for JS (no NaT, etc.)
def to_js_rows(df: pd.DataFrame):
    def conv(v):
        if pd.isna(v): return None
        if isinstance(v, (pd.Timestamp, pd.Timedelta)): return str(v)
        return v
    return [{col: conv(row[col]) for col in df.columns} for _, row in df.iterrows()]

payload = {
    "columns": list(df.columns),
    "rows": to_js_rows(df)
}

# Render
from streamlit.components.v1 import html as st_html
st_html(
    f"""
    <script>
      window.DASH_SPEC = {json.dumps(active_page, ensure_ascii=False)};
      window.DASH_DATA = {json.dumps(payload, ensure_ascii=False)};
    </script>
    {DASH_HTML}
    """,
    height=720,  # 16:9 container with outer padding
    scrolling=False
)
