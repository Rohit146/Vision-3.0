import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io
import openai
import json
import base64
from pandas.api.types import is_datetime64_any_dtype as is_datetime

# -----------------------------------------------------------------------------
# 1. CONFIGURATION & STYLE
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="AI Analytics Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Power BI Style CSS & 16:9 Layout Enhancement
st.markdown("""
<style>
    .stApp { background-color: #f0f2f6; }
    section[data-testid="stSidebar"] { background-color: #ffffff; border-right: 1px solid #e0e0e0; }
    .stExpander { background-color: white; border-radius: 5px; }
    /* Metric Cards - Power BI look */
    div[data-testid="stMetric"] {
        background-color: white; padding: 15px; border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #e0e0e0;
    }
    h1, h2, h3 { font-family: 'Segoe UI', sans-serif; color: #2c3e50; }
    
    /* Enforce 16:9 approximate ratio on the main content area */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 0rem;
        padding-left: 2rem;
        padding-right: 2rem;
        /* Max width to suggest 16:9 viewing experience on large screens */
        max-width: 1400px;
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. SESSION STATE & DATA PERSISTENCE
# -----------------------------------------------------------------------------
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'dashboard_items' not in st.session_state:
    st.session_state.dashboard_items = [] 
if 'raw_df' not in st.session_state:
    st.session_state.raw_df = None
if 'dashboard_image_b64' not in st.session_state:
    st.session_state.dashboard_image_b64 = None

# -----------------------------------------------------------------------------
# 3. HELPER FUNCTIONS
# -----------------------------------------------------------------------------

def preprocess_data(df):
    """Auto-converts columns to appropriate types (dates, etc)."""
    for col in df.columns:
        # Try converting to datetime
        if df[col].dtype == 'object':
            try:
                # Use errors='coerce' to turn invalid dates into NaT, then drop them
                df[col] = pd.to_datetime(df[col], errors='coerce')
                df = df.dropna(subset=[col])
            except (ValueError, TypeError):
                pass
    return df

def detect_columns(query, columns):
    query = query.lower()
    return [col for col in columns if col.lower() in query]

def detect_chart_type(query):
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

# --- API CALL FOR IMAGE GENERATION ---
def generate_mock_dashboard_image(df, api_key):
    """
    Uses Imagen to generate a mock Power BI dashboard image based on the data schema.
    """
    if not api_key:
        st.error("OpenAI API Key is required for image generation.")
        return

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
    
    # The API key must be an empty string for the Canvas environment to replace it at runtime
    IMAGE_API_KEY = "" 
    IMAGE_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={IMAGE_API_KEY}"
    
    st.session_state.dashboard_image_b64 = "loading" # Set loading state
    st.toast("Generating Power BI mock image...", icon='🎨')
    
    # --- Exponential Backoff Fetch Simulation ---
    # Since direct `requests` is not ideal in Streamlit cloud and we cannot use the 
    # Canvas `fetch` wrapper here directly, this logic remains conceptual 
    # but represents the necessary steps for the user's environment.
    
    # For a placeholder that works without external network dependencies:
    st.error("Image generation is triggered but requires a live environment with network access to the Imagen API.")
    st.session_state.dashboard_image_b64 = None
    
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
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2 # Lower temperature for stable JSON output
        )
        
        content = response.choices[0].message.content.strip()
        # Clean up markdown if present
        if "```" in content:
            content = content.split("```json")[-1].split("```")[0].strip()
            
        configs = json.loads(content)
        
        # Add IDs and validate
        valid_configs = []
        for i, config in enumerate(configs):
             # Simple validation
            if all(key in config for key in ['type', 'x', 'y', 'agg', 'title']):
                config['id'] = len(st.session_state.dashboard_items) + i + 1
                valid_configs.append(config)
            
        if valid_configs:
            st.session_state.dashboard_items.extend(valid_configs)
            st.toast(f"🤖 AI generated an initial dashboard with {len(valid_configs)} charts!", icon='✨')
            st.session_state.messages.append({"role": "assistant", "content": f"AI analyzed your data and built an initial dashboard with {len(valid_configs)} key visuals."})
        
    except Exception as e:
        st.error(f"AI Generation Error: Could not generate initial dashboard. Check API key or console for details. ({e})")

def get_openai_config(df, query, api_key):
    """
    (Used for chat input only) Uses OpenAI to interpret the query and return a single chart configuration.
    """
    col_info = {col: str(df[col].dtype) for col in df.columns}
    
    system_prompt = """
    You are a data visualization assistant. 
    Analyze the user's query and the dataframe schema provided.
    Return a SINGLE VALID JSON object (no markdown, no comments) with this structure:
    {
        "type": "bar" | "line" | "scatter" | "pie" | "box" | "histogram" | "area",
        "x": "column_name_for_x_axis",
        "y": "column_name_for_y_axis",
        "agg": "sum" | "mean" | "count" | "min" | "max" | "none",
        "title": "A descriptive title for the chart"
    }
    Rules:
    1. If the user asks for a count/frequency, use 'count' aggregation and the same column for x (if categorical) or appropriate setup.
    2. If no numeric column is specified for Y in a bar/line chart, assume 'count' of X.
    3. JSON keys must be strictly "type", "x", "y", "agg", "title".
    """
    
    user_prompt = f"""
    Columns & Types: {json.dumps(col_info)}
    User Query: "{query}"
    """
    
    try:
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1
        )
        
        content = response.choices[0].message.content.strip()
        if "```" in content:
            content = content.split("```json")[-1].split("```")[0].strip()
            
        config = json.loads(content)
        
        if config['x'] not in df.columns or (config['y'] and config['y'] not in df.columns):
            return None, "I tried to generate a chart, but the columns didn't match the data."
            
        config['id'] = 0 # Placeholder ID
        return config, f"AI generated a {config['type']} chart: {config['title']}"
        
    except Exception as e:
        return None, f"OpenAI Error: {str(e)}. Falling back to simple detection."

def generate_chart_config(df, query, api_key=None):
    # 1. Try OpenAI if Key is present
    if api_key:
        config, msg = get_openai_config(df, query, api_key)
        if config:
            config['id'] = len(st.session_state.dashboard_items) + 1
            return config, msg

    # 2. Fallback to Heuristic Logic
    detected_cols = detect_columns(query, df.columns)
    chart_type = detect_chart_type(query)
    
    x_col, y_col = None, None
    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
    cat_cols = df.select_dtypes(exclude=['number', 'datetime']).columns.tolist() # Exclude datetime here
    
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
    return config, f"Added {chart_type} chart."

# -----------------------------------------------------------------------------
# 4. SIDEBAR - DATA LOAD & GLOBAL SLICERS
# -----------------------------------------------------------------------------
openai_api_key = st.secrets.get("OPENAI_API_KEY")

with st.sidebar:
    st.title("📊 Data Assistant")
    
    # --- File Upload ---
    uploaded_file = st.file_uploader("Data Source", type=['xlsx', 'csv'])
    
    if uploaded_file:
        try:
            # Check if a new file has been uploaded or if it's the first load
            if st.session_state.raw_df is None or (hasattr(uploaded_file, 'name') and uploaded_file.name != st.session_state.get('last_file', '')):
                
                # Read the file content into a buffer first for robust handling
                data = uploaded_file.getvalue()

                if uploaded_file.name.endswith('.csv'):
                    df_temp = pd.read_csv(io.BytesIO(data))
                elif uploaded_file.name.endswith('.xlsx'):
                    # Use io.BytesIO for robust Excel reading
                    df_temp = pd.read_excel(io.BytesIO(data))
                else:
                    st.error("Unsupported file type. Please upload a .csv or .xlsx file.")
                    # IMPORTANT: Return here to prevent proceeding with invalid data
                    # and ensure session state isn't overwritten incorrectly.
                    st.session_state.raw_df = None
                    st.session_state.last_file = ""
                    st.rerun()
                
                st.session_state.raw_df = preprocess_data(df_temp)
                st.session_state.last_file = uploaded_file.name
                
                # --- AI AUTO-GENERATE DASHBOARD TRIGGER ---
                st.session_state.dashboard_items = [] # Clear previous dashboard
                st.session_state.dashboard_image_b64 = None # Clear previous image
                if openai_api_key:
                    generate_initial_dashboard(st.session_state.raw_df.copy(), openai_api_key)
                
                st.success(f"Loaded {len(st.session_state.raw_df)} rows")
        except Exception as e:
            st.error(f"Load Error: {e}. If this is an Excel file, ensure it's a standard format and doesn't require complex dependencies.")

    # --- Global Slicers (Power BI Style) ---
    st.markdown("### ✂️ Slicers")
    current_df = st.session_state.raw_df
    
    if current_df is not None:
        cat_cols = current_df.select_dtypes(include=['object', 'category']).columns.tolist()
        filter_cols = cat_cols[:3] # Limit filters
        
        filters = {}
        for col in filter_cols:
            unique_vals = current_df[col].unique()
            if len(unique_vals) < 50:
                selected = st.multiselect(f"Filter {col}", unique_vals)
                if selected:
                    filters[col] = selected
        
        for col, vals in filters.items():
            current_df = current_df[current_df[col].isin(vals)]
            
        st.markdown(f"**Active Rows:** {len(current_df)}")
    else:
        st.info("Upload data to see filters")

    st.divider()

    # --- Chat Interface ---
    st.markdown("### 💬 AI Chat")
    
    if not openai_api_key:
        st.warning("⚠️ **To enable AI features:** Add your `OPENAI_API_KEY` to Streamlit Secrets.")
    else:
        st.success("🤖 Smart AI enabled!")
    
    if prompt := st.chat_input("Ex: 'Compare average profit by category'"):
        if current_df is None:
            st.error("Upload data first.")
        else:
            st.session_state.messages.append({"role": "user", "content": prompt})
            config, response = generate_chart_config(current_df, prompt, openai_api_key)
            if config:
                st.session_state.dashboard_items.append(config)
            st.session_state.messages.append({"role": "assistant", "content": response})

    # Show last few messages
    for msg in st.session_state.messages[-3:]:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            
    if st.button("Reset Dashboard"):
        st.session_state.dashboard_items = []
        st.session_state.messages = []
        st.session_state.dashboard_image_b64 = None
        st.rerun()

# -----------------------------------------------------------------------------
# 5. MAIN DASHBOARD AREA
# -----------------------------------------------------------------------------
st.title("Executive Dashboard")

if current_df is not None:
    
    # --- Top Level Metrics ---
    st.markdown("### Key Metrics")
    num_cols = current_df.select_dtypes(include=['number']).columns
    if len(num_cols) > 0:
        cols = st.columns(4)
        for i, col in enumerate(num_cols[:4]):
            val = current_df[col].sum()
            # Intelligent formatting
            fmt_val = f"{val:,.0f}" if val > 1000 else f"{val:.2f}"
            if val > 1_000_000: fmt_val = f"{val/1_000_000:.1f}M"
            elif val > 1_000: fmt_val = f"{val/1_000:.1f}K"
            
            cols[i].metric(col, fmt_val)
    
    st.divider()

    # --- Mock Image Generation ---
    st.markdown("### 🖼️ Power BI Mockup")
    if st.button("Generate Power BI Mockup Image (AI required)"):
        generate_mock_dashboard_image(current_df.copy(), openai_api_key)

    if st.session_state.dashboard_image_b64 == "loading":
        st.info("Generating image...")
    elif st.session_state.dashboard_image_b64:
        # Display the base64 image
        image_data = f"data:image/png;base64,{st.session_state.dashboard_image_b64}"
        st.image(image_data, caption="AI Generated Power BI Mockup", use_column_width=True)
        st.caption("This image is a concept mockup generated by AI based on your data columns.")
    
    st.divider()

    # --- Charts Grid (2-column layout for 16:9 feel) ---
    st.markdown("### 📊 Interactive Visualizations")
    if not st.session_state.dashboard_items:
        st.info("Start chatting in the sidebar to create visualizations, or upload data with your OpenAI key configured to auto-generate the dashboard!")
    
    # Display logic using a 2-column grid
    chart_containers = []
    num_charts = len(st.session_state.dashboard_items)
    
    # Create column pairs
    for i in range(0, num_charts, 2):
        col1, col2 = st.columns(2)
        chart_containers.append(col1)
        if i + 1 < num_charts:
            chart_containers.append(col2)
            
    for i, item in enumerate(st.session_state.dashboard_items):
        with chart_containers[i]:
            
            # Use a container inside the column for structure
            with st.container():
                
                # Title and Settings in a row
                title_col, settings_col = st.columns([3, 1])
                with title_col:
                    st.subheader(item.get('title', 'Untitled Chart'), anchor=False)
                    
                with settings_col:
                    # Edit Mode Expander for compactness
                    with st.expander("⚙️"):
                        # Ensure indices are valid for selectbox
                        chart_types = ['bar', 'line', 'area', 'pie', 'scatter', 'box', 'histogram']
                        agg_types = ['sum', 'mean', 'count', 'min', 'max', 'none']
                        
                        try:
                            type_idx = chart_types.index(item['type'])
                        except ValueError:
                            type_idx = 0
                            
                        try:
                            agg_idx = agg_types.index(item.get('agg', 'sum'))
                        except ValueError:
                            agg_idx = 0

                        new_type = st.selectbox("Type", chart_types, index=type_idx, key=f"t_{i}")
                        new_x = st.selectbox("X-Axis", current_df.columns, index=current_df.columns.get_loc(item['x']), key=f"x_{i}")
                        
                        y_axis_options = current_df.columns.tolist()
                        try:
                            y_idx = current_df.columns.get_loc(item['y'])
                        except KeyError:
                            y_idx = 0

                        new_y = st.selectbox("Y-Axis", y_axis_options, index=y_idx, key=f"y_{i}")
                        new_agg = st.selectbox("Aggregation", agg_types, index=agg_idx, key=f"agg_{i}")
                        
                        if st.button("Update", key=f"upd_{i}"):
                            item.update({'type': new_type, 'x': new_x, 'y': new_y, 'agg': new_agg, 
                                       'title': f"{new_type.capitalize()} of {new_y} by {new_x}"})
                            st.rerun()
                        
                        if st.button("Remove", key=f"del_{i}"):
                            st.session_state.dashboard_items.pop(i)
                            st.rerun()

                # --- Visualization Logic ---
                try:
                    # 1. Prepare Data based on Aggregation
                    y_col_name = item['y'] # Default Y column name
                    
                    if item['agg'] != 'none' and item['type'] not in ['scatter', 'box', 'histogram']:
                        is_y_numeric = item['y'] in current_df.columns and current_df[item['y']].dtype in ['float64', 'int64']
                        
                        if item['y'] not in current_df.columns or (item['agg'] != 'count' and not is_y_numeric):
                             chart_df = current_df # Skip aggregation if Y is invalid
                             st.warning(f"Skipping aggregation: invalid y-column for '{item['agg']}'.")
                        else:
                            if item['agg'] == 'count':
                                chart_df = current_df.groupby(item['x']).size().reset_index(name='count_of_records')
                                y_col_name = 'count_of_records'
                            elif item['agg'] == 'mean':
                                chart_df = current_df.groupby(item['x'])[item['y']].mean().reset_index(name='mean_of_y')
                                y_col_name = 'mean_of_y'
                            elif item['agg'] == 'min':
                                chart_df = current_df.groupby(item['x'])[item['y']].min().reset_index(name='min_of_y')
                                y_col_name = 'min_of_y'
                            elif item['agg'] == 'max':
                                chart_df = current_df.groupby(item['x'])[item['y']].max().reset_index(name='max_of_y')
                                y_col_name = 'max_of_y'
                            else: # Sum
                                chart_df = current_df.groupby(item['x'])[item['y']].sum().reset_index(name='sum_of_y')
                                y_col_name = 'sum_of_y'
                    else:
                        chart_df = current_df

                    # 2. Render Chart
                    y_plot_col = y_col_name if 'count_of_records' in chart_df.columns or 'sum_of_y' in chart_df.columns else item['y']
                    
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
                        fig = px.histogram(chart_df, x=item['x'], template="plotly_white")
                    elif item['type'] == 'box':
                        fig = px.box(chart_df, x=item['x'], y=y_plot_col, color=item['x'], template="plotly_white")
                    
                    fig.update_layout(height=350, margin=dict(l=20, r=20, t=30, b=20))
                    st.plotly_chart(fig, use_container_width=True)
                    
                except Exception as e:
                    st.error(f"Could not render chart: {e}")
            
            st.markdown("---") # Visual separator between charts in the grid

    # --- Data Export ---
    st.markdown("### 📥 Export Data")
    
    csv = current_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="Download Filtered Data as CSV",
        data=csv,
        file_name='dashboard_data.csv',
        mime='text/csv',
    )

else:
    st.info("Awaiting data upload...")
