type BrandMarkProps = {
  /** Show the tagline lockup. */
  tagline?: boolean;
  /** Compact sizing for tight headers. */
  size?: "sm" | "md";
  className?: string;
  /** Image alt text — leave empty when the logo is decorative inside a labeled link. */
  alt?: string;
};

export function BrandMark({
  tagline = false,
  size = "md",
  className = "",
  alt,
}: BrandMarkProps) {
  const src = tagline
    ? "/brand/edfintia-logo-tagline.svg"
    : "/brand/edfintia-logo.svg";
  const height = tagline ? "h-10" : size === "sm" ? "h-6" : "h-8";
  const defaultAlt = tagline
    ? "EdFintia — Your prescription for education funding."
    : "EdFintia";

  return (
    <img
      src={src}
      alt={alt ?? defaultAlt}
      className={`${height} w-auto object-contain ${className}`}
    />
  );
}
