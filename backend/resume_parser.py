from PyPDF2 import PdfReader
from gemini_helper import analyze_resume

def extract_text_from_resume(filepath):
    if filepath.endswith('.pdf'):
        reader = PdfReader(filepath)
        return " ".join(page.extract_text() for page in reader.pages)
    # Add DOCX handling here
    return ""

def process_resume(filepath):
    text = extract_text_from_resume(filepath)
    return analyze_resume(text)  # Uses Gemini AI
