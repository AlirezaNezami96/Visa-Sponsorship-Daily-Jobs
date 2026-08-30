/**
 * POST /functions/v1/extract-job-skills
 * Internal / cron-triggered. Processes a batch of jobs that have no
 * skills extracted yet and writes the skills array back.
 *
 * Protected by the INTERNAL_API_KEY header — not callable by frontend users.
 *
 * Body: { batch_size?: number }  (default 50, max 200)
 *
 * Response:
 * { processed: number, failed: number, errors: string[] }
 */
import { createAdminClient } from "../_shared/supabase-clients.ts";
import { handleOptions, json, serverError } from "../_shared/http.ts";
import { getEnv } from "../_shared/env.ts";

const DEFAULT_BATCH = 50;
const MAX_BATCH = 200;

// Inline rule-based skill extraction (mirrors Python skill_extractor.py).
// Used here so the function can operate without the Python engine.
// Normalization parity (spec §3.2): NodeJS/Node/Node.js -> Node.js,
// ML -> Machine Learning, AI -> Artificial Intelligence, NLP -> Natural
// Language Processing, Python 3.9 -> Python, compounds kept compound.
const SKILL_PATTERNS: [RegExp, string][] = [
  // Languages
  [/\bPython\s?3(?:\.\d+)?\b|\bPython\b/i, "Python"],
  [/\bPython3?\b/i, "Python"],
  [/\bJavaScript\b/i, "JavaScript"],
  [/\bTypeScript\b/i, "TypeScript"],
  [/\bJava\b(?! ?Script)/i, "Java"],
  [/\bC\+\+\b/i, "C++"],
  [/\bC#\b/i, "C#"],
  [/\bGo\b(?!ogle)/i, "Go"],
  [/\bRust\b/i, "Rust"],
  [/\bKotlin\b/i, "Kotlin"],
  [/\bSwift\b/i, "Swift"],
  [/\bPHP\b/i, "PHP"],
  [/\bRuby\b/i, "Ruby"],
  [/\bScala\b/i, "Scala"],
  [/\bSQL\b/i, "SQL"],
  [/\bBash\b/i, "Bash"],
  [/\bNode(?:\.js|JS)?\b/i, "Node.js"],
  // Frameworks / Libraries
  [/\bReact(?:\.js)?\b/i, "React"],
  [/\bVue(?:\.js)?\b/i, "Vue.js"],
  [/\bAngular\b/i, "Angular"],
  [/\bNext\.js\b/i, "Next.js"],
  [/\bSvelte\b/i, "Svelte"],
  [/\bDjango\b/i, "Django"],
  [/\bFlask\b/i, "Flask"],
  [/\bFastAPI\b/i, "FastAPI"],
  [/\bSpring(?:\s+Boot)?\b/i, "Spring Boot"],
  [/\bExpress(?:\.js)?\b/i, "Express"],
  [/\bNest(?:\.js)?\b/i, "NestJS"],
  [/\bFlutter\b/i, "Flutter"],
  [/\bReact Native\b/i, "React Native"],
  [/\bPyTorch\b/i, "PyTorch"],
  [/\bTensorFlow\b/i, "TensorFlow"],
  [/\bscikit-learn\b/i, "scikit-learn"],
  [/\bLangChain\b/i, "LangChain"],
  // Cloud
  [/\bAWS\b/i, "AWS"],
  [/\bGoogle Cloud\b|\bGCP\b/i, "Google Cloud"],
  [/\bAzure\b/i, "Azure"],
  [/\bTerraform\b/i, "Terraform"],
  // Databases
  [/\bPostgreSQL\b/i, "PostgreSQL"],
  [/\bMySQL\b/i, "MySQL"],
  [/\bMongoDB\b/i, "MongoDB"],
  [/\bRedis\b/i, "Redis"],
  [/\bElasticsearch\b/i, "Elasticsearch"],
  [/\bSupabase\b/i, "Supabase"],
  [/\bBigQuery\b/i, "BigQuery"],
  // DevOps
  [/\bDocker\b/i, "Docker"],
  [/\bKubernetes\b|\bK8s\b/i, "Kubernetes"],
  [/\bGitHub Actions\b/i, "GitHub Actions"],
  [/\bCI\/CD\b/i, "CI/CD"],
  // AI/ML (acronyms expand to full names)
  [/\bLLM\b/i, "LLM"],
  [/\bRAG\b/i, "RAG"],
  [/\bOpenAI\b/i, "OpenAI"],
  [/\bGemini\b/i, "Gemini"],
  [/\bML\b|\bMachine Learning\b/i, "Machine Learning"],
  [/\bAI\b|\bArtificial Intelligence\b/i, "Artificial Intelligence"],
  [/\bNLP\b|\bNatural Language Processing\b/i, "Natural Language Processing"],
  [/\bDeep Learning\b/i, "Deep Learning"],
  [/\bComputer Vision\b/i, "Computer Vision"],
  // Tools
  [/\bGraphQL\b/i, "GraphQL"],
  [/\bREST(?:\s+API)?\b/i, "REST API"],
  [/\bgRPC\b/i, "gRPC"],
  [/\bApache\s+Kafka\b/i, "Apache Kafka"],
  // Soft skills
  [/\bAgile\b/i, "Agile"],
  [/\bScrum\b/i, "Scrum"],
  [/\bLeadership\b/i, "Leadership"],
  [/\bMentoring\b/i, "Mentoring"],
  [/\bCommunication\b/i, "Communication"],
  [/\bCollaboration\b/i, "Collaboration"],
  [/\bProblem\s+solving\b/i, "Problem solving"],
];

// Compound absorption (mirrors Python): when "react native" is found,
// "react" is absorbed; "ruby on rails" absorbs "ruby".
const COMPOUND_COMPONENTS: Record<string, string[]> = {
  "react native": ["react"],
  "ruby on rails": ["ruby", "rails"],
};

function extractSkillsInline(title: string, description: string): string[] {
  const text = [title, description].join(" ");
  const found = new Map<string, string>();
  for (const [pattern, canonical] of SKILL_PATTERNS) {
    if (pattern.test(text)) {
      found.set(canonical.toLowerCase(), canonical);
    }
  }
  // Compound absorption: remove components whose compound is present
  const present = new Set(found.keys());
  for (const [compound, components] of Object.entries(COMPOUND_COMPONENTS)) {
    if (present.has(compound)) {
      for (const c of components) found.delete(c);
    }
  }
  return [...found.values()];
}

function verifyInternalKey(req: Request): boolean {
  const key = req.headers.get("x-internal-key") ?? "";
  const expected = getEnv("INTERNAL_API_KEY") ?? "";
  return key.length > 8 && key === expected;
}

Deno.serve(async (req) => {
  const preflight = handleOptions(req);
  if (preflight) return preflight;

  if (req.method !== "POST") {
    return json({ error: { code: "method_not_allowed", message: "POST only" } }, { status: 405 });
  }
  if (!verifyInternalKey(req)) {
    return json({ error: { code: "forbidden", message: "Invalid internal key" } }, { status: 403 });
  }

  let batchSize = DEFAULT_BATCH;
  try {
    const body = await req.json().catch(() => ({}));
    const parsed = parseInt(body?.batch_size ?? "", 10);
    if (!Number.isNaN(parsed)) batchSize = Math.min(parsed, MAX_BATCH);
  } catch {
    // use default
  }

  try {
    const admin = createAdminClient();

    // Fetch jobs pending skill extraction
    const { data: jobs, error: fetchErr } = await admin
      .from("jobs")
      .select("id, title, description")
      .is("skills_extracted_at", null)
      .eq("status", "active")
      .order("created_at", { ascending: true })
      .limit(batchSize);

    if (fetchErr) {
      console.error("extract-job-skills fetch error:", fetchErr.message);
      return serverError("Failed to fetch pending jobs");
    }

    const rows = (jobs ?? []) as Array<{ id: string; title: string; description: string }>;
    let processed = 0;
    let failed = 0;
    const errors: string[] = [];

    for (const job of rows) {
      try {
        const skills = extractSkillsInline(job.title ?? "", job.description ?? "");
        const { error: updateErr } = await admin
          .from("jobs")
          .update({
            skills,
            skills_extracted_at: new Date().toISOString(),
            skill_extraction_error: null,
          })
          .eq("id", job.id);

        if (updateErr) {
          failed++;
          errors.push(`job ${job.id}: ${updateErr.message}`);
        } else {
          processed++;
        }
      } catch (exc) {
        failed++;
        const msg = exc instanceof Error ? exc.message : String(exc);
        errors.push(`job ${job.id}: ${msg}`);
        // Mark the error so we don't retry immediately
        await admin
          .from("jobs")
          .update({ skill_extraction_error: msg.slice(0, 500) })
          .eq("id", job.id)
          .then(() => undefined, () => undefined);
      }
    }

    return json({ processed, failed, errors: errors.slice(0, 20) });
  } catch (err) {
    console.error("extract-job-skills error:", err);
    return serverError();
  }
});
