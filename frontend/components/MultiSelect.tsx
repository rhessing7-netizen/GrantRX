"use client";

import { useState, useRef, useEffect } from "react";

export type MultiSelectProps = {
  options: string[];
  selected: string[];
  onChange: (selected: string[]) => void;
  placeholder?: string;
  label?: string;
  maxHeight?: number;
};

export function MultiSelect({
  options,
  selected,
  onChange,
  placeholder = "Select…",
  label,
  maxHeight = 240,
}: MultiSelectProps) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const toggle = (option: string) => {
    if (selected.includes(option)) {
      onChange(selected.filter((s) => s !== option));
    } else {
      onChange([...selected, option]);
    }
  };

  const remove = (option: string) => {
    onChange(selected.filter((s) => s !== option));
  };

  const filteredOptions = options.filter((o) =>
    o.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <div ref={ref} className="relative">
      {label && (
        <label className="block text-sm font-medium text-textSecondary">
          {label}
        </label>
      )}

      {/* Selected badges + trigger */}
      <div
        onClick={() => setOpen(!open)}
        className="mt-2 flex min-h-[44px] cursor-pointer flex-wrap items-center gap-1.5 rounded-xl border border-textSecondary/20 bg-surfaceBg px-3 py-2"
      >
        {selected.length === 0 && (
          <span className="text-sm text-textSecondary/50">{placeholder}</span>
        )}
        {selected.map((s) => (
          <span
            key={s}
            className="inline-flex items-center gap-1 rounded-full bg-crayolaBlue/10 px-2.5 py-1 text-xs font-medium text-crayolaBlue"
            onClick={(e) => {
              e.stopPropagation();
              remove(s);
            }}
          >
            {s.length > 30 ? s.slice(0, 28) + "…" : s}
            <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </span>
        ))}
        <svg
          className={`ml-auto h-4 w-4 text-textSecondary transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </div>

      {/* Dropdown */}
      {open && (
        <div className="absolute z-20 mt-1 w-full rounded-xl border border-textSecondary/20 bg-surfaceBg shadow-lg">
          {/* Filter input */}
          <div className="border-b border-textSecondary/10 p-2">
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Search…"
              autoFocus
              className="w-full rounded-lg border border-textSecondary/15 bg-surfaceBg px-3 py-1.5 text-sm text-textPrimary placeholder:text-textSecondary/50"
              onClick={(e) => e.stopPropagation()}
            />
          </div>

          {/* Options list */}
          <div className="overflow-y-auto p-1" style={{ maxHeight }}>
            {filteredOptions.length === 0 && (
              <p className="px-3 py-2 text-sm text-textSecondary">No matches found</p>
            )}
            {filteredOptions.map((option) => (
              <label
                key={option}
                className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-textPrimary hover:bg-cardBg"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(option)}
                  onChange={() => toggle(option)}
                  className="h-4 w-4 accent-crayolaBlue"
                />
                <span className="flex-1">{option}</span>
              </label>
            ))}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between border-t border-textSecondary/10 px-3 py-2">
            <button
              onClick={(e) => {
                e.stopPropagation();
                onChange([]);
              }}
              className="text-xs text-textSecondary hover:text-textPrimary"
            >
              Clear all
            </button>
            <span className="text-xs text-textSecondary">
              {selected.length} selected
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
