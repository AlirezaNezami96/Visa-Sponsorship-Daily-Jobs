export interface Env {
  TELEGRAM_BOT_TOKEN: string;
  TELEGRAM_WEBHOOK_SECRET: string;
  TELEGRAM_AUTHORIZED_USER_ID: string;
  GH_PAT: string;
  GH_OWNER: string;
  GH_REPO: string;
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
          } catch (err) {
            console.error("Error triggering GitHub repository_dispatch:", err);
          }
        } else {
          console.error("Missing GitHub config (GH_PAT, GH_OWNER, GH_REPO).");
        }
      })()
    );

    // Return 200 OK to Telegram immediately
    return new Response("OK", { status: 200 });
  }
};
