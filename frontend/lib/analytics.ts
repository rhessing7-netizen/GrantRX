/**
 * Lightweight analytics hook (R3).
 *
 * No analytics vendor is currently configured for this project. When a GA4
 * measurement ID is provided via NEXT_PUBLIC_GA_MEASUREMENT_ID, the
 * <GoogleAnalytics /> component in the root layout loads gtag.js and this
 * helper forwards events to it. Without the env var this is a silent no-op —
 * it is always safe to call.
 *
 * Privacy rule: NEVER pass PII (email, name, raw form values) through this
 * helper — event names and coarse, non-identifying parameters only.
 */

export function trackEvent(
  name: string,
  params?: Record<string, string | number | boolean>,
): void {
  if (typeof window === "undefined") return;
  const gtag = (window as { gtag?: unknown }).gtag;
  if (typeof gtag !== "function") return;
  try {
    (gtag as (...args: unknown[]) => void)("event", name, params ?? {});
  } catch {
    // Analytics must never break the user experience.
  }
}
