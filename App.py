import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io
import openai
import json

# -----------------------------------------------------------------------------
# 1. CONFIGURATION & STYLE
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="AI Analytics Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Power BI Style CSS
st.markdown("""
<style>
    .stApp { background-color: #f0f2f6; }
    section[data-testid="stSidebar"] { background-color: #ffffff; border-right: 1px solid #e0e0e0; }
    .stExpander { background-color: white; border-radius: 5px; }
    div[data-testid="stMetric"] {
        background-color: white; padding: 15px; border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #e0e0e0;
    }
    h1, h2, h3 { font-family: 'Segoe UI', sans-serif; color: #2c3e50; }
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

# -----------------------------------------------------------------------------
# 3. HELPER FUNCTIONS
# -----------------------------------------------------------------------------

def preprocess_data(df):
    """Auto-converts columns to appropriate types (dates, etc)."""
    for col in df.columns:
        # Try converting to datetime
        if df[col].dtype == 'object':
            try:
                df[col] = pd.to_datetime(df[col])
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

def get_openai_config(df, query, api_key):
    """
    Uses OpenAI to interpret the query and return a chart configuration.
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
        # Clean up markdown if present
        if "```" in content:
            content = content.split("```json")[-1].split("```")[0].strip()
            
        config = json.loads(content)
        
        # Validate columns exist to prevent hallucinations
        if config['x'] not in df.columns or (config['y'] and config['y'] not in df.columns):
            return None, "I tried to generate a chart, but the columns didn't match the data."
            
        # Add ID placeholder (will be set by caller)
        config['id'] = 0 
        
        return config, f"AI generated a {config['type']} chart: {config['title']}"
        
    except Exception as e:
        # In a real deployed app, this is crucial for debugging
        return None, f"OpenAI Error: {str(e)}. Falling back to simple detection."

def generate_chart_config(df, query, api_key=None):
    # 1. Try OpenAI if Key is present
    if api_key:
        config, msg = get_openai_config(df, query, api_key)
        if config:
            config['id'] = len(st.session_state.dashboard_items) + 1
            return config, msg

    # 2. Fallback to Heuristic Logic (Existing Code)
    detected_cols = detect_columns(query, df.columns)
    chart_type = detect_chart_type(query)
    
    x_col, y_col = None, None
    
    # Logic to guess X and Y based on data types
    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
    cat_cols = df.select_dtypes(exclude=['number']).columns.tolist()
    
    if len(detected_cols) >= 2:
        x_col, y_col = detected_cols[0], detected_cols[1]
        # Swap if Y is categorical and X is numeric (usually charts are Cat vs Num)
        if x_col in numeric_cols and y_col in cat_cols:
            x_col, y_col = y_col, x_col
    elif len(detected_cols) == 1:
        # If user says "Show Sales", assume Sales is Y, find a Date or Category for X
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
        'agg': 'sum' if chart_type not in ['scatter', 'box', 'histogram'] else 'none', # Default aggregation
        'title': f"{chart_type.capitalize()} of {y_col} by {x_col}"
    }
    return config, f"Added {chart_type} chart."

# -----------------------------------------------------------------------------
# 4. SIDEBAR - DATA LOAD & GLOBAL SLICERS
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("📊 Data Assistant")
    
    # --- File Upload ---
    uploaded_file = st.file_uploader("Data Source", type=['xlsx', 'csv'])
    
    if uploaded_file:
        try:
            if st.session_state.raw_df is None or (hasattr(uploaded_file, 'name') and uploaded_file.name != st.session_state.get('last_file', '')):
                if uploaded_file.name.endswith('.csv'):
                    df_temp = pd.read_csv(uploaded_file)
                else:
                    df_temp = pd.read_excel(uploaded_file)
                
                st.session_state.raw_df = preprocess_data(df_temp)
                st.session_state.last_file = uploaded_file.name
                st.success(f"Loaded {len(st.session_state.raw_df)} rows")
        except Exception as e:
            st.error(f"Load Error: {e}")

    # --- Global Slicers (Power BI Style) ---
    st.markdown("### ✂️ Slicers")
    current_df = st.session_state.raw_df
    
    if current_df is not None:
        # Auto-detect categorical columns for filtering
        cat_cols = current_df.select_dtypes(include=['object', 'category']).columns.tolist()
        # Limit to first 3 categorical columns to avoid sidebar clutter
        filter_cols = cat_cols[:3] 
        
        filters = {}
        for col in filter_cols:
            # Check unique values, if too many (>50), skip slicer to save memory/UI space
            unique_vals = current_df[col].unique()
            if len(unique_vals) < 50:
                selected = st.multiselect(f"Filter {col}", unique_vals)
                if selected:
                    filters[col] = selected
        
        # Apply Filters to create the 'Active' dataframe
        for col, vals in filters.items():
            current_df = current_df[current_df[col].isin(vals)]
            
        st.markdown(f"**Active Rows:** {len(current_df)}")
    else:
        st.info("Upload data to see filters")

    st.divider()

    # --- Chat Interface ---
    st.markdown("### 💬 AI Chat")
    
    # Check for OpenAI Key in Streamlit Secrets
    openai_api_key = st.secrets.get("OPENAI_API_KEY")
    if not openai_api_key:
        st.warning("⚠️ **To enable smart AI generation:** Add your `OPENAI_API_KEY` to Streamlit Secrets.")
    else:
        st.success("🤖 Smart AI enabled!")
    
    if prompt := st.chat_input("Ex: 'Sales by Region'"):
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
        st.session_session_items = []
        st.session_state.messages = []
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

    # --- Charts Grid ---
    if not st.session_state.dashboard_items:
        st.info("Start chatting in the sidebar to create visualizations!")
    
    # Display logic
    for i, item in enumerate(st.session_state.dashboard_items):
        # Create container for the card
        with st.container():
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.subheader(item.get('title', 'Untitled Chart'))
                
            with col2:
                # Edit Mode Expander
                with st.expander("⚙️ Settings"):
                    new_type = st.selectbox("Type", ['bar', 'line', 'area', 'pie', 'scatter', 'box', 'histogram'], 
                                          index=['bar', 'line', 'area', 'pie', 'scatter', 'box', 'histogram'].index(item['type']), key=f"t_{i}")
                    new_x = st.selectbox("X-Axis", current_df.columns, index=current_df.columns.get_loc(item['x']), key=f"x_{i}")
                    new_y = st.selectbox("Y-Axis", current_df.columns, index=current_df.columns.get_loc(item['y']), key=f"y_{i}")
                    new_agg = st.selectbox("Aggregation", ['sum', 'mean', 'count', 'min', 'max', 'none'], 
                                         index=['sum', 'mean', 'count', 'min', 'max', 'none'].index(item.get('agg', 'sum')), key=f"agg_{i}")
                    
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
                if item['agg'] != 'none' and item['type'] not in ['scatter', 'box', 'histogram']:
                    if item['agg'] == 'count':
                        chart_df = current_df.groupby(item['x'])[item['y']].count().reset_index()
                    elif item['agg'] == 'mean':
                        chart_df = current_df.groupby(item['x'])[item['y']].mean().reset_index()
                    elif item['agg'] == 'min':
                        chart_df = current_df.groupby(item['x'])[item['y']].min().reset_index()
                    elif item['agg'] == 'max':
                        chart_df = current_df.groupby(item['x'])[item['y']].max().reset_index()
                    else: # Sum
                        chart_df = current_df.groupby(item['x'])[item['y']].sum().reset_index()
                else:
                    chart_df = current_df

                # 2. Render Chart
                if item['type'] == 'bar':
                    fig = px.bar(chart_df, x=item['x'], y=item['y'], color=item['x'], template="plotly_white")
                elif item['type'] == 'line':
                    fig = px.line(chart_df, x=item['x'], y=item['y'], markers=True, template="plotly_white")
                elif item['type'] == 'area':
                    fig = px.area(chart_df, x=item['x'], y=item['y'], template="plotly_white")
                elif item['type'] == 'pie':
                    fig = px.pie(chart_df, names=item['x'], values=item['y'], hole=0.5, template="plotly_white")
                elif item['type'] == 'scatter':
                    fig = px.scatter(chart_df, x=item['x'], y=item['y'], color=item['x'], template="plotly_white")
                elif item['type'] == 'histogram':
                    fig = px.histogram(chart_df, x=item['x'], template="plotly_white")
                elif item['type'] == 'box':
                    fig = px.box(chart_df, x=item['x'], y=item['y'], color=item['x'], template="plotly_white")
                
                fig.update_layout(height=400, margin=dict(l=20, r=20, t=30, b=20))
                st.plotly_chart(fig, use_container_width=True)
                
            except Exception as e:
                st.error(f"Could not render chart: {e}")
            
            st.divider()

    # --- Data Export ---
    st.markdown("### 📥 Export Data")
    
    # Convert dataframe to CSV for download
    csv = current_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="Download Filtered Data as CSV",
        data=csv,
        file_name='dashboard_data.csv',
        mime='text/csv',
    )

else:
    st.info("Awaiting data upload...")
