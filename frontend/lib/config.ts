/** Central public EdFintia runtime configuration. */
export const APP_URL = (process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000").replace(/\/$/, "");
export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
export const PRIVACY_EMAIL = process.env.NEXT_PUBLIC_PRIVACY_EMAIL || "privacy@grantrx.com";
/** Public contact for website operators about EdFintiaBot. Falls back to the
 * existing public privacy address until a dedicated address is configured. */
export const CRAWLER_CONTACT_EMAIL = process.env.NEXT_PUBLIC_CRAWLER_CONTACT_EMAIL || PRIVACY_EMAIL;
