export interface MetroOption {
  slug: string;
  name: string;
  shortName: string;
  states: string[];
}

export const TOP_20_METROS: MetroOption[] = [
  { slug: "new_york", name: "New York-Newark-Jersey City", shortName: "NYC Metro", states: ["NY", "NJ", "PA"] },
  { slug: "los_angeles", name: "Los Angeles-Long Beach-Anaheim", shortName: "LA Metro", states: ["CA"] },
  { slug: "chicago", name: "Chicago-Naperville-Elgin", shortName: "Chicagoland", states: ["IL", "IN", "WI"] },
  { slug: "dallas", name: "Dallas-Fort Worth-Arlington", shortName: "DFW Metro", states: ["TX"] },
  { slug: "houston", name: "Houston-Pasadena-The Woodlands", shortName: "Greater Houston", states: ["TX"] },
  { slug: "atlanta", name: "Atlanta-Sandy Springs-Roswell", shortName: "Metro Atlanta", states: ["GA"] },
  { slug: "washington_dc", name: "Washington-Arlington-Alexandria", shortName: "DMV", states: ["DC", "VA", "MD", "WV"] },
  { slug: "miami", name: "Miami-Fort Lauderdale-West Palm Beach", shortName: "South Florida", states: ["FL"] },
  { slug: "philadelphia", name: "Philadelphia-Camden-Wilmington", shortName: "Greater Philadelphia", states: ["PA", "NJ", "DE", "MD"] },
  { slug: "phoenix", name: "Phoenix-Mesa-Chandler", shortName: "Greater Phoenix", states: ["AZ"] },
  { slug: "boston", name: "Boston-Cambridge-Newton", shortName: "Greater Boston", states: ["MA", "NH"] },
  { slug: "riverside", name: "Riverside-San Bernardino-Ontario (Inland Empire)", shortName: "Inland Empire", states: ["CA"] },
  { slug: "san_francisco", name: "San Francisco-Oakland-Fremont", shortName: "Bay Area", states: ["CA"] },
  { slug: "detroit", name: "Detroit-Warren-Dearborn", shortName: "Metro Detroit", states: ["MI"] },
  { slug: "seattle", name: "Seattle-Tacoma-Bellevue", shortName: "Puget Sound", states: ["WA"] },
  { slug: "minneapolis", name: "Minneapolis-St. Paul-Bloomington", shortName: "Twin Cities", states: ["MN", "WI"] },
  { slug: "tampa", name: "Tampa-St. Petersburg-Clearwater", shortName: "Tampa Bay", states: ["FL"] },
  { slug: "san_diego", name: "San Diego-Chula Vista-Carlsbad", shortName: "Greater San Diego", states: ["CA"] },
  { slug: "denver", name: "Denver-Aurora-Centennial", shortName: "Metro Denver", states: ["CO"] },
  { slug: "orlando", name: "Orlando-Kissimmee-Sanford", shortName: "Greater Orlando", states: ["FL"] },
];

/**
 * Resolve a metro restriction value (MSA name, slug, or CBSA code) to a
 * short display name suitable for badges and dropdowns.
 */
export function getMetroShortName(metroValue: string): string {
  // Try exact MSA name match
  const byName = TOP_20_METROS.find((m) => m.name === metroValue);
  if (byName) return byName.shortName;
  // Try slug match
  const bySlug = TOP_20_METROS.find((m) => m.slug === metroValue);
  if (bySlug) return bySlug.shortName;
  // Try CBSA code (e.g. "cbsa:35620")
  if (metroValue.startsWith("cbsa:")) {
    const code = metroValue.slice(5);
    const byCode = TOP_20_METROS.find((m) => m.slug === code);
    if (byCode) return byCode.shortName;
  }
  // Fallback: return as-is (truncated)
  return metroValue.length > 25 ? metroValue.slice(0, 23) + "\u2026" : metroValue;
}

/**
 * Return metros sorted so that those matching the given state code appear
 * first, followed by all others in their original order. Metros matching
 * the state are also flagged with `matchesState: true`.
 */
export function getMetrosForState(stateCode: string): (MetroOption & { matchesState: boolean })[] {
  const sc = stateCode.toUpperCase().trim();
  const matching: (MetroOption & { matchesState: boolean })[] = [];
  const others: (MetroOption & { matchesState: boolean })[] = [];
  for (const m of TOP_20_METROS) {
    const entry = { ...m, matchesState: sc ? m.states.includes(sc) : false };
    if (entry.matchesState) {
      matching.push(entry);
    } else {
      others.push(entry);
    }
  }
  return [...matching, ...others];
}
