import pytest
from job_radar.resume.ats_scorer import compute_ats_score, extract_keywords

def test_ats_scorer_reproducibility():
    input_data = {
        "resumeText": """
        Jane Doe
        jane@example.com | (555) 123-4567 | San Francisco, CA

        PROFESSIONAL SUMMARY
        Senior Backend Engineer with 6+ years building distributed cloud platforms in Go, Python, and Kubernetes.

        TECHNICAL SKILLS
        Go, Python, Kubernetes, Docker, PostgreSQL, Redis, AWS, gRPC

        EXPERIENCE
        Senior Backend Engineer | Cloud Scale Inc (2021 – Present)
        • Architected real-time streaming pipeline processing 250k events/sec with 99.99% availability.
        • Reduced database query latency by 45% through Redis caching and query indexing.
        • Led migration of 15 microservices from EC2 to Kubernetes, saving $120k annually.

        EDUCATION
        B.S. in Computer Science | UC Berkeley (2018)
        """,
        "parsedData": {
            "full_name": "Jane Doe",
            "job_titles": ["Senior Backend Engineer", "Backend Engineer"],
            "skills": ["Go", "Python", "Kubernetes", "Docker", "PostgreSQL", "Redis", "AWS", "gRPC"],
            "experience": [
                {
                    "title": "Senior Backend Engineer",
                    "company": "Cloud Scale Inc",
                    "start": "2021",
                    "end": "Present",
                    "highlights": [
                        "Architected real-time streaming pipeline processing 250k events/sec with 99.99% availability.",
                        "Reduced database query latency by 45% through Redis caching and query indexing.",
                        "Led migration of 15 microservices from EC2 to Kubernetes, saving $120k annually."
                    ]
                }
            ],
            "education": [
                {"institution": "UC Berkeley", "degree": "B.S. in Computer Science", "year": "2018"}
            ]
        },
        "job": {
            "title": "Senior Backend Engineer",
            "company": "Stripe",
            "description": "We are seeking a Senior Backend Engineer proficient in Go, Kubernetes, and PostgreSQL to scale high-throughput payment infrastructure.",
            "skills": ["Go", "Kubernetes", "PostgreSQL", "Redis", "Distributed Systems"],
            "must_haves": ["Go", "Kubernetes", "PostgreSQL"]
        }
    }

    res1 = compute_ats_score(input_data)
    res2 = compute_ats_score(input_data)

    assert res1["total"] == res2["total"]
    assert res1["keywordScore"] == res2["keywordScore"]
    assert res1["titleScore"] == res2["titleScore"]
    assert res1["quantificationScore"] == res2["quantificationScore"]
    assert res1["completenessScore"] == res2["completenessScore"]

    assert 75 <= res1["total"] <= 95
    assert len(res1["mustHavesFound"]) == 3
    assert len(res1["mustHavesMissing"]) == 0
