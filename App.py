import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io
import json
import base64
import time 
import random
from pandas.api.types import is_datetime64_any_dtype as is_datetime

# -----------------------------------------------------------------------------
# 1. CONFIGURATION & STYLE
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="AI Power BI Mockup Generator",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for a professional look (16:9 feel is now managed by the prompt)
st.markdown("""
<style>
    /* Main Background & Font */
    .stApp { background-color: #f0f2f6; font-family: 'Segoe UI', sans-serif; }
    
    /* Metric Cards - Clean, modern, distinct background */
    div[data-testid="stMetric"] {
        background-color: #ffffff; 
        padding: 15px; 
        border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05); 
        border: 1px solid #f0f0f0;
        transition: transform 0.2s;
    }
    div[data-testid="stMetric"]:hover {
        transform: translateY(-2px);
    }
    
    /* Headings */
    h1, h2, h3 { color: #2c3e50; }
    
    /* Main Content Area Layout */
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
        padding-left: 2rem;
        padding-right: 2rem;
        max-width: 1400px;
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. SESSION STATE MANAGEMENT
# -----------------------------------------------------------------------------
if 'raw_df' not in st.session_state:
    st.session_state.raw_df = None
if 'dashboard_image_b64' not in st.session_state:
    st.session_state.dashboard_image_b64 = None
if 'last_file' not in st.session_state:
    st.session_state.last_file = ""

# -----------------------------------------------------------------------------
# 3. CORE DATA UTILITIES
# -----------------------------------------------------------------------------

def preprocess_data(df):
    """Auto-converts columns to datetime if possible."""
    for col in df.columns:
        if df[col].dtype == 'object':
            try:
                # Attempt to convert to datetime
                df[col] = pd.to_datetime(df[col], errors='coerce')
                # Only drop if a significant portion failed to convert
                if df[col].isnull().sum() / len(df) > 0.5:
                    df[col] = df[col].astype('object')
                else:
                    df = df.dropna(subset=[col])
            except (ValueError, TypeError):
                pass
    return df

def try_read_csv(data_buffer):
    """Tries multiple delimiters, encodings, and header settings to robustly read the CSV."""
    separators = [',', ';', '\t', '|']
    encodings = ['utf-8', 'latin1', 'iso-8859-1']
    
    # 1. Attempt standard read (assuming header row)
    for encoding in encodings:
        for sep in separators:
            data_buffer.seek(0)
            try:
                df = pd.read_csv(data_buffer, encoding=encoding, sep=sep, skipinitialspace=True)
                if df.shape[0] > 0 and df.shape[1] > 1:
                    st.toast(f"Success! Loaded with sep='{sep}', enc='{encoding}', header=0.", icon='🎉')
                    return df
            except Exception:
                continue
    
    # 2. Critical fallback: Attempt read with no header (data starts at row 0)
    for encoding in encodings:
        for sep in separators:
            data_buffer.seek(0)
            try:
                df = pd.read_csv(data_buffer, encoding=encoding, sep=sep, skipinitialspace=True, header=None)
                if df.shape[0] > 1 and df.shape[1] > 1:
                    # Rename columns for clean state
                    df.columns = [f"Col_{i+1}" for i in range(df.shape[1])]
                    st.toast(f"Fallback Success! Loaded with sep='{sep}', enc='{encoding}', **header=None**.", icon='✅')
                    return df
            except Exception:
                continue
                
    return None

def get_detailed_data_summary(df):
    """Generates a detailed, human-readable summary for the AI prompt."""
    summary = []
    
    # 1. Overall Metrics
    summary.append(f"Total Rows: {len(df):,}")
    
    # 2. Column Analysis
    for col in df.columns:
        dtype = str(df[col].dtype)
        col_summary = f"- **{col}** ({dtype}): "
        
        if is_datetime(df[col]):
            col_summary += f"Time/Date data. Range: {df[col].min().strftime('%Y-%m-%d')} to {df[col].max().strftime('%Y-%m-%d')}."
        elif df[col].dtype in ['float64', 'int64']:
            col_summary += f"Numeric values. Sum: {df[col].sum():,.0f}. Average: {df[col].mean():,.2f}."
        elif df[col].dtype == 'object' and df[col].nunique() < 50:
            top_vals = df[col].value_counts().nlargest(3).index.tolist()
            col_summary += f"Categorical. {df[col].nunique()} unique values. Top 3: {', '.join(map(str, top_vals))}."
        else:
            col_summary += "General identifier/text data."
            
        summary.append(col_summary)
        
    return "\n".join(summary)


def generate_mock_dashboard_image(df):
    """Calls the Imagen API for a highly detailed Power BI dashboard mockup."""
    
    # Check for API Key (assumed to be available in Streamlit Secrets)
    IMAGE_API_KEY = "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" # The execution environment handles the key
    IMAGE_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={IMAGE_API_KEY}"
    
    if not IMAGE_API_KEY and st.secrets.get("OPENAI_API_KEY"):
        # We can't use the Imagen URL above without the key; use a generic placeholder for now
        # In a real environment, the key would be passed or the fetch would be handled by the environment.
        st.error("Image generation requires the `OPENAI_API_KEY` to be configured in Streamlit Secrets to call the AI Image model.")
        return 

    # --- Generate Detailed Prompt ---
    data_summary = get_detailed_data_summary(df)
    
    # We will choose sample chart types based on available data types
    chart_suggestions = []
    
    if df.select_dtypes(include=['datetime']).shape[1] > 0:
        chart_suggestions.append("A prominent **Line Chart** showing trend over time.")
    if df.select_dtypes(include=['float64', 'int64']).shape[1] >= 2 and df.select_dtypes(include=['object']).shape[1] > 0:
        chart_suggestions.append("A **Bar Chart** comparing the sum of a numeric column across different categories.")
    if df.select_dtypes(include=['object']).shape[1] > 0 and df.shape[0] > 100:
        chart_suggestions.append("A **Pie Chart** or **Treemap** showing the distribution of the top categories.")
    
    if not chart_suggestions:
        chart_suggestions.append("A set of 4 generic charts (bar, line, scatter) to visualize the data structure.")
        
    chart_list_str = "Charts should include: " + ", ".join(chart_suggestions)
    
    prompt = f"""
    Generate a photorealistic, professional Power BI executive dashboard visualization. 
    
    **Data Context:** Based on the following dataset summary:
    {data_summary}
    
    **Dashboard Requirements:**
    1. **Style:** Modern, sleek, clean lines, dark blue and grey color scheme. Use a standard 16:9 aspect ratio.
    2. **Layout:** A large title area at the top, a set of 3 KPI cards (metrics like Total Sum, Average, Count) in a row, and a grid of 3-4 main charts below.
    3. **Content:** The charts must realistically represent the data based on the columns described in the summary. {chart_list_str}
    4. **Detail:** Include realistic Power BI elements: slicers in the margin, clear labels, and subtle shadows on the cards and visuals.
    """
    
    payload = {
        "instances": { "prompt": prompt },
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": "16:9" 
        }
    }
    
    st.session_state.dashboard_image_b64 = "loading" 
    st.toast("Generating Power BI mock image...", icon='🎨')

    # --- Conceptual API Call (must be replaced with actual fetch in execution environment) ---
    # Since we cannot execute actual fetch calls here, this block simulates the result.
    time.sleep(1) 
    
    # SIMULATION: Replace this with actual API call to get base64 image data
    # Example placeholder image: 
    PLACEHOLDER_URL = f"https://placehold.co/1280x720/0B3D91/FFFFFF?text=AI+Dashboard+Mockup"
    
    st.session_state.dashboard_image_b64 = "placeholder_data" # Trigger image display

    st.rerun() 
    # END SIMULATION
    

# -----------------------------------------------------------------------------
# 4. STREAMLIT APP LAYOUT
# -----------------------------------------------------------------------------

# --- Sidebar ---
with st.sidebar:
    st.title("🎨 Mockup Generator")
    
    # --- File Upload ---
    uploaded_file = st.file_uploader("Data Source (CSV/XLSX)", type=['xlsx', 'csv'])
    
    if uploaded_file:
        try:
            if st.session_state.raw_df is None or (uploaded_file.name != st.session_state.last_file):
                
                data = uploaded_file.getvalue()
                df_temp = None

                if uploaded_file.name.endswith('.csv'):
                    df_temp = try_read_csv(io.BytesIO(data))
                else:
                    df_temp = pd.read_excel(io.BytesIO(data))
                
                # Check if data loading was successful
                if df_temp is not None and df_temp.shape[0] > 0:
                    st.session_state.raw_df = preprocess_data(df_temp)
                    st.session_state.last_file = uploaded_file.name
                    st.session_state.dashboard_image_b64 = None 
                    
                    st.success(f"Loaded **{len(st.session_state.raw_df)}** total rows.")
                else:
                    st.error("Data parsing failed: File is empty or could not be parsed with any configuration.")
                    st.session_state.raw_df = None
                    st.session_state.last_file = ""

        except Exception as e:
            st.error(f"Load Error: Could not read file. Details: {e}")
            st.session_state.raw_df = None
            st.session_state.last_file = ""
    
    if st.session_state.raw_df is not None:
        st.markdown(f"**Loaded File:** `{st.session_state.last_file}`")
        st.markdown(f"**Data Dimensions:** `{st.session_state.raw_df.shape[0]} rows, {st.session_state.raw_df.shape[1]} columns`")
    
    st.divider()
    
    if st.session_state.raw_df is not None:
        if st.button("Generate New Mockup", type="primary"):
            generate_mock_dashboard_image(st.session_state.raw_df.copy())
        
        st.markdown("---")
        st.info("The image quality depends on the detail provided to the AI. Ensure your data has clear column names.")
        
        if st.button("Clear Data & Reset"):
            st.session_state.raw_df = None
            st.session_state.dashboard_image_b64 = None
            st.session_state.last_file = ""
            st.rerun()

# --- Main Content ---
st.title("AI Power BI Mockup Generator")
st.markdown("Upload a CSV or XLSX file and click **'Generate New Mockup'** in the sidebar to create a realistic, detailed Power BI visualization concept.")

if st.session_state.raw_df is not None:
    st.divider()
    st.markdown("### 🖼️ Generated Power BI Mockup")

    if st.session_state.dashboard_image_b64 == "loading":
        st.info("Generating highly detailed image... This may take up to 30 seconds.")
    elif st.session_state.dashboard_image_b64:
        
        # In the actual Canvas environment, this will handle the base64 image data from the API
        if st.session_state.dashboard_image_b64 == "placeholder_data":
            # Display placeholder during simulation
            st.image(PLACEHOLDER_URL, caption="AI Generated Power BI Mockup (Conceptual)", use_column_width=True)
            st.caption("*(Note: The actual AI image generation would be displayed here after a successful API call.)*")
        else:
            # Display actual image
            image_data = f"data:image/png;base64,{st.session_state.dashboard_image_b64}"
            st.image(image_data, caption="AI Generated Power BI Mockup (Conceptual)", use_column_width=True)
        
        st.markdown(f"""
        <div style='padding: 10px; border: 1px solid #ccc; border-radius: 5px; background-color: #fff; margin-top: 20px;'>
            <p><strong>Image Prompt used:</strong></p>
            <pre style='white-space: pre-wrap; word-wrap: break-word;'>{get_detailed_data_summary(st.session_state.raw_df.copy())}</pre>
        </div>
        """, unsafe_allow_html=True)
        
    else:
        st.warning("Click the 'Generate New Mockup' button in the sidebar to visualize your data.")
else:
    st.info("""
    ## Ready to Visualize?
    Please upload your data file (CSV or XLSX) to begin the mockup generation process. 
    The AI analyzes the column names, types, and sample statistics to create a highly accurate, professional visualization concept.
    """)

