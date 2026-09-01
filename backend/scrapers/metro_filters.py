"""Top-20 U.S. metropolitan area filters for crawler and LLM extraction.

Maps metro slugs to CBSA identifiers, targeted counties, states, and regional
alias keywords. The crawler uses this to detect geographical targeting in
page text, while the LLM extraction prompt uses it to normalize residency
rules to canonical MSA names or CBSA codes.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional


TOP_20_METROS: Dict[str, dict] = {
    "new_york": {
        "name": "New York-Newark-Jersey City",
        "cbsa_code": "35620",
        "states": ["NY", "NJ", "PA"],
        "target_counties": [
            "new york", "kings", "queens", "bronx", "richmond",
            "westchester", "nassau", "suffolk", "bergen", "hudson", "essex",
        ],
        "metro_keywords": ["nyc", "new york city", "tri-state", "greater new york", "five boroughs"],
    },
    "los_angeles": {
        "name": "Los Angeles-Long Beach-Anaheim",
        "cbsa_code": "31080",
        "states": ["CA"],
        "target_counties": ["los angeles", "orange"],
        "metro_keywords": ["greater los angeles", "la county", "orange county", "socal"],
    },
    "chicago": {
        "name": "Chicago-Naperville-Elgin",
        "cbsa_code": "16980",
        "states": ["IL", "IN", "WI"],
        "target_counties": ["cook", "dupage", "lake", "will", "kane", "mchenry", "porter"],
        "metro_keywords": ["chicagoland", "greater chicago", "cook county"],
    },
    "dallas": {
        "name": "Dallas-Fort Worth-Arlington",
        "cbsa_code": "19100",
        "states": ["TX"],
        "target_counties": ["dallas", "tarrant", "collin", "denton", "ellis", "kaufman", "rockwall"],
        "metro_keywords": ["dfw", "dallas-fort worth", "metroplex", "north texas"],
    },
    "houston": {
        "name": "Houston-Pasadena-The Woodlands",
        "cbsa_code": "26420",
        "states": ["TX"],
        "target_counties": ["harris", "fort bend", "montgomery", "brazoria", "galveston"],
        "metro_keywords": ["greater houston", "harris county", "space city"],
    },
    "atlanta": {
        "name": "Atlanta-Sandy Springs-Roswell",
        "cbsa_code": "12060",
        "states": ["GA"],
        "target_counties": ["fulton", "gwinnett", "cobb", "dekalb", "clayton", "cherokee", "forsyth", "henry"],
        "metro_keywords": ["metro atlanta", "greater atlanta", "fulton county"],
    },
    "washington_dc": {
        "name": "Washington-Arlington-Alexandria",
        "cbsa_code": "47900",
        "states": ["DC", "VA", "MD", "WV"],
        "target_counties": ["fairfax", "loudoun", "prince william", "arlington", "montgomery", "prince george's"],
        "metro_keywords": ["dmv", "dc metro", "national capital region", "greater washington"],
    },
    "miami": {
        "name": "Miami-Fort Lauderdale-West Palm Beach",
        "cbsa_code": "33100",
        "states": ["FL"],
        "target_counties": ["miami-dade", "broward", "palm beach"],
        "metro_keywords": ["south florida", "greater miami", "tri-county area"],
    },
    "philadelphia": {
        "name": "Philadelphia-Camden-Wilmington",
        "cbsa_code": "37980",
        "states": ["PA", "NJ", "DE", "MD"],
        "target_counties": ["philadelphia", "montgomery", "bucks", "delaware", "chester", "camden", "burlington", "new castle"],
        "metro_keywords": ["greater philadelphia", "delaware valley", "philly metro"],
    },
    "phoenix": {
        "name": "Phoenix-Mesa-Chandler",
        "cbsa_code": "38060",
        "states": ["AZ"],
        "target_counties": ["maricopa", "pinal"],
        "metro_keywords": ["valley of the sun", "greater phoenix", "maricopa county"],
    },
    "boston": {
        "name": "Boston-Cambridge-Newton",
        "cbsa_code": "14460",
        "states": ["MA", "NH"],
        "target_counties": ["middlesex", "suffolk", "essex", "norfolk", "plymouth"],
        "metro_keywords": ["greater boston", "metro boston", "boston metro"],
    },
    "riverside": {
        "name": "Riverside-San Bernardino-Ontario",
        "cbsa_code": "40140",
        "states": ["CA"],
        "target_counties": ["riverside", "san bernardino"],
        "metro_keywords": ["inland empire", "the ie", "san bernardino county", "riverside county"],
    },
    "san_francisco": {
        "name": "San Francisco-Oakland-Fremont",
        "cbsa_code": "41860",
        "states": ["CA"],
        "target_counties": ["san francisco", "alameda", "contra costa", "san mateo", "marin"],
        "metro_keywords": ["bay area", "sf bay area", "east bay", "san francisco bay"],
    },
    "detroit": {
        "name": "Detroit-Warren-Dearborn",
        "cbsa_code": "19820",
        "states": ["MI"],
        "target_counties": ["wayne", "oakland", "macomb"],
        "metro_keywords": ["metro detroit", "southeast michigan", "greater detroit"],
    },
    "seattle": {
        "name": "Seattle-Tacoma-Bellevue",
        "cbsa_code": "42660",
        "states": ["WA"],
        "target_counties": ["king", "pierce", "snohomish"],
        "metro_keywords": ["puget sound", "greater seattle", "seattle metro", "king county"],
    },
    "minneapolis": {
        "name": "Minneapolis-St. Paul-Bloomington",
        "cbsa_code": "33460",
        "states": ["MN", "WI"],
        "target_counties": ["hennepin", "ramsey", "dakota", "anoka", "washington", "scott"],
        "metro_keywords": ["twin cities", "minneapolis-st. paul", "metro twin cities"],
    },
    "tampa": {
        "name": "Tampa-St. Petersburg-Clearwater",
        "cbsa_code": "45300",
        "states": ["FL"],
        "target_counties": ["hillsborough", "pinellas", "pasco", "hernando"],
        "metro_keywords": ["tampa bay", "tampa bay area", "hillsborough county"],
    },
    "san_diego": {
        "name": "San Diego-Chula Vista-Carlsbad",
        "cbsa_code": "41740",
        "states": ["CA"],
        "target_counties": ["san diego"],
        "metro_keywords": ["san diego county", "greater san diego"],
    },
    "denver": {
        "name": "Denver-Aurora-Centennial",
        "cbsa_code": "19740",
        "states": ["CO"],
        "target_counties": ["denver", "arapahoe", "jefferson", "adams", "douglas"],
        "metro_keywords": ["metro denver", "greater denver", "mile high metro", "front range"],
    },
    "orlando": {
        "name": "Orlando-Kissimmee-Sanford",
        "cbsa_code": "36740",
        "states": ["FL"],
        "target_counties": ["orange", "seminole", "osceola", "lake"],
        "metro_keywords": ["greater orlando", "central florida", "orange county fl"],
    },
}


# Pre-compute lookup indexes for fast scanning
_ALL_COUNTIES: Dict[str, str] = {}   # county_name -> metro_slug
_ALL_KEYWORDS: Dict[str, str] = {}   # keyword -> metro_slug

for _slug, _data in TOP_20_METROS.items():
    for _county in _data["target_counties"]:
        _ALL_COUNTIES[_county.lower()] = _slug
    for _kw in _data["metro_keywords"]:
        _ALL_KEYWORDS[_kw.lower()] = _slug


def _build_word_boundary_pattern(term: str) -> re.Pattern:
    """Build a regex pattern that matches the term as a whole word/phrase.

    Uses lookarounds so that county names like 'king' don't match inside
    'thinking' or 'booking', and 'cook' doesn't match inside 'cooking'.
    Hyphens and apostrophes are treated as valid word characters.
    """
    escaped = re.escape(term)
    # Word boundary that treats hyphens and apostrophes as part of the word
    return re.compile(r"(?<![a-z'\-])" + escaped + r"(?![a-z'\-])", re.IGNORECASE)


# Pre-compile patterns for performance
_COUNTY_PATTERNS: Dict[str, re.Pattern] = {
    county: _build_word_boundary_pattern(county) for county in _ALL_COUNTIES
}
_KEYWORD_PATTERNS: Dict[str, re.Pattern] = {
    kw: _build_word_boundary_pattern(kw) for kw in _ALL_KEYWORDS
}


def detect_metro_area(text: str) -> Optional[str]:
    """Scan text for matching county names or metro alias keywords.

    Returns the metro slug (e.g. "new_york") of the first match, or None
    if no top-20 metro area is detected.

    Uses word-boundary matching to avoid false positives (e.g. "king"
    matching inside "thinking").
    """
    if not text:
        return None

    # Check metro keywords first (more specific, e.g. "bay area", "dmv")
    for kw, slug in _ALL_KEYWORDS.items():
        if _KEYWORD_PATTERNS[kw].search(text):
            return slug

    # Then check county names
    for county, slug in _ALL_COUNTIES.items():
        if _COUNTY_PATTERNS[county].search(text):
            return slug

    return None


def detect_all_metros(text: str) -> List[str]:
    """Scan text and return ALL matching metro slugs (deduplicated)."""
    if not text:
        return []
    found: List[str] = []
    seen = set()

    for kw, slug in _ALL_KEYWORDS.items():
        if _KEYWORD_PATTERNS[kw].search(text) and slug not in seen:
            found.append(slug)
            seen.add(slug)

    for county, slug in _ALL_COUNTIES.items():
        if _COUNTY_PATTERNS[county].search(text) and slug not in seen:
            found.append(slug)
            seen.add(slug)

    return found


def metro_name(slug: str) -> str:
    """Return the human-readable MSA name for a metro slug."""
    data = TOP_20_METROS.get(slug)
    return data["name"] if data else slug


def metro_cbsa(slug: str) -> str:
    """Return the CBSA code for a metro slug."""
    data = TOP_20_METROS.get(slug)
    return data["cbsa_code"] if data else ""
