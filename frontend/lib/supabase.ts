import { createBrowserClient } from '@supabase/ssr';

const FALLBACK_SUPABASE_URL = 'https://bcsniblbexmugkypbrff.supabase.co';
const FALLBACK_SUPABASE_ANON_KEY = 'dummy-anon-key';

/**
 * Resolve the Supabase URL, validating that it is a proper HTTP/HTTPS URL.
 * On Vercel, NEXT_PUBLIC_SUPABASE_URL may be set to a truthy-but-invalid
 * value (e.g. the string "undefined", a URL without a protocol, or
 * whitespace). The || operator alone won't catch those, so we explicitly
 * validate with the URL constructor and fall back to a known-good URL.
 * Also scrubs quotes, spaces, and newlines that can cause fetch "Invalid value" errors.
 */
function resolveSupabaseUrl(): string {
  const raw = process.env.NEXT_PUBLIC_SUPABASE_URL;
  if (raw) {
    try {
      const cleaned = raw.trim().replace(/[\r\n"']/g, '');
      const parsed = new URL(cleaned);
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        return cleaned;
      }
    } catch {
      // not a valid URL — fall through to fallback
    }
  }
  return FALLBACK_SUPABASE_URL;
}

const supabaseUrl = resolveSupabaseUrl();
const rawKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || FALLBACK_SUPABASE_ANON_KEY;
const supabaseAnonKey = rawKey.trim().replace(/[\r\n"']/g, '');

export const supabase = createBrowserClient(supabaseUrl, supabaseAnonKey);
