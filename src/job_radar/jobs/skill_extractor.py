"""Job skill extractor.

Extracts a normalized list of required skills from a job description using
a two-layer approach:

  1. Rule-based extraction: regex patterns for known tech stacks, frameworks,
     and job-domain keywords. Fast, zero API cost, no latency.
  2. AI augmentation (optional): the LLM fills in soft skills and ambiguous
     domain terms that the regex misses. Falls back gracefully if AI is down.

Normalization rules (spec §3.2):
  - Synonyms collapse: "JS" -> JavaScript, "NodeJS"/"Node.js"/"Node" -> Node.js
  - Acronyms expand to canonical display names: ML -> Machine Learning,
    AI -> Artificial Intelligence, NLP -> Natural Language Processing
  - Version-specific mentions normalize to the base skill:
    "Python 3.9"/"Python3" -> Python
  - Compound skills stay compound: "React Native", "Ruby on Rails"

The outputs are stored in jobs.skills (TEXT[]) and indexed with GIN.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── Rule-based skill patterns ──────────────────────────────────────────────────
# Organized by category for maintainability. Each entry is matched
# case-insensitively against the full job description.

_SKILL_PATTERNS: dict[str, list[str]] = {
    "languages": [
        r"\bPython\b", r"\bPython\s?3(?:\.\d+)?\b", r"\bJavaScript\b", r"\bTypeScript\b",
        r"\bJava\b(?! Script)", r"\bC\+\+\b", r"\bC#\b", r"\bGo\b(?!ogle)", r"\bRust\b",
        r"\bSwift\b", r"\bKotlin\b", r"\bPHP\b", r"\bRuby\b", r"\bScala\b",
        r"\bR\b(?= programming|\s+for|\s+package|\s+library)",
        r"\bMATLAB\b", r"\bDart\b", r"\bElixir\b", r"\bHaskell\b",
        r"\bSQL\b", r"\bPL/SQL\b", r"\bBash\b", r"\bShell\b",
        r"\bNode(?:\.js|JS)?\b", r"\bNodeJS\b",
    ],
    "frameworks": [
        r"\bReact(?:\.js)?\b", r"\bVue(?:\.js)?\b", r"\bAngular\b",
        r"\bNext\.js\b", r"\bNuxt(?:\.js)?\b", r"\bSvelte\b",
        r"\bDjango\b", r"\bFlask\b", r"\bFastAPI\b", r"\bSpring(?:\s+Boot)?\b",
        r"\bExpress(?:\.js)?\b", r"\bNest(?:\.js)?\b", r"\bLaravel\b",
        r"\bRails\b", r"\bRuby on Rails\b", r"\b\.NET(?:\s+Core)?\b",
        r"\bFlutter\b", r"\bReact Native\b",
        r"\bPyTorch\b", r"\bTensorFlow\b", r"\bKeras\b", r"\bscikit-learn\b",
        r"\bXGBoost\b", r"\bLangChain\b",
    ],
    "cloud": [
        r"\bAWS\b", r"\bAmazon Web Services\b", r"\bGCP\b", r"\bGoogle Cloud\b",
        r"\bAzure\b", r"\bDigitalOcean\b", r"\bHeroku\b",
        r"\bS3\b", r"\bEC2\b", r"\bLambda\b", r"\bEKS\b", r"\bGKE\b",
        r"\bCloudFormation\b", r"\bTerraform\b", r"\bPulumi\b",
    ],
    "databases": [
        r"\bPostgreSQL\b", r"\bMySQL\b", r"\bSQLite\b", r"\bMariaDB\b",
        r"\bMongoDB\b", r"\bRedis\b", r"\bElasticsearch\b", r"\bCassandra\b",
        r"\bDynamoDB\b", r"\bFirestore\b", r"\bSupabase\b",
        r"\bBigQuery\b", r"\bSnowflake\b", r"\bRedshift\b", r"\bClickHouse\b",
    ],
    "devops": [
        r"\bDocker\b", r"\bKubernetes\b", r"\bHelm\b", r"\bGitHub Actions\b",
        r"\bGitLab CI\b", r"\bJenkins\b", r"\bCircleCI\b", r"\bArgoCD\b",
        r"\bAnsible\b", r"\bChef\b", r"\bPuppet\b",
        r"\bDatadog\b", r"\bPrometheus\b", r"\bGrafana\b",
    ],
    "ai_ml": [
        r"\bLLM\b", r"\bRAG\b", r"\bOpenAI\b", r"\bGemini\b", r"\bClaude\b",
        r"\bHugging Face\b", r"\bTransformers\b", r"\bFine-tuning\b",
        r"\bVector\s+(?:search|database|store|embedding)\b",
        r"\bEmbedding\b", r"\bSemantic\s+search\b",
        r"\bMLflow\b", r"\bWandb\b", r"\bDVC\b",
        r"\bML\b", r"\bAI\b", r"\bNLP\b", r"\bMachine Learning\b",
        r"\bArtificial Intelligence\b", r"\bNatural Language Processing\b",
        r"\bComputer Vision\b", r"\bDeep Learning\b",
    ],
    "soft_skills": [
        r"\bLeadership\b", r"\bMentoring\b", r"\bCommunication\b",
        r"\bTeam\s+player\b", r"\bCollaboration\b", r"\bAgile\b", r"\bScrum\b",
        r"\bProject\s+management\b", r"\bStakeholder\s+management\b",
        r"\bProblem\s+solving\b", r"\bTime\s+management\b", r"\bAdaptability\b",
        r"\bAttention\s+to\s+detail\b", r"\bCritical\s+thinking\b",
    ],
    "domain": [
        r"\bFinance\b", r"\bFintech\b", r"\bHealthcare\b", r"\bE-?commerce\b",
        r"\bSaaS\b", r"\bLogistics\b", r"\bInsurance\b", r"\bCybersecurity\b",
        r"\bData\s+Engineering\b", r"\bRobotics\b", r"\bAutomotive\b",
    ],
    "tools": [
        r"\bGit\b", r"\bJira\b", r"\bConfluence\b", r"\bNotion\b",
        r"\bFigma\b", r"\bSketch\b", r"\bLinear\b",
        r"\bGraphQL\b", r"\bREST\s+API\b", r"\bgRPC\b",
        r"\bApache\s+Kafka\b", r"\bRabbitMQ\b", r"\bCelery\b",
        r"\bWebSocket\b", r"\bOpenAPI\b",
    ],
}

# Post-extraction normalization: canonical name overrides + synonym collapse.
# Keys are the raw derived (or overridden) name; values the final canonical.
_CANONICAL_NAMES: dict[str, str] = {
    r"\bReact(?:\.js)?\b": "React",
    r"\bVue(?:\.js)?\b": "Vue.js",
    r"\bNext\.js\b": "Next.js",
    r"\bPyTorch\b": "PyTorch",
    r"\bTensorFlow\b": "TensorFlow",
    r"\bgRPC\b": "gRPC",
    r"\bApache\s+Kafka\b": "Apache Kafka",
    r"\bRuby on Rails\b": "Ruby on Rails",
    r"\b\.NET(?:\s+Core)?\b": ".NET",
    r"\bReact Native\b": "React Native",
    r"\bGitHub Actions\b": "GitHub Actions",
    r"\bGitLab CI\b": "GitLab CI",
    r"\bPython\s?3(?:\.\d+)?\b": "Python",       # version-specific -> base
    r"\bNode(?:\.js|JS)?\b": "Node.js",          # NodeJS / Node / Node.js
    r"\bNodeJS\b": "Node.js",
    r"\bMachine Learning\b": "Machine Learning",
    r"\bArtificial Intelligence\b": "Artificial Intelligence",
    r"\bNatural Language Processing\b": "Natural Language Processing",
    r"\bDeep Learning\b": "Deep Learning",
    r"\bComputer Vision\b": "Computer Vision",
    r"\bE-?commerce\b": "E-commerce",
}

# Synonym / acronym expansion applied AFTER extraction (spec §3.2):
#   "js" -> JavaScript, "ml" -> Machine Learning, "ai" -> Artificial
#   Intelligence, "nlp" -> Natural Language Processing.
_SYNONYM_MAP: dict[str, str] = {
    "js": "JavaScript",
    "ml": "Machine Learning",
    "ai": "Artificial Intelligence",
    "nlp": "Natural Language Processing",
    "nodejs": "Node.js",
    "node": "Node.js",
    "node.js": "Node.js",
    "reactjs": "React",
    "react.js": "React",
    "vuejs": "Vue.js",
    "vue.js": "Vue.js",
    "k8s": "Kubernetes",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "tf": "TensorFlow",
    "pytorch": "PyTorch",
}


def _derive_canonical_from_pattern_raw(pattern_str: str) -> str:
    """Pre-build canonical names from patterns.
    Strips regex syntax to get the core display name.
    """
    clean = re.sub(r"\\b|\\s|\?P<\w+>|[+?*\[\]()|{}^$]|\\", " ", pattern_str)
    clean = " ".join(clean.split()).strip()
    return clean if clean else pattern_str


def _derive_canonical_from_pattern(pattern_str: str) -> str:
    """Derive a canonical display name from a regex pattern string.

    Strips regex metacharacters to get the human-readable skill name.
    E.g.: r'\\bDjango\\b' -> 'Django', r'\\bscikit-learn\\b' -> 'scikit-learn'
    """
    # Remove anchors and common regex syntax to get the core name
    clean = re.sub(r"\\b|\\s|[+?*\[\]()|{}]|\\", " ", pattern_str)
    # Collapse whitespace and strip
    clean = " ".join(clean.split()).strip()
    # Remove remaining regex quantifiers and groups
    clean = re.sub(r"\s*\.\s*\w+", lambda m: m.group(0).replace(" ", ""), clean)
    return clean if clean else pattern_str


def _build_compiled_patterns() -> list[tuple[re.Pattern, str]]:
    patterns = []
    for _category, entries in _SKILL_PATTERNS.items():
        for pattern_str in entries:
            # Use explicit canonical name if defined, otherwise derive from pattern string
            canonical = _CANONICAL_NAMES.get(pattern_str) or _derive_canonical_from_pattern_raw(pattern_str)
            compiled = re.compile(pattern_str, re.IGNORECASE)
            patterns.append((compiled, canonical))
    return patterns


_COMPILED_PATTERNS = _build_compiled_patterns()


def _canonicalize(skill: str) -> str:
    """Apply synonym/acronym normalization to a single extracted skill."""
    key = skill.lower().strip().rstrip(".")
    mapped = _SYNONYM_MAP.get(key)
    return mapped if mapped else skill


def extract_skills_rule_based(text: str) -> list[str]:
    """Extract skills from text using precompiled regex patterns.

    Returns deduplicated list preserving first-encountered form.
    """
    if not text:
        return []

    found: list[str] = []
    for pattern, canonical in _COMPILED_PATTERNS:
        if pattern.search(text):
            found.append(canonical)

    return _deduplicate(found)


def extraction_confidence(
    title: str,
    description: str,
    extracted_skills: list[str],
) -> float:
    """Confidence that the extraction captured the job's real requirements.

    Heuristic per spec §3.2 (confidence scoring for extracted skills):
      - Starts at 0.5 (rule-based only is decent but not exhaustive)
      - Short descriptions (< 200 chars) lower confidence
      - Longer, denser descriptions raise it
      - Finding at least one skill is a positive signal
    Returns a float 0.0–1.0.
    """
    text_len = len((description or "").strip())
    conf = 0.5
    if text_len == 0:
        # Title-only matching: lowest confidence band
        return 0.3 if extracted_skills else 0.2
    if text_len < 200:
        conf -= 0.15
    elif text_len >= 800:
        conf += 0.15
    elif text_len >= 400:
        conf += 0.1
    if extracted_skills:
        conf += 0.2
    else:
        conf -= 0.1
    return max(0.0, min(1.0, conf))


def extract_skills_from_job(
    title: str,
    description: str,
    requirements: list[str] | None = None,
    llm_router: Any = None,
    use_ai: bool = False,
) -> list[str]:
    """Extract required skills from a job posting.

    Strategy:
      1. Rule-based extraction (always runs, zero cost)
      2. AI augmentation if use_ai=True and llm_router is provided

    Args:
        title: Job title.
        description: Full job description.
        requirements: Optional pre-split requirements list.
        llm_router: LLM router instance for AI augmentation.
        use_ai: Whether to augment with AI (adds latency + cost).

    Returns:
        Deduplicated list of normalized skill strings.
    """
    combined_text = "\n".join(filter(None, [title, description, "\n".join(requirements or [])]))

    # Layer 1: rule-based
    rule_skills = extract_skills_rule_based(combined_text)

    if not use_ai or not llm_router:
        return _deduplicate(rule_skills)

    # Layer 2: AI augmentation
    try:
        ai_skills = _ai_extract_skills(combined_text, rule_skills, llm_router)
        return _deduplicate(rule_skills + ai_skills)
    except Exception as exc:
        logger.warning("AI skill extraction failed, using rule-based only: %s", exc)
        return _deduplicate(rule_skills)


def _ai_extract_skills(text: str, already_found: list[str], llm_router: Any) -> list[str]:
    """Use AI to extract additional skills not caught by rules."""
    prompt = f"""Extract required technical and soft skills from this job posting.
Return ONLY a JSON array of skill strings, no explanation.
DO NOT repeat these already-found skills: {already_found[:20]}

Job text: {text[:6000]}

Return format: ["skill1", "skill2", ...]"""

    result = llm_router.complete_json(prompt)
    if isinstance(result, list):
        return [str(s).strip() for s in result if s and isinstance(s, str)]
    # Handle {"skills": [...]} shape
    if isinstance(result, dict):
        skills = result.get("skills") or []
        return [str(s).strip() for s in skills if s]
    return []


def _deduplicate(skills: list[str]) -> list[str]:
    """Deduplicate skill list case-insensitively, preserving order.

    Synonyms (e.g. "JavaScript" and "JS") collapse to one entry, and
    the canonical form of the first occurrence wins. When a compound
    skill and its component both appear (e.g. "React Native" and
    "React"), the compound absorbs the component.
    """
    seen: dict[str, str] = {}  # lower key -> canonical display
    order: list[str] = []
    for s in skills:
        if not s:
            continue
        canonical = _canonicalize(s)
        key = canonical.lower().strip()
        if key and key not in seen:
            seen[key] = canonical
            order.append(key)

    # Compound absorption: when a compound skill is present, its components
    # ("react" under "react native", "ruby"/"rails" under "ruby on rails")
    # are absorbed into the compound.
    _COMPOUND_COMPONENTS: dict[str, tuple[str, ...]] = {
        "react native": ("react",),
        "ruby on rails": ("ruby", "rails"),
    }
    present = set(order)
    result_keys = []
    for key in order:
        if key in _COMPOUND_COMPONENTS:
            result_keys.append(key)
        elif not any(
            key in components and compound in present
            for compound, components in _COMPOUND_COMPONENTS.items()
        ):
            result_keys.append(key)
    return [seen[k] for k in result_keys]
