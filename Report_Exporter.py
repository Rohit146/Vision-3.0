from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import tempfile

def export_pdf(content):
    styles = getSampleStyleSheet()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    doc = SimpleDocTemplate(tmp.name, pagesize=A4)
    story = [Paragraph("AI Business Mockup Report", styles['Title']), Spacer(1, 12)]
    story += [Paragraph(line, styles['Normal']) for line in content.split("\n")]
    doc.build(story)
    return tmp.name
