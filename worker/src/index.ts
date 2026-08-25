export interface Env {
  TELEGRAM_BOT_TOKEN: string;
  TELEGRAM_WEBHOOK_SECRET: string;
  TELEGRAM_AUTHORIZED_USER_ID: string;
  GH_PAT: string;
  GH_OWNER: string;
  GH_REPO: string;
  RESEND_API_KEY?: string;
  EMAIL_TO?: string;
  EMAIL_FROM?: string;
}

async function sendWorkerEmailNotification(
  env: Env,
  payload: {
    eventType: string;
    action?: string;
    fromId?: string;
    chatId?: any;
    messageId?: any;
    status: string;
  }
): Promise<void> {
  const apiKey = env.RESEND_API_KEY;
  const toEmail = env.EMAIL_TO;
  if (!apiKey || !toEmail) {
    return;
  }

  const fromEmail = env.EMAIL_FROM || "onboarding@resend.dev";
  const now = new Date().toISOString();
  const subject = `🔔 Cloudflare Worker Triggered: ${payload.action || payload.eventType}`;

  const html = `
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 560px; margin: 0 auto; padding: 20px; background: #0f172a; color: #f8fafc; border-radius: 10px; border: 1px solid #334155;">
      <h2 style="margin: 0 0 12px 0; color: #38bdf8;">🔔 Cloudflare Worker Execution Alert</h2>
      <p style="color: #94a3b8; font-size: 14px; margin-bottom: 20px;">A webhook request was received and processed by your Cloudflare Worker relay.</p>
      <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
        <tr style="border-bottom: 1px solid #334155;"><td style="padding: 8px 0; color: #94a3b8;">Event Type</td><td style="padding: 8px 0; color: #f1f5f9; font-weight: bold;">${payload.eventType}</td></tr>
        <tr style="border-bottom: 1px solid #334155;"><td style="padding: 8px 0; color: #94a3b8;">Action</td><td style="padding: 8px 0; color: #38bdf8; font-weight: bold;">${payload.action || "N/A"}</td></tr>
        <tr style="border-bottom: 1px solid #334155;"><td style="padding: 8px 0; color: #94a3b8;">User ID</td><td style="padding: 8px 0; color: #f1f5f9;">${payload.fromId || "Unknown"}</td></tr>
        <tr style="border-bottom: 1px solid #334155;"><td style="padding: 8px 0; color: #94a3b8;">Chat ID</td><td style="padding: 8px 0; color: #f1f5f9;">${payload.chatId || "N/A"}</td></tr>
        <tr style="border-bottom: 1px solid #334155;"><td style="padding: 8px 0; color: #94a3b8;">Message ID</td><td style="padding: 8px 0; color: #f1f5f9;">${payload.messageId || "N/A"}</td></tr>
        <tr style="border-bottom: 1px solid #334155;"><td style="padding: 8px 0; color: #94a3b8;">Status</td><td style="padding: 8px 0; color: #4ade80; font-weight: bold;">${payload.status}</td></tr>
        <tr style="border-bottom: 1px solid #334155;"><td style="padding: 8px 0; color: #94a3b8;">Timestamp</td><td style="padding: 8px 0; color: #f1f5f9;">${now}</td></tr>
      </table>
    </div>
  `;

  try {
    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: fromEmail,
        to: [toEmail],
        subject: subject,
        html: html,
      }),
    });
    if (!res.ok) {
      const errText = await res.text();
      console.warn(`Resend email alert failed (${res.status}): ${errText}`);
    }
  } catch (err) {
    console.error("Error sending Resend email alert from Cloudflare worker:", err);
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    // 1. Verify Telegram Webhook Secret Token
    const secretHeader = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
    if (env.TELEGRAM_WEBHOOK_SECRET && secretHeader !== env.TELEGRAM_WEBHOOK_SECRET) {
      console.warn("Unauthorized webhook request: secret token mismatch.");
      return new Response("Unauthorized", { status: 401 });
    }

    let update: any;
    try {
      update = await request.json();
    } catch (e) {
      return new Response("Invalid JSON", { status: 400 });
    }

    // 2. Ignore updates that aren't callback_query
    const callbackQuery = update.callback_query;
    if (!callbackQuery) {
      return new Response("Ignored non-callback update", { status: 200 });
    }

    // 3. Verify callback_query.from.id
    const fromId = String(callbackQuery.from?.id || "");
    if (env.TELEGRAM_AUTHORIZED_USER_ID && fromId !== String(env.TELEGRAM_AUTHORIZED_USER_ID)) {
      console.warn(`Ignored callback from unauthorized user_id: ${fromId}`);
      return new Response("Ignored unauthorized user", { status: 200 });
    }

    const callbackId = callbackQuery.id;
    const action = callbackQuery.data;
    const message = callbackQuery.message || {};
    const chatId = message.chat ? message.chat.id : null;
    const messageId = message.message_id;

    // 4. Asynchronously process Telegram answer & GitHub repository_dispatch
    ctx.waitUntil(
      (async () => {
        // Fast answerCallbackQuery feedback
        if (callbackId && env.TELEGRAM_BOT_TOKEN) {
          try {
            await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/answerCallbackQuery`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                callback_query_id: callbackId,
                text: "Processing approval request..."
              })
            });
          } catch (err) {
            console.error("Error calling answerCallbackQuery:", err);
          }
        }

        let dispatchSuccess = false;
        // Call GitHub repository_dispatch
        if (env.GH_PAT && env.GH_OWNER && env.GH_REPO) {
          const dispatchUrl = `https://api.github.com/repos/${env.GH_OWNER}/${env.GH_REPO}/dispatches`;
          try {
            const ghRes = await fetch(dispatchUrl, {
              method: "POST",
              headers: {
                "Authorization": `Bearer ${env.GH_PAT}`,
                "Accept": "application/vnd.github+json",
                "User-Agent": "Cloudflare-Worker-Telegram-Relay",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json"
              },
              body: JSON.stringify({
                event_type: "telegram_approval",
                client_payload: {
                  action: action,
                  chat_id: chatId,
                  message_id: messageId,
                  user_id: Number(fromId)
                }
              })
            });
            console.log(`GitHub repository_dispatch status: ${ghRes.status}`);
            dispatchSuccess = ghRes.ok;
          } catch (err) {
            console.error("Error triggering GitHub repository_dispatch:", err);
          }
        } else {
          console.error("Missing GitHub config (GH_PAT, GH_OWNER, GH_REPO).");
        }

        // Send email alert to the user on worker run
        await sendWorkerEmailNotification(env, {
          eventType: "telegram_callback",
          action: action,
          fromId: fromId,
          chatId: chatId,
          messageId: messageId,
          status: dispatchSuccess ? "Dispatched" : "Completed",
        });
      })()
    );

    // Return 200 OK to Telegram immediately
    return new Response("OK", { status: 200 });
  }
};

