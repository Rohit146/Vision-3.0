import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io
import openai
import json
import base64
from pandas.api.types import is_datetime64_any_dtype as is_datetime
import time 

# -----------------------------------------------------------------------------
# 1. CONFIGURATION & STYLE (No changes here)
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="AI Analytics Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for a clean, Power BI-inspired look and responsive layout
st.markdown("""
<style>
    /* Main Background & Font */
    .stApp { background-color: #f0f2f6; font-family: 'Segoe UI', sans-serif; }
    
    /* Sidebar Styling */
    section[data-testid="stSidebar"] { 
        background-color: #ffffff; 
        border-right: 1px solid #e0e0e0; 
        box-shadow: 2px 0 5px rgba(0,0,0,0.05);
    }
    
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
    
    /* Main Content Area Layout (Aids 16:9 feel) */
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 0rem;
        padding-left: 2rem;
        padding-right: 2rem;
        max-width: 1400px;
    }
    
    /* Fix for Plotly figure height alignment in columns */
    .stPlotlyChart {
        min-height: 350px;
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. SESSION STATE MANAGEMENT (No changes here)
# -----------------------------------------------------------------------------
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'dashboard_items' not in st.session_state:
    st.session_state.dashboard_items = [] 
if 'raw_df' not in st.session_state:
    st.session_state.raw_df = None
if 'dashboard_image_b64' not in st.session_state:
    st.session_state.dashboard_image_b64 = None
if 'active_filters' not in st.session_state:
    st.session_state.active_filters = {}
if 'last_file' not in st.session_state:
    st.session_state.last_file = ""

# -----------------------------------------------------------------------------
# 3. HELPER FUNCTIONS (API and Chart logic unchanged)
# -----------------------------------------------------------------------------

def preprocess_data(df):
    """
    Auto-converts columns to appropriate types (dates) for better analysis.
    Drops rows where date conversion fails.
    """
    for col in df.columns:
        if df[col].dtype == 'object':
            try:
                df[col] = pd.to_datetime(df[col], errors='coerce')
                df = df.dropna(subset=[col])
            except (ValueError, TypeError):
                pass
    return df

def detect_chart_type(query):
    """Simple heuristic to detect chart type from query."""
    query = query.lower()
    mapping = {
        'line': 'line', 'trend': 'line', 'time': 'line',
        'pie': 'pie', 'share': 'pie', 'distribution': 'pie',
        'scatter': 'scatter', 'relation': 'scatter',
        'bar': 'bar', 'column': 'bar', 'compare': 'bar',
        'box': 'box', 'outlier': 'box',
        'hist': 'histogram', 'frequency': 'histogram',
        'area': 'area'
    }
    for key, value in mapping.items():
        if key in query:
            return value
    return 'bar' 

def generate_mock_dashboard_image(df):
    """Conceptual function to call the Imagen API for dashboard mockup."""
    IMAGE_API_KEY = "" 
    IMAGE_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={IMAGE_API_KEY}"
    
    col_info = {}
    for col in df.columns:
        dtype = str(df[col].dtype)
        if is_datetime(df[col]):
            dtype = 'datetime'
        col_info[col] = dtype
    
    prompt = f"""
    A realistic and professional Power BI executive dashboard visualization containing 3 to 4 charts (KPI cards, bar chart, line chart, and a pie chart) based on a dataset with the following columns and types: {json.dumps(col_info)}. The style should be modern, clean, 16:9 aspect ratio, blue and grey color scheme.
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

    max_retries = 3
    for attempt in range(max_retries):
        try:
            st.warning(f"Attempting image generation (Attempt {attempt + 1}).")
            st.rerun() 
            break 

        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2**(attempt+1))
            else:
                st.session_state.dashboard_image_b64 = None
                st.error(f"Image generation failed after multiple attempts. Error: {e}")
    
    st.rerun() 


def generate_initial_dashboard(df, api_key):
    """Uses OpenAI to analyze the full schema and generate 4 diverse chart configs."""
    if not api_key:
        st.warning("Cannot auto-generate dashboard: OpenAI API Key not found.")
        return

    col_info = {}
    for col in df.columns:
        dtype = str(df[col].dtype)
        if is_datetime(df[col]):
            dtype = 'datetime'
        elif df[col].nunique() < 10 and df[col].dtype == 'object':
            dtype = 'categorical (low cardinality)'
        col_info[col] = dtype
    
    system_prompt = """
    You are a world-class Business Intelligence analyst. Your task is to analyze the provided DataFrame schema (columns and data types) and suggest 4 highly relevant, diverse, and insightful chart configurations that form a cohesive executive dashboard.

    Return a SINGLE VALID JSON ARRAY (no markdown, no comments, no external text) of chart configuration objects.

    Structure for EACH object in the array:
    {
        "type": "bar" | "line" | "scatter" | "pie" | "box" | "histogram" | "area",
        "x": "column_name_for_x_axis",
        "y": "column_name_for_y_axis",
        "agg": "sum" | "mean" | "count" | "min" | "max" | "none",
        "title": "A descriptive, insightful title for the chart"
    }

    Rules for Chart Generation:
    1. Always use 'line' chart for time-based analysis (if a 'datetime' column exists).
    2. Always use 'sum' aggregation for columns like 'Sales', 'Revenue', or 'Profit'.
    3. Use 'count' for key categorical comparisons (e.g., 'Count of Orders by Region').
    4. Ensure the columns selected for X and Y exist in the schema.
    5. The final output must be only the JSON array.
    """
    
    user_prompt = f"""
    Generate a 4 chart dashboard configuration for this dataset schema: {json.dumps(col_info)}
    """
    
    try:
        client = openai.OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2 
        )
        
        content = response.choices[0].message.content.strip()
        if "```" in content:
            content = content.split("```json")[-1].split("```")[0].strip()
            
        configs = json.loads(content)
        
        valid_configs = []
        for i, config in enumerate(configs):
            if all(key in config for key in ['type', 'x', 'y', 'agg', 'title']) and \
               config['x'] in df.columns.tolist() and config['y'] in df.columns.tolist():
                config['id'] = len(st.session_state.dashboard_items) + i + 1
                valid_configs.append(config)
            
        if valid_configs:
            st.session_state.dashboard_items.extend(valid_configs)
            st.toast(f"🤖 AI generated an initial dashboard with {len(valid_configs)} charts!", icon='✨')
            st.session_state.messages.append({"role": "assistant", "content": f"AI analyzed your data and built an initial dashboard with {len(valid_configs)} key visuals."})
        
    except Exception as e:
        st.error(f"AI Generation Error: Could not generate initial dashboard. Check API key or console for details. ({e})")

def generate_chart_config(df, query, api_key=None):
    """Generates a single chart configuration from a chat query."""
    
    query_lower = query.lower()
    detected_cols = [col for col in df.columns if col.lower() in query_lower]
    chart_type = detect_chart_type(query)
    
    x_col, y_col = None, None
    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
    cat_cols = df.select_dtypes(exclude=['number', 'datetime']).columns.tolist() 
    
    if len(detected_cols) >= 2:
        x_col, y_col = detected_cols[0], detected_cols[1]
        if x_col in numeric_cols and y_col in cat_cols:
            x_col, y_col = y_col, x_col
    elif len(detected_cols) == 1:
        target = detected_cols[0]
        if target in numeric_cols:
            y_col = target
            x_col = cat_cols[0] if cat_cols else (numeric_cols[1] if len(numeric_cols)>1 else target)
        else: 
            x_col = target
            y_col = numeric_cols[0] if numeric_cols else target
    else:
        return None, "I couldn't identify specific columns. Please mention column names."

    chart_id = len(st.session_state.dashboard_items) + 1
    
    config = {
        'id': chart_id,
        'type': chart_type,
        'x': x_col,
        'y': y_col,
        'agg': 'sum' if chart_type not in ['scatter', 'box', 'histogram'] else 'none',
        'title': f"{chart_type.capitalize()} of {y_col} by {x_col}"
    }
    return config, f"Added a {chart_type} chart comparing {x_col} and {y_col}."

# -----------------------------------------------------------------------------
# 4. SIDEBAR - DATA LOAD & SLICERS (CRITICAL FIXES HERE)
# -----------------------------------------------------------------------------
openai_api_key = st.secrets.get("OPENAI_API_KEY")

def try_read_csv(data_buffer):
    """Tries multiple delimiters, encodings, and header settings to robustly read the CSV."""
    separators = [',', ';', '\t', '|']
    encodings = ['utf-8', 'latin1', 'iso-8859-1']
    
    # 1. Attempt standard read (assuming header row, strict check: > 0 rows and > 1 column)
    for encoding in encodings:
        for sep in separators:
            data_buffer.seek(0) # Reset buffer position
            try:
                # Try with header (default)
                df = pd.read_csv(data_buffer, encoding=encoding, sep=sep, skipinitialspace=True)
                if df.shape[0] > 0 and df.shape[1] > 1:
                    st.toast(f"Success! Loaded with sep='{sep}', enc='{encoding}', header=0.", icon='🎉')
                    return df
            except Exception:
                continue
    
    # 2. If attempt 1 fails, attempt read with no header (critical fallback)
    for encoding in encodings:
        for sep in separators:
            data_buffer.seek(0) # Reset buffer position
            try:
                # Try explicitly setting header=None
                df = pd.read_csv(data_buffer, encoding=encoding, sep=sep, skipinitialspace=True, header=None)
                # If we get > 1 row and > 1 column, we've successfully loaded the data
                if df.shape[0] > 1 and df.shape[1] > 1: 
                    # Rename columns for clean state
                    df.columns = [f"Col_{i+1}" for i in range(df.shape[1])]
                    st.toast(f"Fallback Success! Loaded with sep='{sep}', enc='{encoding}', **header=None**.", icon='✅')
                    return df
            except Exception:
                continue
                
    return None

with st.sidebar:
    st.title("📊 Data Assistant")
    
    # --- File Upload ---
    uploaded_file = st.file_uploader("Data Source (CSV/XLSX)", type=['xlsx', 'csv'])
    
    if uploaded_file:
        try:
            if st.session_state.raw_df is None or (uploaded_file.name != st.session_state.last_file):
                
                data = uploaded_file.getvalue()
                df_temp = None

                if uploaded_file.name.endswith('.csv'):
                    # Use the robust CSV reader
                    df_temp = try_read_csv(io.BytesIO(data))
                else:
                    # Use standard Excel reader
                    df_temp = pd.read_excel(io.BytesIO(data))
                
                # Check if data loading was successful
                if df_temp is not None and df_temp.shape[0] > 0:
                    st.session_state.raw_df = preprocess_data(df_temp)
                    st.session_state.last_file = uploaded_file.name
                    
                    st.session_state.dashboard_items = [] 
                    st.session_state.dashboard_image_b64 = None 
                    st.session_state.active_filters = {} 

                    if openai_api_key:
                        generate_initial_dashboard(st.session_state.raw_df.copy(), openai_api_key)
                    
                    st.success(f"Loaded {len(st.session_state.raw_df)} total rows.")
                else:
                    st.error("Data loading failed: File is empty or could not be parsed with any standard configuration (delimiter/encoding/header). Please ensure your CSV is correctly formatted.")
                    st.session_state.raw_df = None
                    st.session_state.last_file = ""

        except Exception as e:
            st.error(f"Load Error: Could not read file. Details: {e}")
            st.session_state.raw_df = None
            st.session_state.last_file = ""

    # --- Global Slicers (Filters) ---
    st.markdown("### ✂️ Slicers")
    
    if st.session_state.raw_df is not None:
        raw_df_copy = st.session_state.raw_df.copy()
        
        cat_cols = raw_df_copy.select_dtypes(include=['object', 'category']).columns.tolist()
        filter_cols = cat_cols[:4] 
        
        new_filters = {} 
        for col in filter_cols:
            unique_vals = raw_df_copy[col].unique().tolist()
            if len(unique_vals) < 50:
                
                # CRITICAL FIX: Default to selecting ALL values on first load/reset
                if col in st.session_state.active_filters and st.session_state.active_filters[col]:
                    default_selection = st.session_state.active_filters[col]
                else:
                    default_selection = unique_vals 
                    
                selected = st.multiselect(
                    f"Filter by: **{col}**", 
                    unique_vals, 
                    default=default_selection,
                    key=f"filter_multiselect_{col}"
                )
                
                new_filters[col] = selected
        
        st.session_state.active_filters = new_filters
            
        temp_df_count = st.session_state.raw_df.copy()
        for col, vals in new_filters.items():
            if vals: 
                 temp_df_count = temp_df_count[temp_df_count[col].isin(vals)]
            
        st.markdown(f"**Active Rows:** **{len(temp_df_count)}** (out of {len(st.session_state.raw_df)})")
    else:
        st.info("Upload data to enable slicers and dashboard features.")

    st.divider()

    # --- Chat Interface for AI Commands (Logic unchanged) ---
    st.markdown("### 💬 AI Chat")
    
    if not openai_api_key:
        st.warning("⚠️ **AI Disabled:** Add your `OPENAI_API_KEY` to secrets for full functionality.")
    else:
        st.success("🤖 AI Chat and Auto-Generation Enabled!")
    
    if prompt := st.chat_input("Ex: 'Compare average profit by category'"):
        
        temp_current_df = st.session_state.raw_df.copy() if st.session_state.raw_df is not None else None
        
        if temp_current_df is not None:
            for col, vals in st.session_state.active_filters.items():
                if vals:
                    temp_current_df = temp_current_df[temp_current_df[col].isin(vals)]
            
            st.session_state.messages.append({"role": "user", "content": prompt})
            
            config, response = generate_chart_config(temp_current_df, prompt, openai_api_key)
            
            if config:
                st.session_state.dashboard_items.append(config)
            st.session_state.messages.append({"role": "assistant", "content": response})
            st.rerun()
        else:
            st.error("Please upload and process your data before using the AI chat.")

    for msg in st.session_state.messages[-3:]:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            
    if st.button("🔄 Reset Dashboard"):
        st.session_state.dashboard_items = []
        st.session_state.messages = []
        st.session_state.dashboard_image_b64 = None
        st.session_state.active_filters = {}
        st.rerun()

# -----------------------------------------------------------------------------
# 4.5 Global Data Filtering 
# -----------------------------------------------------------------------------

current_df = st.session_state.raw_df.copy() if st.session_state.raw_df is not None else None

if current_df is not None:
    filters = st.session_state.get('active_filters', {})
    for col, vals in filters.items():
        if vals and col in current_df.columns:
            current_df = current_df[current_df[col].isin(vals)]
            
# -----------------------------------------------------------------------------
# 5. MAIN DASHBOARD AREA - VISUALIZATIONS (Logic unchanged)
# -----------------------------------------------------------------------------
st.title("Executive Dashboard")

if current_df is not None:
    
    st.markdown("### Key Metrics")
    num_cols = current_df.select_dtypes(include=['number']).columns
    
    if len(num_cols) > 0:
        cols = st.columns(min(4, len(num_cols)))
        
        for i, col in enumerate(num_cols[:4]):
            val = current_df[col].sum()
            
            fmt_val = f"{val:,.0f}" 
            if val > 1_000_000: 
                fmt_val = f"${val/1_000_000:.1f}M"
            elif val > 1_000: 
                fmt_val = f"${val/1_000:,.1f}K"
            elif val < 1000: 
                fmt_val = f"${val:,.2f}"

            cols[i].metric(col, fmt_val)
    
    st.divider()

    st.markdown("### 🖼️ Power BI Mockup")
    if st.button("Generate Power BI Mockup Image (AI required)"):
        generate_mock_dashboard_image(current_df.copy())

    if st.session_state.dashboard_image_b64 == "loading":
        st.info("Generating image...")
    elif st.session_state.dashboard_image_b64:
        image_data = f"data:image/png;base64,{st.session_state.dashboard_image_b64}"
        st.image(image_data, caption="AI Generated Power BI Mockup (Conceptual)", use_column_width=True)
        st.caption("The image is a concept generated by the AI to visualize the potential dashboard layout.")
    
    st.divider()

    st.markdown("### 📊 Interactive Visualizations")
    if not st.session_state.dashboard_items:
        st.info("Ask the AI to generate charts (e.g., 'show a bar chart of sales by region') or upload data with your API key to auto-generate.")
    
    chart_containers = []
    num_charts = len(st.session_state.dashboard_items)
    
    for i in range(0, num_charts, 2):
        col1, col2 = st.columns(2)
        chart_containers.append(col1)
        if i + 1 < num_charts:
            chart_containers.append(col2)
            
    for i, item in enumerate(st.session_state.dashboard_items):
        with chart_containers[i]:
            
            with st.container():
                
                title_col, settings_col = st.columns([3, 1])
                with title_col:
                    st.subheader(item.get('title', 'Untitled Chart'), anchor=False)
                    
                with settings_col:
                    with st.expander("⚙️"):
                        
                        chart_types = ['bar', 'line', 'area', 'pie', 'scatter', 'box', 'histogram']
                        agg_types = ['sum', 'mean', 'count', 'min', 'max', 'none']
                        all_cols = current_df.columns.tolist()

                        type_idx = chart_types.index(item['type']) if item['type'] in chart_types else 0
                        agg_idx = agg_types.index(item.get('agg', 'sum')) if item.get('agg') in agg_types else 0
                        x_idx = all_cols.index(item['x']) if item['x'] in all_cols else (all_cols.index(all_cols[0]) if all_cols else 0)
                        y_idx = all_cols.index(item['y']) if item['y'] in all_cols else (all_cols.index(all_cols[0]) if all_cols else 0)
                        
                        new_type = st.selectbox("Type", chart_types, index=type_idx, key=f"t_{i}")
                        new_x = st.selectbox("X-Axis", all_cols, index=x_idx, key=f"x_{i}")
                        new_y = st.selectbox("Y-Axis", all_cols, index=y_idx, key=f"y_{i}")
                        new_agg = st.selectbox("Aggregation", agg_types, index=agg_idx, key=f"agg_{i}")
                        
                        col_upd, col_del = st.columns(2)
                        with col_upd:
                            if st.button("Update", key=f"upd_{i}"):
                                item.update({'type': new_type, 'x': new_x, 'y': new_y, 'agg': new_agg, 
                                            'title': f"{new_type.capitalize()} of {new_y} by {new_x}"})
                                st.rerun()
                        with col_del:
                            if st.button("Remove", key=f"del_{i}"):
                                st.session_state.dashboard_items.pop(i)
                                st.rerun()

                try:
                    y_plot_col = item['y'] 
                    chart_df = current_df
                    
                    if item['agg'] != 'none' and item['type'] not in ['scatter', 'box', 'histogram']:
                        is_y_numeric = item['y'] in current_df.columns and current_df[item['y']].dtype in ['float64', 'int64']
                        
                        if item['agg'] == 'count':
                            chart_df = current_df.groupby(item['x']).size().reset_index(name='count_of_records')
                            y_plot_col = 'count_of_records'
                        elif is_y_numeric:
                            agg_func = {'sum': 'sum', 'mean': 'mean', 'min': 'min', 'max': 'max'}.get(item['agg'], 'sum')
                            name_suffix = agg_func
                            chart_df = current_df.groupby(item['x'])[item['y']].agg(agg_func).reset_index(name=f"{name_suffix}_of_{item['y']}")
                            y_plot_col = f"{name_suffix}_of_{item['y']}"
                        else:
                            st.warning(f"Invalid Y-column type for '{item['agg']}'. Displaying raw data if possible.")

                    if item['type'] == 'bar':
                        fig = px.bar(chart_df, x=item['x'], y=y_plot_col, color=item['x'], template="plotly_white")
                    elif item['type'] == 'line':
                        fig = px.line(chart_df, x=item['x'], y=y_plot_col, markers=True, template="plotly_white")
                    elif item['type'] == 'area':
                        fig = px.area(chart_df, x=item['x'], y=y_plot_col, template="plotly_white")
                    elif item['type'] == 'pie':
                        fig = px.pie(chart_df, names=item['x'], values=y_plot_col, hole=0.5, template="plotly_white")
                    elif item['type'] == 'scatter':
                        fig = px.scatter(chart_df, x=item['x'], y=y_plot_col, color=item['x'], template="plotly_white")
                    elif item['type'] == 'histogram':
                        fig = px.histogram(current_df, x=item['x'], template="plotly_white") 
                    elif item['type'] == 'box':
                        fig = px.box(chart_df, x=item['x'], y=y_plot_col, color=item['x'], template="plotly_white")
                    else:
                        continue
                    
                    fig.update_layout(height=350, margin=dict(l=20, r=20, t=30, b=20))
                    st.plotly_chart(fig, use_container_width=True)
                    
                except Exception as e:
                    st.error(f"Visualization Error: Ensure X and Y columns are compatible for '{item['type']}'. Details: {e}")
            
            st.markdown("---") 

    st.markdown("### 📥 Export Data")
    
    csv = current_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="Download Filtered Data as CSV",
        data=csv,
        file_name='filtered_dashboard_data.csv',
        mime='text/csv',
    )

else:
    st.info("""
    ## Welcome to the AI Analytics Dashboard!
    
    1. **Upload your Data** (CSV or XLSX) using the file uploader in the sidebar.
    2. **View Key Metrics** and the auto-generated dashboard (if API key is present).
    3. **Use Slicers** in the sidebar to filter the data.
    4. **Chat with the AI** to create new charts (e.g., "Line chart of revenue over time").
    """)
