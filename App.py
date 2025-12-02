import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io
import openai
import json
import base64
from pandas.api.types import is_datetime64_any_dtype as is_datetime
import time # Used for exponential backoff simulation (for API calls)

# -----------------------------------------------------------------------------
# 1. CONFIGURATION & STYLE
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
# 2. SESSION STATE MANAGEMENT
# -----------------------------------------------------------------------------
# Store chat history
if 'messages' not in st.session_state:
    st.session_state.messages = []
# Store dynamic chart configurations
if 'dashboard_items' not in st.session_state:
    st.session_state.dashboard_items = [] 
# Store the raw, unfiltered DataFrame
if 'raw_df' not in st.session_state:
    st.session_state.raw_df = None
# Store the base64 string of the AI-generated mock image
if 'dashboard_image_b64' not in st.session_state:
    st.session_state.dashboard_image_b64 = None
# Store the active filter selections for the slicers (CRITICAL for the fix)
if 'active_filters' not in st.session_state:
    st.session_state.active_filters = {}
# Track the last file name to detect new uploads
if 'last_file' not in st.session_state:
    st.session_state.last_file = ""

# -----------------------------------------------------------------------------
# 3. HELPER FUNCTIONS
# -----------------------------------------------------------------------------

def preprocess_data(df):
    """
    Auto-converts columns to appropriate types (dates) for better analysis.
    Drops rows where date conversion fails.
    """
    for col in df.columns:
        # Check if column is object type and likely a date
        if df[col].dtype == 'object':
            try:
                # Try converting to datetime, coercing errors to NaT
                df[col] = pd.to_datetime(df[col], errors='coerce')
                # Drop rows with NaT after conversion
                df = df.dropna(subset=[col])
            except (ValueError, TypeError):
                # Ignore if conversion fails or type is incompatible
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
    return 'bar' # Default chart type

def generate_mock_dashboard_image(df):
    """
    Conceptual function to call the Imagen API for dashboard mockup.
    The API key is retrieved from secrets (or assumed to be provided by environment).
    """
    # NOTE: In the Canvas environment, the API key for fetch calls is automatically
    # handled if left as an empty string.
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
    
    # Configuration for the Imagen model
    payload = {
        "instances": { "prompt": prompt },
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": "16:9" 
        }
    }
    
    st.session_state.dashboard_image_b64 = "loading" # Set loading state
    st.toast("Generating Power BI mock image...", icon='🎨')

    # --- Conceptual Network Call & Backoff Simulation ---
    # This structure relies on the environment's fetch hook
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # We assume the fetch call will be executed externally.
            # Use `st.warning` as a placeholder for the network action.
            st.warning(f"Attempting image generation (Attempt {attempt + 1}).")
            
            # The actual fetch call happens here (conceptual for this environment):
            # response = await fetch(IMAGE_API_URL, {method: 'POST', body: JSON.stringify(payload)})
            
            # Since we can't await network calls directly here, we use st.rerun() 
            # and rely on the state being updated externally upon success.
            st.rerun() 
            
            # Assuming success and state update
            break 

        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2**(attempt+1))
            else:
                st.session_state.dashboard_image_b64 = None
                st.error(f"Image generation failed after multiple attempts. Error: {e}")
    
    st.rerun() # Refresh to show status update


def generate_initial_dashboard(df, api_key):
    """
    Uses OpenAI to analyze the full schema and generate 3-5 diverse chart configs.
    This runs automatically after data upload.
    """
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
        # Initialize client with the API key from secrets
        client = openai.OpenAI(api_key=api_key)
        
        # --- API Call with JSON expectation ---
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2 
        )
        
        content = response.choices[0].message.content.strip()
        # Robust cleanup of markdown wrappers
        if "```" in content:
            content = content.split("```json")[-1].split("```")[0].strip()
            
        configs = json.loads(content)
        
        # Validate and add configurations to state
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
    """
    Generates a single chart configuration from a chat query, falling back to 
    heuristics if the API key is missing or the AI call is complex.
    """
    
    # 1. Fallback Heuristic Logic (Robust and always available)
    query_lower = query.lower()
    
    # Simple column detection
    detected_cols = [col for col in df.columns if col.lower() in query_lower]
    chart_type = detect_chart_type(query)
    
    x_col, y_col = None, None
    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
    cat_cols = df.select_dtypes(exclude=['number', 'datetime']).columns.tolist() 
    
    # Heuristic logic for assigning X and Y axes
    if len(detected_cols) >= 2:
        x_col, y_col = detected_cols[0], detected_cols[1]
        # Try to put categorical on X and numerical on Y for most charts
        if x_col in numeric_cols and y_col in cat_cols:
            x_col, y_col = y_col, x_col
    elif len(detected_cols) == 1:
        target = detected_cols[0]
        if target in numeric_cols:
            y_col = target
            x_col = cat_cols[0] if cat_cols else (numeric_cols[1] if len(numeric_cols)>1 else target)
        else: # Categorical or Datetime
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
# 4. SIDEBAR - DATA LOAD & SLICERS (GLOBAL FILTERS)
# -----------------------------------------------------------------------------
# Retrieve the API key from Streamlit secrets (or environment variable)
openai_api_key = st.secrets.get("OPENAI_API_KEY")

with st.sidebar:
    st.title("📊 Data Assistant")
    
    # --- File Upload ---
    uploaded_file = st.file_uploader("Data Source (CSV/XLSX)", type=['xlsx', 'csv'])
    
    if uploaded_file:
        try:
            # Check if a new file is uploaded
            if st.session_state.raw_df is None or (uploaded_file.name != st.session_state.last_file):
                
                data = uploaded_file.getvalue()
                if uploaded_file.name.endswith('.csv'):
                    df_temp = pd.read_csv(io.BytesIO(data))
                else:
                    df_temp = pd.read_excel(io.BytesIO(data))
                
                st.session_state.raw_df = preprocess_data(df_temp)
                st.session_state.last_file = uploaded_file.name
                
                # --- Reset State on New Upload ---
                st.session_state.dashboard_items = [] 
                st.session_state.dashboard_image_b64 = None 
                st.session_state.active_filters = {} # Reset filters
                
                # Trigger initial AI dashboard generation
                if openai_api_key:
                    generate_initial_dashboard(st.session_state.raw_df.copy(), openai_api_key)
                
                st.success(f"Loaded {len(st.session_state.raw_df)} total rows.")
        except Exception as e:
            st.error(f"Load Error: Could not read file. Details: {e}")
            st.session_state.raw_df = None
            st.session_state.last_file = ""

    # --- Global Slicers (Filters) ---
    st.markdown("### ✂️ Slicers")
    
    if st.session_state.raw_df is not None:
        raw_df_copy = st.session_state.raw_df.copy()
        
        # Select columns suitable for filtering (categorical columns with low cardinality)
        cat_cols = raw_df_copy.select_dtypes(include=['object', 'category']).columns.tolist()
        filter_cols = cat_cols[:4] # Display up to 4 categorical filters
        
        new_filters = {} 
        for col in filter_cols:
            unique_vals = raw_df_copy[col].unique().tolist()
            if len(unique_vals) < 50: # Avoid filters on columns with too many unique values
                
                # --- CRITICAL FIX IMPLEMENTATION ---
                # Check if this column is already filtered. If not, select ALL values by default.
                # This prevents the multiselect defaulting to [] and filtering out all rows.
                if col in st.session_state.active_filters and st.session_state.active_filters[col]:
                    # Use existing filter if available and non-empty
                    default_selection = st.session_state.active_filters[col]
                else:
                    # Default to selecting everything on first load or reset
                    default_selection = unique_vals 
                    
                selected = st.multiselect(
                    f"Filter by: **{col}**", 
                    unique_vals, 
                    default=default_selection,
                    key=f"filter_multiselect_{col}"
                )
                
                # Store the selection (even if empty, representing an explicit filter)
                new_filters[col] = selected
        
        # Update the session state with the new filters
        st.session_state.active_filters = new_filters
            
        # Calculate and display active rows
        temp_df_count = st.session_state.raw_df.copy()
        for col, vals in new_filters.items():
            if vals: # Only filter if selected values list is NOT empty
                 temp_df_count = temp_df_count[temp_df_count[col].isin(vals)]
            
        st.markdown(f"**Active Rows:** **{len(temp_df_count)}** (out of {len(st.session_state.raw_df)})")
    else:
        st.info("Upload data to enable slicers and dashboard features.")

    st.divider()

    # --- Chat Interface for AI Commands ---
    st.markdown("### 💬 AI Chat")
    
    if not openai_api_key:
        st.warning("⚠️ **AI Disabled:** Add your `OPENAI_API_KEY` to secrets for full functionality.")
    else:
        st.success("🤖 AI Chat and Auto-Generation Enabled!")
    
    # Process chat input
    if prompt := st.chat_input("Ex: 'Compare average profit by category'"):
        
        # 1. First, apply the filters to get the current working DataFrame
        temp_current_df = st.session_state.raw_df.copy() if st.session_state.raw_df is not None else None
        
        if temp_current_df is not None:
            # Apply active filters to the working DF
            for col, vals in st.session_state.active_filters.items():
                if vals:
                    temp_current_df = temp_current_df[temp_current_df[col].isin(vals)]
            
            st.session_state.messages.append({"role": "user", "content": prompt})
            
            # 2. Generate chart config
            config, response = generate_chart_config(temp_current_df, prompt, openai_api_key)
            
            # 3. Update state
            if config:
                st.session_state.dashboard_items.append(config)
            st.session_state.messages.append({"role": "assistant", "content": response})
            st.rerun()
        else:
            st.error("Please upload and process your data before using the AI chat.")

    # Show last few messages in the sidebar
    for msg in st.session_state.messages[-3:]:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            
    # Reset Button
    if st.button("🔄 Reset Dashboard"):
        st.session_state.dashboard_items = []
        st.session_state.messages = []
        st.session_state.dashboard_image_b64 = None
        st.session_state.active_filters = {}
        st.rerun()

# -----------------------------------------------------------------------------
# 4.5 Global Data Filtering (Executed outside sidebar)
# -----------------------------------------------------------------------------

# Start with raw data
current_df = st.session_state.raw_df.copy() if st.session_state.raw_df is not None else None

# Apply all active filters to get the final, working DataFrame (current_df)
if current_df is not None:
    filters = st.session_state.get('active_filters', {})
    for col, vals in filters.items():
        if vals and col in current_df.columns:
            current_df = current_df[current_df[col].isin(vals)]
            
# -----------------------------------------------------------------------------
# 5. MAIN DASHBOARD AREA - VISUALIZATIONS
# -----------------------------------------------------------------------------
st.title("Executive Dashboard")

if current_df is not None:
    
    # --- Top Level Metrics ---
    st.markdown("### Key Metrics")
    num_cols = current_df.select_dtypes(include=['number']).columns
    
    if len(num_cols) > 0:
        # Use up to 4 numerical columns for key metrics
        cols = st.columns(min(4, len(num_cols)))
        
        for i, col in enumerate(num_cols[:4]):
            val = current_df[col].sum()
            
            # Format value intelligently (Currency/Thousands/Millions)
            fmt_val = f"{val:,.0f}" 
            if val > 1_000_000: 
                fmt_val = f"${val/1_000_000:.1f}M"
            elif val > 1_000: 
                fmt_val = f"${val/1_000:,.1f}K"
            elif val < 1000: 
                fmt_val = f"${val:,.2f}"

            cols[i].metric(col, fmt_val)
    
    st.divider()

    # --- AI Mockup Image Section ---
    st.markdown("### 🖼️ Power BI Mockup")
    if st.button("Generate Power BI Mockup Image (AI required)"):
        # Image generation is triggered here
        generate_mock_dashboard_image(current_df.copy())

    if st.session_state.dashboard_image_b64 == "loading":
        st.info("Generating image...")
    elif st.session_state.dashboard_image_b64:
        # Display the base64 image (the result of the conceptual fetch call)
        image_data = f"data:image/png;base64,{st.session_state.dashboard_image_b64}"
        st.image(image_data, caption="AI Generated Power BI Mockup (Conceptual)", use_column_width=True)
        st.caption("The image is a concept generated by the AI to visualize the potential dashboard layout.")
    
    st.divider()

    # --- Interactive Charts Grid ---
    st.markdown("### 📊 Interactive Visualizations")
    if not st.session_state.dashboard_items:
        st.info("Ask the AI to generate charts (e.g., 'show a bar chart of sales by region') or upload data with your API key to auto-generate.")
    
    # Use a 2-column grid for standard dashboard layout
    chart_containers = []
    num_charts = len(st.session_state.dashboard_items)
    
    for i in range(0, num_charts, 2):
        # Create columns dynamically
        col1, col2 = st.columns(2)
        chart_containers.append(col1)
        if i + 1 < num_charts:
            chart_containers.append(col2)
            
    for i, item in enumerate(st.session_state.dashboard_items):
        with chart_containers[i]:
            
            # Visualization container
            with st.container():
                
                # Chart Title and Settings Header
                title_col, settings_col = st.columns([3, 1])
                with title_col:
                    st.subheader(item.get('title', 'Untitled Chart'), anchor=False)
                    
                with settings_col:
                    # Compact Expander for editing chart properties
                    with st.expander("⚙️"):
                        
                        # Options for editing
                        chart_types = ['bar', 'line', 'area', 'pie', 'scatter', 'box', 'histogram']
                        agg_types = ['sum', 'mean', 'count', 'min', 'max', 'none']
                        all_cols = current_df.columns.tolist()

                        # Safe indexing for selections
                        type_idx = chart_types.index(item['type']) if item['type'] in chart_types else 0
                        agg_idx = agg_types.index(item.get('agg', 'sum')) if item.get('agg') in agg_types else 0
                        x_idx = all_cols.index(item['x']) if item['x'] in all_cols else (all_cols.index(all_cols[0]) if all_cols else 0)
                        y_idx = all_cols.index(item['y']) if item['y'] in all_cols else (all_cols.index(all_cols[0]) if all_cols else 0)
                        
                        new_type = st.selectbox("Type", chart_types, index=type_idx, key=f"t_{i}")
                        new_x = st.selectbox("X-Axis", all_cols, index=x_idx, key=f"x_{i}")
                        new_y = st.selectbox("Y-Axis", all_cols, index=y_idx, key=f"y_{i}")
                        new_agg = st.selectbox("Aggregation", agg_types, index=agg_idx, key=f"agg_{i}")
                        
                        # Update and Remove buttons
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

                # --- Plotly Chart Rendering ---
                try:
                    # 1. Data Aggregation / Preparation
                    y_plot_col = item['y'] # Default Y column name
                    chart_df = current_df
                    
                    # Apply aggregation unless it's a raw plot type
                    if item['agg'] != 'none' and item['type'] not in ['scatter', 'box', 'histogram']:
                        is_y_numeric = item['y'] in current_df.columns and current_df[item['y']].dtype in ['float64', 'int64']
                        
                        if item['agg'] == 'count':
                            chart_df = current_df.groupby(item['x']).size().reset_index(name='count_of_records')
                            y_plot_col = 'count_of_records'
                        elif is_y_numeric:
                            # Apply the requested numerical aggregation
                            agg_func = {'sum': 'sum', 'mean': 'mean', 'min': 'min', 'max': 'max'}.get(item['agg'], 'sum')
                            name_suffix = agg_func
                            chart_df = current_df.groupby(item['x'])[item['y']].agg(agg_func).reset_index(name=f"{name_suffix}_of_{item['y']}")
                            y_plot_col = f"{name_suffix}_of_{item['y']}"
                        else:
                            # Fallback if non-count aggregation requested on non-numeric column
                            st.warning(f"Invalid Y-column type for '{item['agg']}'. Displaying raw data if possible.")

                    # 2. Render Plotly Figure
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
                        fig = px.histogram(current_df, x=item['x'], template="plotly_white") # Histograms typically use raw DF
                    elif item['type'] == 'box':
                        fig = px.box(chart_df, x=item['x'], y=y_plot_col, color=item['x'], template="plotly_white")
                    else:
                        st.warning(f"Unknown chart type: {item['type']}")
                        continue
                    
                    # Consistent height for a neat grid layout
                    fig.update_layout(height=350, margin=dict(l=20, r=20, t=30, b=20))
                    st.plotly_chart(fig, use_container_width=True)
                    
                except Exception as e:
                    # Catch rendering errors (e.g., column not found after update)
                    st.error(f"Visualization Error: Ensure X and Y columns are compatible for '{item['type']}'. Details: {e}")
            
            st.markdown("---") # Visual separator

    # --- Data Export ---
    st.markdown("### 📥 Export Data")
    
    csv = current_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="Download Filtered Data as CSV",
        data=csv,
        file_name='filtered_dashboard_data.csv',
        mime='text/csv',
    )

else:
    # Display message if no data is loaded
    st.info("""
    ## Welcome to the AI Analytics Dashboard!
    
    1. **Upload your Data** (CSV or XLSX) using the file uploader in the sidebar.
    2. **View Key Metrics** and the auto-generated dashboard (if API key is present).
    3. **Use Slicers** in the sidebar to filter the data.
    4. **Chat with the AI** to create new charts (e.g., "Line chart of revenue over time").
    """)
