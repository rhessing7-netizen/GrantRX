"use client";

import { createBrowserClient } from "@supabase/ssr";

/**
 * Supabase browser client for client-side auth.
 *
 * Uses NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY from .env.local.
 * In local dev without Supabase configured, the client is null and the app
 * falls back to the demo token flow (see lib/api.ts).
 */
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export const supabase =
  supabaseUrl && supabaseAnonKey
    ? createBrowserClient(supabaseUrl, supabaseAnonKey)
    : null;

export type SupabaseClient = NonNullable<typeof supabase>;
