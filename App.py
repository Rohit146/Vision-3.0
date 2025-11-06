import streamlit as st
from data_handler import load_excel, generate_data_profile
from mockup_generator import generate_mockup
from visualizer import suggest_chart
from report_exporter import export_pdf

st.set_page_config(page_title="AI Business Mockup Chatbot", layout="wide")
st.title("💼 AI Business Mockup Chatbot")

st.sidebar.header("⚙️ Settings")
role = st.sidebar.selectbox(
    "Select Role Mode",
    ["Business Analyst", "Procurement Specialist", "Finance Planner", "Operations Manager"]
)
uploaded_file = st.sidebar.file_uploader("📂 Upload Excel file", type=["xlsx","xls"])

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if uploaded_file:
    excel_data = load_excel(uploaded_file)
    profile = generate_data_profile(excel_data)

    with st.expander("🔍 View Data Summary"):
        st.text(profile)

    user_prompt = st.text_area("💬 Your prompt", placeholder="e.g., Create a spend analysis dashboard...")
    if st.button("🚀 Generate Mockup") and user_prompt:
        context = f"Data summary:\n{profile}\n\nUser prompt:\n{user_prompt}"
        response = generate_mockup(context, role)
        st.session_state.chat_history.append({"user": user_prompt, "bot": response})

    for chat in st.session_state.chat_history:
        st.markdown(f"**You:** {chat['user']}")
        st.markdown(f"**{role} AI:** {chat['bot']}")
        st.markdown("---")

    with st.expander("📊 Generate Chart Mockups"):
        sheet_name = st.selectbox("Select Sheet", list(excel_data.keys()))
        suggest_chart(excel_data[sheet_name])

    if st.button("📄 Export Report"):
        content = "\n\n".join([c['bot'] for c in st.session_state.chat_history])
        pdf_path = export_pdf(content)
        with open(pdf_path, "rb") as f:
            st.download_button("⬇️ Download Report PDF", f, "mockup_report.pdf")
else:
    st.info("Upload an Excel file in the sidebar to start.")
