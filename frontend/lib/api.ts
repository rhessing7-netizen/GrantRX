import type {
  BillingPlan,
  CalendarEvent,
  CalendarFeedInfo,
  CheckoutResponse,
  EssayOutlineResponse,
  FinancialPlanner,
  MatchedFeed,
  Profile,
  ProfileCreate,
  ProfileUpdate,
  StudentCollegeBudgetUpdate,
  Usage,
  UserScholarship,
  UserScholarshipCreate,
  UserScholarshipUpdate,
} from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Auth token management
//
// In production, the token comes from Supabase Auth (set via setAuthToken).
// In local dev, we auto-generate a demo token so the app works out-of-the-box
// without requiring a full OAuth login flow.
//
// Priority:
//   1. Explicit token set via setAuthToken() (real Supabase session)
//   2. NEXT_PUBLIC_DEMO_JWT env var (pre-signed JWT for testing)
//   3. Auto-generated demo token "grantrx-dev-demo" (accepted by backend in dev mode)
// ---------------------------------------------------------------------------

const DEMO_TOKEN_FALLBACK = "grantrx-dev-demo";

let authToken: string | null =
  process.env.NEXT_PUBLIC_DEMO_JWT ?? DEMO_TOKEN_FALLBACK;

export function setAuthToken(token: string | null) {
  authToken = token;
}

export function getAuthToken(): string | null {
  return authToken;
}

function authHeaders(): HeadersInit {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }
  return headers;
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${API_BASE}${path}`;

  // Guard against invalid URLs that would cause "Failed to execute 'fetch'"
  if (!url || !/^https?:\/\/.+/i.test(url)) {
    const e = new Error(
      "API endpoint is not configured. Please set NEXT_PUBLIC_API_URL.",
    ) as Error & { status?: number; body?: unknown };
    e.status = 0;
    throw e;
  }

  let resp: Response;
  try {
    resp = await fetch(url, {
      ...options,
      headers: { ...authHeaders(), ...(options.headers ?? {}) },
      signal: AbortSignal.timeout(15000),
    });
  } catch (err) {
    // Network error, timeout, or DNS failure
    const e = new Error(
      err instanceof Error && err.name === "TimeoutError"
        ? "Request timed out. Please check your connection and try again."
        : "Network error. Please check your connection and try again.",
    ) as Error & { status?: number; body?: unknown };
    e.status = 0;
    throw e;
  }

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ detail: resp.statusText }));
    const err = new Error(
      typeof body.detail === "string"
        ? body.detail
        : JSON.stringify(body.detail ?? body),
    ) as Error & { status?: number; body?: unknown };
    err.status = resp.status;
    err.body = body;
    throw err;
  }

  if (resp.status === 204) {
    return undefined as T;
  }
  return resp.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Blob download helper — triggers a browser file download from a Blob
// ---------------------------------------------------------------------------

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Profile
// ---------------------------------------------------------------------------

export const api = {
  getProfile: () => request<Profile>("/profiles/me"),
  createProfile: (data: ProfileCreate) =>
    request<Profile>("/profiles", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateProfile: (data: ProfileUpdate) =>
    request<Profile>("/profiles", {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  // Matching
  // - query: optional keyword search string. When non-empty, consumes a
  //   search quota for free-tier users. When empty/omitted, the request is
  //   a free match refresh or faceted filter change (no quota deduction).
  getMatchedScholarships: (query?: string) => {
    const qs = query && query.trim() ? `?query=${encodeURIComponent(query.trim())}` : "";
    return request<MatchedFeed>(`/api/scholarships/matched${qs}`);
  },
  getUsage: () => request<Usage>("/api/user/usage"),

  // Feed curation (hide/dismiss)
  dismissScholarship: (id: string) =>
    request<{ status: string; scholarship_id: string }>(
      `/api/scholarships/${id}/dismiss`,
      { method: "POST" },
    ),
  undismissScholarship: (id: string) =>
    request<{ status: string; scholarship_id: string }>(
      `/api/scholarships/${id}/undismiss`,
      { method: "POST" },
    ),

  // Kanban tracking
  listUserScholarships: () => request<UserScholarship[]>("/user-scholarships"),
  trackScholarship: (data: UserScholarshipCreate) =>
    request<UserScholarship>("/user-scholarships", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateTracking: (id: string, data: UserScholarshipUpdate) =>
    request<UserScholarship>(`/user-scholarships/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  deleteTracking: (id: string) =>
    request<void>(`/user-scholarships/${id}`, { method: "DELETE" }),

  // Calendar
  getCalendarEvents: () => request<CalendarEvent[]>("/api/calendar/events"),
  getFeedUrl: () => request<CalendarFeedInfo>("/api/calendar/feed-url"),

  // Billing
  createCheckout: (plan: BillingPlan, successUrl?: string, cancelUrl?: string) =>
    request<CheckoutResponse>("/api/billing/create-checkout-session", {
      method: "POST",
      body: JSON.stringify({
        plan,
        success_url: successUrl,
        cancel_url: cancelUrl,
      }),
    }),
  createBillingPortalSession: () =>
    request<{ url: string }>("/api/v1/billing/portal", { method: "POST" }),
  submitCancellationFeedback: (
    reason: string,
    awardAmount?: number,
    comments?: string,
  ) =>
    request<{ id: string; reason: string }>(
      "/api/v1/billing/cancellation-feedback",
      {
        method: "POST",
        body: JSON.stringify({
          reason,
          award_amount: awardAmount,
          comments,
        }),
      },
    ),
  deleteAccount: () =>
    request<{ status: string; message: string }>("/api/v1/profile/me", {
      method: "DELETE",
    }),

  // Scholarship issue reporting
  reportScholarship: (
    scholarshipId: string,
    reason: "broken_link" | "inaccurate_deadline" | "expired",
    notes?: string,
  ) =>
    request<{ id: string; status: string }>(
      `/api/v1/scholarships/${scholarshipId}/report`,
      {
        method: "POST",
        body: JSON.stringify({ reason, notes }),
      },
    ),

  // Financial Planner
  getFinancialPlanner: () =>
    request<FinancialPlanner>("/api/v1/financial-planner/budget"),
  updateFinancialPlanner: (data: StudentCollegeBudgetUpdate) =>
    request<FinancialPlanner>("/api/v1/financial-planner/budget", {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  // Exports — Calendar & Asana
  getGcalUrl: (scholarshipId: string) =>
    request<{ url: string }>(
      `/api/v1/planner/export/gcal-url/${scholarshipId}`,
    ),
  downloadAsanaCsv: async () => {
    const resp = await fetch(
      `${API_BASE}/api/v1/planner/export/asana-csv`,
      { headers: authHeaders(), signal: AbortSignal.timeout(15000) },
    );
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(
        typeof body.detail === "string" ? body.detail : "Download failed",
      );
    }
    const blob = await resp.blob();
    triggerDownload(blob, "grantrx_planner_asana.csv");
  },
  downloadIcsCalendar: async () => {
    const resp = await fetch(
      `${API_BASE}/api/v1/planner/export/calendar.ics`,
      { headers: authHeaders(), signal: AbortSignal.timeout(15000) },
    );
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(
        typeof body.detail === "string" ? body.detail : "Download failed",
      );
    }
    const blob = await resp.blob();
    triggerDownload(blob, "grantrx_deadlines.ics");
  },

  // AI Statement Coach — Essay Outline
  generateEssayOutline: (
    scholarshipId: string,
    payload: {
      prompt?: string;
      word_limit?: number;
      user_discipline?: string;
      user_credential?: string;
      lived_experience_notes?: string;
      work_volunteer_experience?: string;
      academic_topics_of_interest?: string;
    },
  ) =>
    request<EssayOutlineResponse>(
      `/api/v1/scholarships/${scholarshipId}/outline`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),
};
