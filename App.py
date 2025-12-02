# app.py
import streamlit as st
import pandas as pd
import plotly.express as px
import io
import time
import base64
from pandas.api.types import is_datetime64_any_dtype as is_datetime
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------
st.set_page_config(
    page_title="AI Power BI Mockup Generator",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stApp { background-color: #f0f2f6; font-family: 'Segoe UI', sans-serif; }
    div[data-testid="stMetric"] {
        background-color: #ffffff; padding: 15px; border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05); border: 1px solid #f0f0f0;
        transition: transform 0.2s;
    }
    div[data-testid="stMetric"]:hover { transform: translateY(-2px); }
    h1, h2, h3 { color: #2c3e50; }
    .block-container { padding: 1.5rem 2rem 2rem 2rem; max-width: 1400px; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------------------
if 'raw_df' not in st.session_state:
    st.session_state.raw_df = None
if 'dashboard_image_b64' not in st.session_state:
    st.session_state.dashboard_image_b64 = None
if 'last_file' not in st.session_state:
    st.session_state.last_file = ""
if 'generating' not in st.session_state:
    st.session_state.generating = False

# ---------------------------------------------------------------------
# UTILITIES
# ---------------------------------------------------------------------
def preprocess_data(df: pd.DataFrame) -> pd.DataFrame:
    """Try converting object columns to datetime where reasonable without dropping many rows."""
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == 'object':
            # Try to parse datetimes
            parsed = pd.to_datetime(df[col], errors='coerce', dayfirst=False)
            # If less than ~40% nulls after parse, accept conversion
            if parsed.notna().sum() / max(1, len(parsed)) > 0.6:
                df[col] = parsed
            # else leave as object
    return df

def try_read_csv(data_buffer: io.BytesIO):
    """Try multiple separators and encodings to read CSV. Returns DataFrame or None."""
    separators = [',', ';', '\t', '|']
    encodings = ['utf-8', 'latin1', 'iso-8859-1']

    for encoding in encodings:
        for sep in separators:
            data_buffer.seek(0)
            try:
                df = pd.read_csv(data_buffer, encoding=encoding, sep=sep, skipinitialspace=True)
                if df.shape[0] > 0 and df.shape[1] > 0:
                    st.info(f"Loaded with sep='{sep}', enc='{encoding}'.")
                    return df
            except Exception:
                continue

    # Try header=None fallback
    for encoding in encodings:
        for sep in separators:
            data_buffer.seek(0)
            try:
                df = pd.read_csv(data_buffer, encoding=encoding, sep=sep, skipinitialspace=True, header=None)
                if df.shape[0] > 1 and df.shape[1] > 0:
                    df.columns = [f"Col_{i+1}" for i in range(df.shape[1])]
                    st.info(f"Fallback loaded with header=None, sep='{sep}', enc='{encoding}'.")
                    return df
            except Exception:
                continue
    return None

def get_detailed_data_summary(df: pd.DataFrame) -> str:
    """Return a human-readable summary (for prompt/UI)."""
    lines = [f"Total Rows: {len(df):,}", f"Total Columns: {df.shape[1]}"]
    for col in df.columns:
        dtype = str(df[col].dtype)
        if is_datetime(df[col]):
            rng_min = df[col].min()
            rng_max = df[col].max()
            lines.append(f"- {col} ({dtype}): date range {rng_min.date() if pd.notna(rng_min) else 'NA'} to {rng_max.date() if pd.notna(rng_max) else 'NA'}")
        elif df[col].dtype.kind in 'fiu':
            lines.append(f"- {col} ({dtype}): numeric; mean={df[col].mean():.2f} median={df[col].median():.2f} nulls={df[col].isna().sum()}")
        else:
            nuniq = df[col].nunique(dropna=True)
            if nuniq <= 10:
                top = df[col].value_counts(dropna=True).nlargest(3).to_dict()
                lines.append(f"- {col} ({dtype}): categorical; {nuniq} unique; top={top}")
            else:
                lines.append(f"- {col} ({dtype}): text/identifier; {nuniq} unique")
    return "\n".join(lines)

def create_placeholder_image(prompt_text: str, title: str = "AI Power BI Mockup", size=(1280, 720)):
    """Create a simple placeholder PNG image with the prompt text using Pillow and return base64 string."""
    img = Image.new("RGB", size, color=(11,61,145))  # deep-blue background
    draw = ImageDraw.Draw(img)
    # Title
    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 40)
        font_body = ImageFont.truetype("DejaVuSans.ttf", 16)
    except Exception:
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()

    margin = 40
    draw.text((margin, margin), title, fill=(255,255,255), font=font_title)
    # Render a clipped prompt area on right/below
    # Wrap prompt_text to lines
    max_w = size[0] - margin*2
    lines = []
    words = prompt_text.replace("\n", " ").split()
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textsize(test, font=font_body)[0] <= max_w:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)

    y = margin + 70
    # limit lines to avoid overflow
    for i, line in enumerate(lines[:30]):
        draw.text((margin, y + i*20), line, fill=(230,230,230), font=font_body)

    # small footer
    draw.text((margin, size[1]-30), "Placeholder generated locally — replace with real image API call.", fill=(200,200,200), font=font_body)

    # save to bytes
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
    return b64

def generate_mock_dashboard_image(df: pd.DataFrame):
    """Build prompt summary and create placeholder image (base64) — replaceable by real API call."""
    st.session_state.generating = True
    with st.spinner("Building prompt and generating mockup..."):
        time.sleep(0.6)  # simulate work
        summary = get_detailed_data_summary(df)
        prompt = f"Power BI executive dashboard. Data summary:\n{summary}\n\nLayout: title, 3 KPI cards, grid of charts, slicers on left. Style: modern, dark blue/grey. Aspect ratio 16:9."
        # In a real setup: call your image generation API here and set dashboard_image_b64 accordingly.
        # For now create a local placeholder image:
        image_b64 = create_placeholder_image(prompt, title="AI Power BI Mockup (Conceptual)")
        st.session_state.dashboard_image_b64 = image_b64
        st.session_state.generating = False

# ---------------------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------------------
with st.sidebar:
    st.title("🎨 Mockup Generator")
    uploaded_file = st.file_uploader("Data Source (CSV / XLSX)", type=['csv', 'xlsx'], help="Upload CSV or XLSX. Large files may take longer.")
    if uploaded_file:
        try:
            data = uploaded_file.getvalue()
            df_temp = None
            if uploaded_file.name.lower().endswith('.csv'):
                df_temp = try_read_csv(io.BytesIO(data))
            else:
                # excel
                df_temp = pd.read_excel(io.BytesIO(data))
            if df_temp is None or df_temp.shape[0] == 0:
                st.error("Could not parse file. Try different CSV format or open in Excel and re-export.")
                st.session_state.raw_df = None
                st.session_state.last_file = ""
            else:
                df_clean = preprocess_data(df_temp)
                st.session_state.raw_df = df_clean
                st.session_state.last_file = uploaded_file.name
                st.session_state.dashboard_image_b64 = None
                st.success(f"Loaded {len(df_clean):,} rows × {df_clean.shape[1]} cols from `{uploaded_file.name}`")
        except Exception as e:
            st.error(f"Load Error: {e}")
            st.session_state.raw_df = None
            st.session_state.last_file = ""

    st.divider()
    if st.session_state.raw_df is not None:
        if st.button("Generate New Mockup", type="primary"):
            generate_mock_dashboard_image(st.session_state.raw_df.copy())

        if st.button("Clear Data & Reset"):
            st.session_state.raw_df = None
            st.session_state.dashboard_image_b64 = None
            st.session_state.last_file = ""
            st.session_state.generating = False
            st.experimental_rerun()

# ---------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------
st.title("AI Power BI Mockup Generator")
st.markdown("Upload data then click **Generate New Mockup**. The app auto-suggests chart widgets and builds a conceptual Power BI mockup image.")

if st.session_state.raw_df is not None:
    df = st.session_state.raw_df.copy()
    st.markdown("#### Dataset preview")
    st.dataframe(df.head(200))

    st.markdown("#### Quick auto-suggested visuals (you can choose columns to preview)")
    col1, col2 = st.columns([1,1])
    with col1:
        dt_cols = [c for c in df.columns if is_datetime(df[c])]
        if dt_cols:
            date_col = st.selectbox("Choose date column for trend (if any)", options=dt_cols, index=0)
        else:
            date_col = None
            st.info("No datetime-like columns detected.")
    with col2:
        num_cols = [c for c in df.columns if df[c].dtype.kind in 'fiu']
        cat_cols = [c for c in df.columns if df[c].dtype == 'object' or (df[c].nunique() < 200 and df[c].dtype == 'category')]
        if num_cols:
            y_col = st.selectbox("Choose numeric column for aggregation", options=num_cols, index=0)
        else:
            y_col = None
            st.info("No numeric columns detected.")

    # Render a sample chart if possible
    if date_col and y_col:
        st.markdown("##### Time Series sample")
        try:
            df_ts = df[[date_col, y_col]].dropna().sort_values(date_col)
            fig = px.line(df_ts, x=date_col, y=y_col, title=f"{y_col} over {date_col}")
            st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.error(f"Could not render time series: {e}")

    elif len(num_cols) >= 1 and cat_cols:
        st.markdown("##### Category vs Numeric (sample)")
        try:
            fig = px.bar(df.groupby(cat_cols[0])[num_cols[0]].sum().reset_index().nlargest(20, num_cols[0]), x=cat_cols[0], y=num_cols[0], title=f"{num_cols[0]} by {cat_cols[0]}")
            st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.error(f"Could not render category chart: {e}")

    st.divider()
    st.markdown("### 🖼️ Generated Power BI Mockup")
    if st.session_state.generating:
        st.info("Generating mockup — please wait...")
    elif st.session_state.dashboard_image_b64:
        # Show image from base64
        b64 = st.session_state.dashboard_image_b64
        image_bytes = base64.b64decode(b64)
        st.image(image_bytes, caption="AI Generated Power BI Mockup (Conceptual)", use_column_width=True)
        with st.expander("View / download prompt used for generation"):
            prompt_text = get_detailed_data_summary(df)
            st.code(prompt_text)
            # downloadable prompt txt
            b = prompt_text.encode('utf-8')
            b64_prompt = base64.b64encode(b).decode()
            href = f'<a href="data:file/txt;base64,{b64_prompt}" download="mockup_prompt.txt">Download prompt (.txt)</a>'
            st.markdown(href, unsafe_allow_html=True)

        with st.expander("Export image"):
            st.download_button("Download PNG", data=image_bytes, file_name="mockup.png", mime="image/png")
    else:
        st.warning("Click the 'Generate New Mockup' button in the sidebar to visualize your data.")
else:
    st.info("""
    ## Ready to Visualize?
    Upload CSV or XLSX to the left. The app will:
    - auto-detect datetimes and numerics,
    - show quick sample visual previews,
    - generate a conceptual Power BI mockup image (placeholder — replace with your image API call).
    """)

# ---------------------------------------------------------------------
# END
# ---------------------------------------------------------------------
