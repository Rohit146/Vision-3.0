import pandas as pd

def apply_filters(df, filters):
    for col, vals in filters.items():
        if col in df.columns and vals:
            df = df[df[col].astype(str).isin(vals)]
    return df

def calc_kpi(df, expr):
    val = 0
    try:
        if expr.startswith("SUM("): col = expr[4:-1]; val = df[col].sum()
        elif expr.startswith("AVG("): col = expr[4:-1]; val = df[col].mean()
        elif expr.startswith("COUNT("): col = expr[6:-1]; val = df[col].count()
    except Exception:
        pass
    return val

def format_val(v, fmt):
    if fmt == "pct": return f"{v*100:.2f}%"
    if fmt == "currency": return f"₹{v:,.0f}"
    if isinstance(v,float): return f"{v:,.0f}"
    return str(v)
