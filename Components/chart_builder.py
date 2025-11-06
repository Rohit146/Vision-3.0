import streamlit as st

def add_element_ui(df_columns):
    st.subheader("➕ Add new element")
    el_type = st.selectbox("Element type", ["KPI","Chart","Table"])
    if el_type == "KPI":
        col = st.selectbox("Column", df_columns)
        agg = st.selectbox("Aggregation", ["SUM","AVG","COUNT"])
        fmt = st.selectbox("Format", ["auto","currency","pct"])
        return {"type":"KPI","expr":f"{agg}({col})","format":fmt,"title":f"{agg} of {col}"}
    elif el_type == "Chart":
        x = st.selectbox("X-axis", df_columns)
        y = st.selectbox("Y-axis", df_columns)
        chart_t = st.selectbox("Chart type", ["bar","line","pie"])
        return {"type":"Chart","x":x,"y":y,"chart":chart_t}
    elif el_type == "Table":
        cols = st.multiselect("Columns", df_columns)
        return {"type":"Table","cols":cols}
    return None
