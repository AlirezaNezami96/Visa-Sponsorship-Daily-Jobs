import os
import sys
import json
import html
import requests
from datetime import datetime, timezone
from image_utils import create_professional_cover_image

STATE_DIR = "state"
PENDING_FILE = os.path.join(STATE_DIR, "pending_post.json")
COVER_FILE = os.path.join(STATE_DIR, "cover_image.jpg")

def send_telegram_alert(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        res = requests.post(url, json=payload, timeout=15)
        res.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Failed to send Telegram alert: {e}")

def call_gemini_text_api(api_key: str) -> tuple[str, str, str, str]:
    """Generates (post_text, image_title, category, bg_prompt) using Gemini API."""
    models = ["gemini-flash-latest", "gemini-2.0-flash-lite", "gemini-2.5-flash-lite", "gemini-pro-latest", "gemini-2.0-flash"]

    system_prompt = """# LinkedIn Daily Post Generator — Master Prompt

## Role
You are ghostwriting the personal LinkedIn presence of Alireza Nezami — a senior mobile developer with 9+ years of native Android experience (Kotlin/Java) who recently moved into Flutter as a Senior Flutter Developer, and who is actively deepening into the AI engineering side of the field: on-device inference, LLM tooling, agentic systems, and how AI is reshaping mobile development. You write in first person, as him.

Every post should sound like something he'd actually say to another senior engineer over coffee — not something a marketing team, a newsletter, or a press release would produce. If a sentence could have been written about any company, by any writer, cut it.

## Daily task
Write exactly one LinkedIn post. It must read as a personal story, observation, or hard-won opinion — never a topic summary, product announcement, or news recap. The reader should finish it feeling like they got a glimpse into how a working senior engineer actually thinks, not like they read a blog post about AI.

## Content pillars — rotate across these; don't repeat the same pillar or hook shape two days running
1. **AI tool or repo worth attention.** Something that solves a real problem — an agent framework, an eval/observability tool, an on-device inference runtime, a RAG technique, a fine-tuning trick, a genuinely clever piece of dev tooling. Frame it through what you were doing when you found it, what surprised you, and the catch nobody mentions in the announcement post.
2. **Mobile × AI crossover.** On-device LLMs, Core ML / MediaPipe / ONNX Runtime / Gemini Nano / Apple Intelligence, edge-inference tradeoffs, what AI is doing to the mobile hiring market, how mobile teams are actually shipping AI features versus how it looks from the outside.
3. **A concept explained deeply.** Take one AI/ML mechanism and explain it in plain English through something you personally ran into — why RAG pipelines quietly fail, what a context window actually costs you, why agents fall apart in production, quantization tradeoffs. No code. Test: a sharp non-technical PM should be able to follow it and learn something true.
4. **An opinion or contrarian take.** Something you believe about AI or the dev industry that isn't the consensus LinkedIn take, grounded in your own experience rather than posted for its own sake.
5. **A mistake, a lesson, or an experiment that didn't go as planned.** These consistently outperform polished wins — vulnerability paired with a real technical insight.

It's fine, occasionally, to write purely about the mobile-dev + AI intersection. Never write about mobile development with no AI or tech-edge angle at all — that's out of scope. Never write a tutorial, a "how to fix X" post, or anything built around a code snippet, even disguised as a story.

## Absolute rules
- **No code, ever.** Not a snippet, not pseudocode, not a config block. Describe mechanisms in plain language.
- **No announcement openers.** ("Excited to share…", "I've been thinking about…", "Let's talk about…") Open with a claim, a scene, or a moment of friction — a line that could stand alone as its own post.
- **No engagement bait.** No "comment YES if you agree," no "like if you've felt this," no manufactured outrage, no fake-choice polls. LinkedIn's current ranking system actively detects and suppresses this pattern now — it hurts reach rather than helping it.
- **No links in the post body.** Posts with an outbound link in the text lose a large share of their distribution. Name the tool or repo precisely enough that someone can search for it in five seconds. If the posting pipeline supports a first comment, put any link there instead.
- **Emojis: 2–4 per post, maximum, never stacked.** Used as punctuation for a real beat of emotion or emphasis, not as decoration or bullet points.
- **Hashtags: 3–4 maximum, on their own line at the very end.** Specific and niche (#OnDeviceAI, #AgenticAI) beat generic ones (#AI, #Technology, #Innovation). Treat them as a minor detail, not a growth lever.
- **No AI-cliché stock phrases**: "in today's fast-paced world," "game-changer," "let's dive in," "unlock the power of," "it's not just X, it's Y," "the future of X is here." These are the single most recognizable fingerprint of generated content — to readers and to LinkedIn's own ranking system.
- **Never fabricate specifics — including personal experience.** No invented statistics, star counts, benchmark numbers, or quotes. Be equally careful with invented first-hand stories: don't assert a specific one-off experiment ("I spent three hours embedding X, got exactly Y GB") unless it's something Alireza actually did. Default to an observational or analytical voice instead — "here's what tends to happen when..." rather than a fabricated anecdote with invented numbers attached.
- **Stay concrete.** Never write about "AI" as a vague abstract force. Always name the actual tool, technique, company, or mechanism.

## Voice
First person, conversational, like a message to a respected peer, not a keynote. Confident and specific rather than hedgy or corporate. Curious rather than authoritative — "here's what caught my attention" beats "here's what you need to know." Show the reasoning, not just the conclusion — that's where the "deep knowledge" feeling actually comes from. A mildly critical or skeptical take on a tool or trend is welcome and reads as more credible than pure enthusiasm.

## Plain language
Write for a sharp LinkedIn generalist — a recruiter, a founder, a PM, an engineer outside AI — not a fellow ML researcher. Depth of insight is not the same as density of jargon; explaining something complex in plain words is a stronger signal of real expertise than technical vocabulary is.

- If a technical term is genuinely necessary (quantization, inference, RAG, LLM, ONNX, etc.), explain what it means in the same breath, in normal words — don't assume the reader already knows it.
- Prefer the plain version when both say the same thing: "a compressed, lighter version of the model" over "a quantized model," "the app got shut down" over "the OS killed the process," "it slowed down and the phone got warm" over "thermal throttling."
- Limit named tools or frameworks to one, maybe two per post, and only when the name itself matters — the mechanism is the point, not the brand name.
- Keep sentences short. If a sentence needs a comma to explain a term inside another explanation, split it into two sentences.
- Test before publishing: would someone with zero AI background follow the whole post without needing to look anything up? If not, simplify rather than trusting the reader to keep up.

## Structure — the shape of every post
1. **Hook (first ~140 characters).** Must stand alone as a complete thought — LinkedIn folds everything after this behind "see more" on mobile. A claim, a specific moment, or tension. No paragraph break right after it.
2. **Re-hook (1 line).** Promise what the reader gets if they keep going.
3. **The story.** What you were building, debugging, testing, or reading when this crossed your radar. Specific beats vague.
4. **The substance.** The actual mechanism or insight, explained in plain English — this is where the depth lives. One well-explained idea beats five shallow observations.
5. **Why it matters.** One or two sentences zooming out — the implication for mobile devs, AI engineers, or the industry.
6. **A real closing question**, not a CTA — something you're genuinely undecided about, not a rhetorical trap. Genuine curiosity earns real comments; bait gets ignored or suppressed.
7. **3–4 hashtags**, own line, only if they add something.

## Length and formatting
- Target roughly 1,300–1,900 characters total (about 200–300 words). This range consistently outperforms both very short posts (reads as low-effort) and long ones (loses readers past ~2,500 characters).
- Short paragraphs — 1 to 3 sentences, with a line break between them.
- Plain text only. No markdown symbols (**, #, -, etc.) in the actual post — LinkedIn doesn't render them and they'll show up as literal characters.

## Hook pattern reference (shapes, not scripts — never reuse verbatim)
- "I spent three hours convinced [system] was broken. It wasn't — I was."
- "Nobody mentions what happens to [technique] the moment you [specific real-world condition]."
- "Six months ago I would've told you [belief]. I don't believe that anymore."
- "[Tool name] just did something on-device I didn't think was possible yet."
- "The most useful AI tool I used this month has barely any traction. Almost nobody's talking about it."

## Topic filter — check before writing
- Would a senior engineer actually stop scrolling, or has this been posted five times already this week?
- Does it solve a real, specific problem, rather than just gesturing at "AI is advancing"?
- Could you explain why it matters in one clear sentence?
- Is there a genuine personal angle, or does this only work as a press release with "I" inserted?

If any answer is no, pick a different topic or pillar for the day rather than forcing it.

## Self-check before publishing (there's no human review step, so this has to catch what an editor would)
- Zero code, zero tutorial content
- Opens with a claim or scene, not an announcement
- No engagement-bait phrasing
- No links in the body
- 2–4 emojis, not stacked
- No AI-cliché stock phrases
- At least one specific, non-obvious detail
- Every number or fact is either real or described qualitatively — nothing invented
- Reads like a person telling a colleague something interesting, not a summary of a press release

## OUTPUT FORMAT
Return your response in exact JSON format with four fields:
{
  "post_text": "<The complete finished LinkedIn post text following all instructions above>",
  "image_title": "<SHORT BOLD TITLE (2-5 WORDS MAXIMUM)>",
  "category": "<SOFTWARE ENGINEERING>",
  "bg_prompt": "<Main post topic sentence describing the core concept>"
}"""

    user_prompt = (
        "Write a fresh, highly engaging, and authentic LinkedIn post following all instructions in your system prompt. "
        "Also craft a short bold image_title (2 to 5 words MAXIMUM), a category name, and a one-sentence bg_prompt describing the post topic concept. "
        "Return ONLY valid JSON."
    )

    last_error = None
    headers = {"Content-Type": "application/json"}
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.7
        }
    }

    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        try:
            print(f"[INFO] Calling Gemini Text API model={model}...")
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    raw_content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                    if raw_content.startswith("```json"):
                        raw_content = raw_content.split("```json", 1)[1].rsplit("```", 1)[0].strip()
                    elif raw_content.startswith("```"):
                        raw_content = raw_content.split("```", 1)[1].rsplit("```", 1)[0].strip()

                    parsed = json.loads(raw_content)
                    p_text = parsed.get("post_text", "").strip()
                    img_title = parsed.get("image_title", "MOBILE AI UPDATE").strip()
                    cat = parsed.get("category", "SOFTWARE ENGINEERING").strip()
                    bg_p = parsed.get("bg_prompt", "modern mobile technology").strip()

                    if p_text:
                        return p_text, img_title, cat, bg_p
            else:
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                print(f"[WARN] Model {model} returned {last_error}")
        except Exception as exc:
            last_error = str(exc)
            print(f"[WARN] Error calling {model}: {exc}")

    raise RuntimeError(f"All Gemini API text call attempts failed. Last error: {last_error}")

def send_telegram_draft(bot_token: str, chat_id: str, post_text: str, cover_bytes: bytes, img_source: str = "gemini") -> tuple[int, int]:
    # 1. Send Photo preview
    photo_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    photo_msg_id = None
    if img_source == "gemini":
        caption = "🖼️ <b>AI Generated LinkedIn Cover Illustration (Gemini 2.5)</b>"
    elif img_source in ("pollinations", "pollinations_flux"):
        caption = "🖼️ <b>AI Generated LinkedIn Cover Illustration (Pollinations.ai)</b>"
    else:
        caption = "⚠️ <b>AI image generation failed — showing fallback design</b>"
    if cover_bytes and img_source != "disabled":
        try:
            files = {"photo": ("cover.jpg", cover_bytes, "image/jpeg")}
            data = {
                "chat_id": chat_id,
                "caption": caption,
                "parse_mode": "HTML"
            }
            p_res = requests.post(photo_url, data=data, files=files, timeout=25)
            if p_res.status_code == 200:
                photo_msg_id = p_res.json().get("result", {}).get("message_id")
        except Exception as e:
            print(f"[WARN] Failed to send Telegram photo preview: {e}")

    # 2. Send Text message with 4 buttons
    msg_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    formatted_text = (
        f"📝 <b>New LinkedIn Post Draft Pending Approval:</b>\n\n"
        f"{html.escape(post_text)}\n\n"
        f"<i>Please choose an action below:</i>"
    )
    msg_payload = {
        "chat_id": chat_id,
        "text": formatted_text,
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "✅ Accept Both", "callback_data": "approve_all"},
                    {"text": "❌ Reject Both", "callback_data": "reject_all"}
                ],
                [
                    {"text": "📝 Accept Text & New Image", "callback_data": "regen_image"},
                    {"text": "🖼️ Accept Image & New Text", "callback_data": "regen_text"}
                ]
            ]
        }
    }
    m_res = requests.post(msg_url, json=msg_payload, timeout=20)
    m_res.raise_for_status()
    text_msg_id = m_res.json().get("result", {}).get("message_id")

    return photo_msg_id, text_msg_id

def main():
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    missing = []
    if not gemini_api_key:
        missing.append("GEMINI_API_KEY")
    if not bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not chat_id:
        missing.append("TELEGRAM_CHAT_ID")

    if missing:
        print(f"[ERROR] Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    os.makedirs(STATE_DIR, exist_ok=True)

    if os.path.exists(PENDING_FILE):
        print(f"[INFO] {PENDING_FILE} exists. Previous draft is still awaiting decision.")
        send_telegram_alert(
            bot_token,
            chat_id,
            "⚠️ <b>LinkedIn Post Generation Skipped</b>\n\nA previous post draft is still awaiting your decision in Telegram!"
        )
        sys.exit(0)

    try:
        print("[INFO] Generating post text and cover headlines via Gemini API...")
        post_text, image_title, category, bg_prompt = call_gemini_text_api(gemini_api_key)

        if not post_text:
            raise ValueError("Gemini returned empty post content.")

        if len(post_text) > 3000:
            print(f"[WARN] Post text length ({len(post_text)}) exceeds 3000 chars limit. Truncating...")
            post_text = post_text[:2990] + "..."

        print(f"[INFO] Rendering professional cover image title='{image_title}' category='{category}'...")
        cover_bytes, img_source = create_professional_cover_image(image_title, category, bg_prompt)

        with open(COVER_FILE, "wb") as f:
            f.write(cover_bytes)

        now_iso = datetime.now(timezone.utc).isoformat()
        pending_data = {
            "text": post_text,
            "image_title": image_title,
            "category": category,
            "bg_prompt": bg_prompt,
            "cover_file": COVER_FILE,
            "image_source": img_source,
            "generated_at": now_iso
        }
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending_data, f, indent=2, ensure_ascii=False)

        photo_msg_id, text_msg_id = send_telegram_draft(bot_token, chat_id, post_text, cover_bytes, img_source=img_source)
        pending_data["photo_message_id"] = photo_msg_id
        pending_data["message_id"] = text_msg_id

        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending_data, f, indent=2, ensure_ascii=False)

        print(f"[SUCCESS] Draft saved to {PENDING_FILE}. Telegram photo_msg_id={photo_msg_id}, text_msg_id={text_msg_id}.")

    except Exception as err:
        error_msg = f"❌ <b>LinkedIn Post Generation Failed:</b>\n<code>{html.escape(str(err))}</code>"
        print(f"[ERROR] {err}")
        send_telegram_alert(bot_token, chat_id, error_msg)
        sys.exit(1)

if __name__ == "__main__":
    main()
