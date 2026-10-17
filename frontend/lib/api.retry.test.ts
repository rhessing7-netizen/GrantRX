/**
 * Transport retry tests — run with:
 *   node --test --experimental-strip-types lib/api.retry.test.ts
 *   (Node >=23 runs .ts natively; the flag is a no-op safeguard.)
 *
 * Policy under test:
 *   - A genuine transport failure (status-0: timeout/network/DNS) on a
 *     safe idempotent read (GET/HEAD) is retried exactly ONCE.
 *   - A second failure surfaces the final error.
 *   - HTTP 4xx/5xx responses are never retried by this mechanism.
 *   - Mutations (POST/PUT/DELETE/etc.) are never auto-retried.
 *   - Caller-initiated AbortError is rethrown and never retried.
 */

import test from "node:test";
import assert from "node:assert/strict";
import {
  api,
  setAuthToken,
  __setFetchImpl,
  __setRetryDelayMs,
} from "./api.ts";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const PROFILE_BODY = { id: "u-1", email: "t@example.com" };

test.beforeEach(() => {
  setAuthToken("test.jwt.token");
  __setRetryDelayMs(1);
});

test.afterEach(() => {
  __setFetchImpl(null);
  setAuthToken(null);
});

test("GET: first transport failure retries once and succeeds", async () => {
  let calls = 0;
  let retried = false;
  __setFetchImpl((() => {
    calls++;
    if (calls === 1) return Promise.reject(new TypeError("fetch failed"));
    return Promise.resolve(jsonResponse(PROFILE_BODY));
  }) as typeof fetch);

  // Exercise the hook-bearing read path via getMatchedScholarships' hook.
  const profile = await api.getProfile();
  assert.equal(calls, 2);
  assert.equal(profile.id, "u-1");

  // onRetry hook fires on the matched-feed path too.
  let calls2 = 0;
  __setFetchImpl((() => {
    calls2++;
    if (calls2 === 1) return Promise.reject(new TypeError("fetch failed"));
    return Promise.resolve(jsonResponse({ results: [], total: 0, visible: 0 }));
  }) as typeof fetch);
  await api.getMatchedScholarships(undefined, { onRetry: () => (retried = true) });
  assert.equal(calls2, 2);
  assert.equal(retried, true);
});

test("GET: two consecutive transport failures surface the final error", async () => {
  let calls = 0;
  __setFetchImpl((() => {
    calls++;
    return Promise.reject(new TypeError("fetch failed"));
  }) as typeof fetch);

  await assert.rejects(api.getProfile(), (err: unknown) => {
    const e = err as Error & { status: number };
    assert.equal(e.status, 0);
    assert.match(e.message, /network error/i);
    return true;
  });
  assert.equal(calls, 2); // exactly one retry — no loop
});

test("GET: 4xx response is not retried", async () => {
  let calls = 0;
  __setFetchImpl((() => {
    calls++;
    return Promise.resolve(jsonResponse({ detail: "not found" }, 404));
  }) as typeof fetch);

  await assert.rejects(api.getProfile(), (err: unknown) => {
    assert.equal((err as { status: number }).status, 404);
    return true;
  });
  assert.equal(calls, 1);
});

test("GET: 5xx response is not retried", async () => {
  let calls = 0;
  __setFetchImpl((() => {
    calls++;
    return Promise.resolve(jsonResponse({ detail: "boom" }, 500));
  }) as typeof fetch);

  await assert.rejects(api.getProfile(), (err: unknown) => {
    assert.equal((err as { status: number }).status, 500);
    return true;
  });
  assert.equal(calls, 1);
});

test("POST: transport failure is never retried (no duplicate writes)", async () => {
  let calls = 0;
  __setFetchImpl((() => {
    calls++;
    return Promise.reject(new TypeError("fetch failed"));
  }) as typeof fetch);

  await assert.rejects(
    api.updateProfile({ full_name: "x" }),
    (err: unknown) => (err as { status: number }).status === 0,
  );
  assert.equal(calls, 1);
});

test("GET: caller AbortError is rethrown and never retried", async () => {
  let calls = 0;
  __setFetchImpl((() => {
    calls++;
    const err = new Error("aborted");
    err.name = "AbortError";
    return Promise.reject(err);
  }) as typeof fetch);

  await assert.rejects(api.getProfile(), (err: unknown) => {
    assert.equal((err as Error).name, "AbortError");
    return true;
  });
  assert.equal(calls, 1);
});
