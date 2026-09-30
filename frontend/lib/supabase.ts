import { createBrowserClient } from '@supabase/ssr';
import type { SupabaseClient } from '@supabase/supabase-js';

/**
 * Resolve the Supabase URL, validating that it is a proper HTTP/HTTPS URL.
 * On Vercel, NEXT_PUBLIC_SUPABASE_URL may be set to a truthy-but-invalid
 * value (e.g. the string "undefined", a URL without a protocol, or
 * whitespace). The || operator alone won't catch those, so we explicitly
 * validate with the URL constructor.
 * Also scrubs quotes, spaces, and newlines that can cause fetch "Invalid value" errors.
 *
 * There is intentionally NO built-in project fallback: an unset or malformed
 * configuration must never silently attach this build to an unintended
 * Supabase project (e.g. a staging build reaching the production project).
 * Missing/invalid config yields `supabase === null`, and every consumer
 * already guards on that — the UI degrades to a clear signed-out /
 * "authentication is not configured" state instead of talking to the wrong
 * backend.
 */
function resolveSupabaseUrl(): string | null {
  const raw = process.env.NEXT_PUBLIC_SUPABASE_URL;
  if (raw) {
    try {
      const cleaned = raw.trim().replace(/[\r\n"']/g, '');
      const parsed = new URL(cleaned);
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        return cleaned;
      }
    } catch {
      // not a valid URL — fall through to null
    }
  }
  return null;
}

function resolveSupabaseAnonKey(): string | null {
  const raw = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!raw) return null;
  const cleaned = raw.trim().replace(/[\r\n"']/g, '');
  return cleaned || null;
}

const supabaseUrl = resolveSupabaseUrl();
const supabaseAnonKey = resolveSupabaseAnonKey();

if (!supabaseUrl || !supabaseAnonKey) {
  console.warn(
    'Supabase is not configured (NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY). ' +
      'Auth-dependent features are disabled for this build.',
  );
}

export const supabase: SupabaseClient | null =
  supabaseUrl && supabaseAnonKey
    ? createBrowserClient(supabaseUrl, supabaseAnonKey)
    : null;
