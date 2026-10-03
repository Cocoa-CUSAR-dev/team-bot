/**
 * Discord relay.
 *
 * review-bot runs on Render's free tier, which NATs outbound traffic through
 * an IP shared with everyone else on it. On 2026-10-03 Discord's Cloudflare
 * edge started refusing that IP outright -- 429 with Retry-After 491, then
 * 3242 the same evening -- while the exact same webhook answered a laptop
 * instantly with 4 of 5 requests left in its bucket. Nothing the bot sent was
 * over any limit; the address it sent from was simply in the doghouse.
 *
 * So the message goes out from here instead. Discord is itself behind
 * Cloudflare, so a Worker's request barely leaves the network.
 *
 * The Discord webhook URL lives here as a Worker secret, not in the caller:
 * this relay can post to exactly one channel, so leaking the relay's own URL
 * and secret costs far less than leaking the webhook would.
 *
 * Deploy:
 *   npx wrangler deploy
 *   npx wrangler secret put DISCORD_WEBHOOK_URL
 *   npx wrangler secret put RELAY_SECRET
 */

function constantTimeEquals(a, b) {
  const encoder = new TextEncoder();
  const left = encoder.encode(a);
  const right = encoder.encode(b);
  // timingSafeEqual throws on a length mismatch, and length alone isn't the
  // secret, so compare it up front.
  if (left.byteLength !== right.byteLength) return false;
  return crypto.subtle.timingSafeEqual(left, right);
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("POST only", { status: 405 });
    }
    if (!env.RELAY_SECRET || !env.DISCORD_WEBHOOK_URL) {
      return new Response("relay is not configured", { status: 503 });
    }
    if (!constantTimeEquals(request.headers.get("X-Relay-Secret") ?? "", env.RELAY_SECRET)) {
      return new Response("unauthorized", { status: 401 });
    }

    // arrayBuffer, not text: the body is forwarded byte for byte, so nothing
    // here can mangle the Thai and the emoji every message is made of.
    // Decoding and re-encoding would usually be harmless and is pure risk.
    //
    // The query string is carried over so ?wait=true works through the relay
    // -- that's what makes Discord return the created message, which is the
    // only way to check from outside that the text arrived intact.
    const query = new URL(request.url).search;
    const upstream = await fetch(env.DISCORD_WEBHOOK_URL + query, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: await request.arrayBuffer(),
    });

    // Discord's status and Retry-After are passed through untouched: the
    // caller's rate-limit handling (and its outbox cooldown) reads them, and a
    // relay that swallowed a 429 would just move the problem one hop away.
    const headers = new Headers();
    for (const name of ["Retry-After", "X-RateLimit-Remaining", "X-RateLimit-Reset-After"]) {
      const value = upstream.headers.get(name);
      if (value !== null) headers.set(name, value);
    }
    return new Response(await upstream.text(), { status: upstream.status, headers });
  },
};
