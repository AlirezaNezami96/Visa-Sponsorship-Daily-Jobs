"""Build ai_companies.json from curated lists of dedicated AI companies & AI job boards."""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, List

logger = logging.getLogger(__name__)

CURATED_AI = [
    # Verified Active AI Companies (Greenhouse API)
    ("Anthropic", "greenhouse", "anthropic"),
    ("Scale AI", "greenhouse", "scaleai"),
    ("Databricks", "greenhouse", "databricks"),
    ("Cresta", "greenhouse", "cresta"),
    ("Together AI", "greenhouse", "togetherai"),
    ("Snorkel AI", "greenhouse", "snorkelai"),
    ("Stability AI", "greenhouse", "stabilityai"),
    ("Labelbox", "greenhouse", "labelbox"),
    ("DeepMind", "greenhouse", "deepmind"),
    ("Abacus AI", "greenhouse", "abacus"),
    ("Otter.ai", "greenhouse", "otterai"),
    ("Descript", "greenhouse", "descript"),
    ("AssemblyAI", "greenhouse", "assemblyai"),
    ("Imbue", "greenhouse", "imbue"),
    ("Inflection AI", "greenhouse", "inflectionai"),
    ("Weights & Biases", "greenhouse", "wandb"),
    ("DataRobot", "greenhouse", "datarobot"),

    # Verified Active AI Companies (Lever API)
    ("Shield AI", "lever", "shieldai"),
    ("Anyscale", "lever", "anyscale"),
    ("Runway", "lever", "runwayml"),
    ("Cohere", "lever", "cohere"),

    # Verified Active AI Companies (Workable API)
    ("Hugging Face", "workable", "huggingface"),

    # AI Labs (Custom / Direct careers URLs)
    ("OpenAI", "custom", "https://openai.com/careers/search/"),
    ("Mistral AI", "custom", "https://mistral.ai/jobs/"),
    ("Perplexity", "custom", "https://www.perplexity.ai/careers"),
    ("xAI", "custom", "https://x.ai/careers"),
    ("ElevenLabs", "custom", "https://elevenlabs.io/careers"),
    ("Character.AI", "custom", "https://character.ai/careers"),
    ("Pinecone", "custom", "https://www.pinecone.io/careers/"),
    ("Weaviate", "custom", "https://weaviate.io/company/careers"),
    ("LangChain", "custom", "https://www.langchain.com/careers"),
    ("Modal", "custom", "https://modal.com/careers"),
    ("Replicate", "custom", "https://replicate.com/careers"),
    ("Baseten", "custom", "https://www.baseten.co/careers/"),
    ("Groq", "custom", "https://groq.com/careers/"),
    ("Cerebras", "custom", "https://cerebras.ai/careers/"),

    # Dedicated AI Job Portals & Niche Aggregators
    ("AI-Jobs.net", "custom", "https://ai-jobs.net"),
    ("DataScienceJobs", "custom", "https://datasciencejobs.com"),
    ("RemoteAI.io", "custom", "https://remoteai.io"),
    ("CryptoJobs AI", "custom", "https://crypto.jobs"),
    ("Web3 Career AI", "custom", "https://web3.career"),
    ("HackerNews AI Jobs", "custom", "https://news.ycombinator.com/jobs"),
]


def build_ai_companies(output_file: str = "ai_companies.json") -> dict:
    scrapable = []
    custom_ats = []

    for name, ats, slug_or_url in CURATED_AI:
        if ats == "greenhouse":
            url = f"https://boards.greenhouse.io/{slug_or_url}"
            slug = slug_or_url
        elif ats == "lever":
            url = f"https://jobs.lever.co/{slug_or_url}"
            slug = slug_or_url
        elif ats == "ashby":
            url = f"https://{slug_or_url}.ashbyhq.com"
            slug = slug_or_url
        elif ats == "workable":
            url = f"https://apply.workable.com/{slug_or_url}"
            slug = slug_or_url
        elif ats == "smartrecruiters":
            url = f"https://careers.smartrecruiters.com/{slug_or_url}"
            slug = slug_or_url
        else:
            url = slug_or_url
            slug = None

        item = {
            "name": name,
            "careers_url": url,
            "ats": ats,
            "slug": slug,
            "source": "curated_ai",
        }

        if ats in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "personio"):
            scrapable.append(item)
        else:
            custom_ats.append(item)

    out = {
        "scrapable": scrapable,
        "custom_ats": custom_ats,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    return out
