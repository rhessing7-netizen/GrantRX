"use client";

import { DEGREE_LEVELS, CREDENTIALS_BY_LEVEL, type DegreeLevel } from "@/lib/constants/credentials";

export type CascadingCredentialSelectProps = {
  label?: string;
  selectedLevel: DegreeLevel | "";
  selectedCredential: string;
  onLevelChange: (level: DegreeLevel | "") => void;
  onCredentialChange: (credential: string) => void;
};

export function CascadingCredentialSelect({
  label = "Degree & Credential",
  selectedLevel,
  selectedCredential,
  onLevelChange,
  onCredentialChange,
}: CascadingCredentialSelectProps) {
  const credentials = selectedLevel ? CREDENTIALS_BY_LEVEL[selectedLevel] : [];

  return (
    <div className="space-y-3">
      <label className="block text-sm font-medium text-textMuted">
        {label}
      </label>

      {/* Step 1: Degree Level */}
      <select
        value={selectedLevel}
        onChange={(e) => {
          const level = e.target.value as DegreeLevel | "";
          onLevelChange(level);
          // Clear the credential only when it isn't valid for the new level —
          // never silently drop a previously saved selection.
          if (
            selectedCredential &&
            (!level || !CREDENTIALS_BY_LEVEL[level].includes(selectedCredential))
          ) {
            onCredentialChange("");
          }
        }}
        className="w-full rounded-xl border border-textMuted/20 bg-surface px-4 py-2.5 text-text"
      >
        <option value="">Select degree level…</option>
        {DEGREE_LEVELS.map((lvl) => (
          <option key={lvl.value} value={lvl.value}>
            {lvl.label}
          </option>
        ))}
      </select>

      {/* Step 2: Specific credential — only shown after degree level is selected */}
      {selectedLevel && (
        <select
          value={selectedCredential}
          onChange={(e) => onCredentialChange(e.target.value)}
          className="w-full rounded-xl border border-textMuted/20 bg-surface px-4 py-2.5 text-text transition"
        >
          <option value="">Select specific credential…</option>
          {credentials.map((cred) => (
            <option key={cred} value={cred}>
              {cred}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
