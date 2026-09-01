import io
import pytest
from job_radar.ai.pdf_builder import build_resume_pdf

def test_build_resume_pdf_12_sections():
    profile = {
        "full_name": "Dr. Elena Rostova",
        "email": "elena@research.org",
        "location": "Boston, MA",
        "section_order": [
            {"type": "summary", "label": "Executive Summary"},
            {"type": "skills", "label": "Skills"},
            {"type": "experience", "label": "Experience"},
            {"type": "education", "label": "Education"},
            {"type": "publications", "label": "Selected Publications"},
            {"type": "awards", "label": "Honors"},
            {"type": "languages", "label": "Languages"}
        ]
    }

    output_json = {
        "sections": [
            {
                "type": "summary",
                "label": "Executive Summary",
                "items": "AI Research Scientist specializing in foundation models."
            },
            {
                "type": "skills",
                "label": "Skills",
                "items": ["PyTorch", "JAX", "Transformers", "Distributed Training"]
            },
            {
                "type": "experience",
                "label": "Experience",
                "items": [
                    {
                        "title": "Principal Researcher",
                        "company": "Deep Labs",
                        "start": "2021",
                        "end": "Present",
                        "bullets": ["Trained 70B parameter LLM on 4,096 H100 GPUs with 98% efficiency."]
                    }
                ]
            },
            {
                "type": "education",
                "label": "Education",
                "items": [{"institution": "Harvard University", "degree": "Ph.D. Computer Science", "year": "2021"}]
            },
            {
                "type": "publications",
                "label": "Selected Publications",
                "items": [{"title": "Scaling Laws for Agentic Architectures", "venue": "NeurIPS", "year": "2024"}]
            },
            {
                "type": "awards",
                "label": "Honors",
                "items": [{"title": "Best Paper Award", "issuer": "ICML", "year": "2023"}]
            },
            {
                "type": "languages",
                "label": "Languages",
                "items": [{"language": "English", "proficiency": "Native"}, {"language": "French", "proficiency": "Fluent"}]
            }
        ]
    }

    pdf_bytes = build_resume_pdf(profile, output_json, format_type="own")
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 2000
    assert pdf_bytes.startswith(b"%PDF")
