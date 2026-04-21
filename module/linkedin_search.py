"""LinkedIn Company Search API client using the Voyager GraphQL endpoint."""

import csv
import json
import os
import random
import time
import urllib.parse
from base64 import b64decode
from typing import Optional

from curl_cffi import requests as curl_requests
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from module.paths import PROGRESS_DIR, PROJECT_ROOT, RESULTS_DIR

# Load .env from project root
load_dotenv(PROJECT_ROOT / ".env")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TextViewModel(BaseModel):
    text: Optional[str] = None
    text_direction: Optional[str] = Field(None, alias="textDirection")
    attributes_v2: Optional[list] = Field(None, alias="attributesV2")
    accessibility_text: Optional[str] = Field(None, alias="accessibilityText")


class VectorArtifact(BaseModel):
    width: Optional[int] = None
    height: Optional[int] = None
    file_identifying_url: Optional[str] = Field(None, alias="fileIdentifyingUrlPathSegment")
    expires_at: Optional[int] = Field(None, alias="expiresAt")


class VectorImage(BaseModel):
    root_url: Optional[str] = Field(None, alias="rootUrl")
    artifacts: Optional[list[VectorArtifact]] = None


class NonEntityCompanyLogo(BaseModel):
    vector_image: Optional[VectorImage] = Field(None, alias="vectorImage")


class ImageDetailData(BaseModel):
    company_logo: Optional[dict] = Field(None, alias="companyLogo")
    non_entity_company_logo: Optional[NonEntityCompanyLogo] = Field(None, alias="nonEntityCompanyLogo")
    image_url: Optional[str] = Field(None, alias="imageUrl")


class ImageAttribute(BaseModel):
    detail_data: Optional[ImageDetailData] = Field(None, alias="detailData")


class ImageViewModel(BaseModel):
    attributes: Optional[list[ImageAttribute]] = None
    accessibility_text: Optional[str] = Field(None, alias="accessibilityText")


class NavigationContext(BaseModel):
    url: Optional[str] = None
    open_externally: Optional[bool] = Field(None, alias="openExternally")


class EntityResultViewModel(BaseModel):
    """A single company result from the LinkedIn search response."""
    # Core text fields
    title: Optional[TextViewModel] = None
    primary_subtitle: Optional[TextViewModel] = Field(None, alias="primarySubtitle")
    secondary_subtitle: Optional[TextViewModel] = Field(None, alias="secondarySubtitle")
    summary: Optional[TextViewModel] = None

    # Navigation
    navigation_url: Optional[str] = Field(None, alias="navigationUrl")
    navigation_context: Optional[NavigationContext] = Field(None, alias="navigationContext")
    bserp_entity_navigational_url: Optional[str] = Field(None, alias="bserpEntityNavigationalUrl")
    actor_navigation_url: Optional[str] = Field(None, alias="actorNavigationUrl")
    actor_navigation_context: Optional[dict] = Field(None, alias="actorNavigationContext")

    # Tracking / URNs
    tracking_urn: Optional[str] = Field(None, alias="trackingUrn")
    tracking_id: Optional[str] = Field(None, alias="trackingId")
    entity_urn: Optional[str] = Field(None, alias="entityUrn")
    actor_tracking_urn: Optional[str] = Field(None, alias="actorTrackingUrn")

    # Image / logo
    image: Optional[ImageViewModel] = None

    # Actions
    primary_actions: Optional[list] = Field(None, alias="primaryActions")
    overflow_actions: Optional[list] = Field(None, alias="overflowActions")
    lazy_loaded_actions: Optional[str] = Field(None, alias="*lazyLoadedActions")

    # Insights
    actor_insights: Optional[list] = Field(None, alias="actorInsights")
    insights_resolution_results: Optional[list] = Field(None, alias="insightsResolutionResults")

    # Badges
    badge_text: Optional[str] = Field(None, alias="badgeText")
    badge_icon: Optional[object] = Field(None, alias="badgeIcon")  # Can be str or ImageViewModel dict
    badge_data: Optional[dict] = Field(None, alias="badgeData")
    ring_status: Optional[object] = Field(None, alias="ringStatus")  # Can be str or dict

    # Misc
    template: Optional[str] = None
    add_entity_to_search_history: Optional[bool] = Field(None, alias="addEntityToSearchHistory")
    show_additional_cluster: Optional[bool] = Field(None, alias="showAdditionalCluster")
    search_action_type: Optional[str] = Field(None, alias="searchActionType")
    control_name: Optional[str] = Field(None, alias="controlName")
    entity_custom_tracking_info: Optional[dict] = Field(None, alias="entityCustomTrackingInfo")
    entity_embedded_object: Optional[dict] = Field(None, alias="entityEmbeddedObject")
    interstitial_component: Optional[dict] = Field(None, alias="interstitialComponent")
    target: Optional[dict] = None
    unread_indicator_details: Optional[dict] = Field(None, alias="unreadIndicatorDetails")
    recipe_types: Optional[list] = Field(None, alias="$recipeTypes")
    type_name: Optional[str] = Field(None, alias="$type")

    model_config = {"populate_by_name": True}

    # ---- Convenience properties ----

    @property
    def name(self) -> str:
        return self.title.text if self.title and self.title.text else ""

    @property
    def location(self) -> str:
        return self.primary_subtitle.text if self.primary_subtitle and self.primary_subtitle.text else ""

    @property
    def followers(self) -> str:
        return self.secondary_subtitle.text if self.secondary_subtitle and self.secondary_subtitle.text else ""

    @property
    def description(self) -> str:
        """Extract plain text from summary (without formatting attributes)."""
        return self.summary.text if self.summary and self.summary.text else ""

    @property
    def logo_url(self) -> str:
        """Extract the company logo URL from the image field."""
        if not self.image or not self.image.attributes:
            return ""
        for attr in self.image.attributes:
            if attr.detail_data:
                # Check nonEntityCompanyLogo first
                if attr.detail_data.non_entity_company_logo:
                    logo = attr.detail_data.non_entity_company_logo
                    if logo.vector_image and logo.vector_image.artifacts:
                        for artifact in logo.vector_image.artifacts:
                            if artifact.file_identifying_url:
                                return artifact.file_identifying_url
                # Fallback to imageUrl
                if attr.detail_data.image_url:
                    return attr.detail_data.image_url
                # Fallback to companyLogo
                if attr.detail_data.company_logo:
                    return attr.detail_data.company_logo.get("imageUrl", "")
        return ""

    @property
    def company_id(self) -> str:
        """Extract the numeric LinkedIn company ID from the tracking URN."""
        if self.tracking_urn and ":" in self.tracking_urn:
            # e.g. "urn:li:company:85654841"
            parts = self.tracking_urn.split(":")
            return parts[-1] if parts else ""
        return ""

    def to_dict(self) -> dict:
        """Export all fields as a flat dictionary."""
        return {
            "name": self.name,
            "company_id": self.company_id,
            "tracking_urn": self.tracking_urn,
            "tracking_id": self.tracking_id,
            "entity_urn": self.entity_urn,
            "description": self.description,
            "followers": self.followers,
            "location": self.location,
            "url": self.navigation_url,
            "logo_url": self.logo_url,
            "bserp_entity_navigational_url": self.bserp_entity_navigational_url,
            "template": self.template,
            "badge_text": self.badge_text,
            "actor_insights_count": len(self.actor_insights) if self.actor_insights else 0,
            "primary_actions_count": len(self.primary_actions) if self.primary_actions else 0,
            "add_entity_to_search_history": self.add_entity_to_search_history,
            "show_additional_cluster": self.show_additional_cluster,
        }

    def to_minimal_dict(self) -> dict:
        """Export only essential fields for CSV conversion."""
        return {
            "company_name": self.name,
            "industry_location": self.location,
            "followers": self.followers,
            "description": self.description,
            "logo_url": self.logo_url,
            "company_page_url": self.navigation_url,
            "company_urn": self.tracking_urn,
        }


class SearchMetadata(BaseModel):
    total_result_count: int = Field(alias="totalResultCount")
    search_id: str = Field(alias="searchId")
    primary_result_type: Optional[str] = Field(None, alias="primaryResultType")
    filter_applied_count: Optional[int] = Field(None, alias="filterAppliedCount")
    blocked_query: Optional[bool] = Field(None, alias="blockedQuery")
    query_type: Optional[str] = Field(None, alias="queryType")
    pagination_token: Optional[str] = Field(None, alias="paginationToken")
    entity_action_button_style: Optional[str] = Field(None, alias="entityActionButtonStyle")
    cluster_title_font_size: Optional[str] = Field(None, alias="clusterTitleFontSize")


class PaginationMetadata(BaseModel):
    count: int
    start: int
    total: int


class SearchResponse(BaseModel):
    """Parsed LinkedIn company search response."""
    metadata: SearchMetadata
    paging: PaginationMetadata
    companies: list[EntityResultViewModel]


# ---------------------------------------------------------------------------
# Geo Typeahead models & functions
# ---------------------------------------------------------------------------

class GeoResult(BaseModel):
    """A single geo location result from LinkedIn's typeahead API."""
    title: Optional[str] = None
    subtitle: Optional[str] = None
    tracking_urn: Optional[str] = None
    entity_urn: Optional[str] = None
    type: Optional[str] = None
    # The *geo field from target — e.g. "urn:li:fsd_geo:106164952"
    fsd_geo_urn: Optional[str] = None

    @property
    def geo_id(self) -> str:
        """Extract the numeric geo ID from the FSD geo URN."""
        if self.fsd_geo_urn and ":" in self.fsd_geo_urn:
            parts = self.fsd_geo_urn.split(":")
            return parts[-1] if parts else ""
        # Fallback: try tracking_urn
        if self.tracking_urn and "geo:" in self.tracking_urn:
            parts = self.tracking_urn.split(":")
            return parts[-1] if parts else ""
        return ""


class GeoTypeaheadResponse(BaseModel):
    """Parsed LinkedIn geo typeahead response."""
    locations: list[GeoResult]
    raw_count: int = 0


def _build_anti_bot_headers(
    keywords: Optional[str] = None,
    page_instance: Optional[str] = None,
    geo_urn: Optional[str] = None,
) -> dict:
    """Build complete anti-bot headers matching real Firefox browser."""
    # Generate random device tracking values
    timezone = random.choice(["Asia/Kolkata", "America/New_York", "Europe/London", "Asia/Tokyo"])
    offset_map = {
        "Asia/Kolkata": 5.5,
        "America/New_York": -5,
        "Europe/London": 0,
        "Asia/Tokyo": 9,
    }
    offset = offset_map[timezone]
    display_width = random.choice([1920, 2560, 1366, 1440])
    display_height = random.choice([1080, 1440, 768, 900])
    display_density = 1 if display_width <= 1920 else 2

    if not page_instance:
        # Generate a random page instance ID (base64-like)
        page_instance = b64decode("j8aQsSy5Q4OMnvQZbAdDTA==").hex()
        page_instance = page_instance[:20]

    headers = {
        "Accept": "application/vnd.linkedin.normalized+json+2.1",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Pragma": "no-cache",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "TE": "trailers",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64; rv:148.0) "
            "Gecko/20100101 Firefox/148.0"
        ),
        "x-li-lang": "en_US",
        "x-li-page-instance": f"urn:li:page:d_flagship3_search_srp_companies;{page_instance}",
        "x-li-pem-metadata": "Voyager - Companies SRP=search-results",
        "x-li-track": json.dumps({
            "clientVersion": "1.13.43510",
            "mpVersion": "1.13.43510",
            "osName": "web",
            "timezoneOffset": offset,
            "timezone": timezone,
            "deviceFormFactor": "DESKTOP",
            "mpName": "voyager-web",
            "displayDensity": display_density,
            "displayWidth": display_width,
            "displayHeight": display_height,
        }, separators=(",", ":")),
        "x-restli-protocol-version": "2.0.0",
    }

    if keywords:
        # Build referer matching browser's format
        if geo_urn:
            geo_param = f"companyHqGeo=%5B%22{geo_urn}%22%5D&"
            headers["Referer"] = (
                f"https://www.linkedin.com/search/results/companies/"
                f"?{geo_param}"
                f"keywords={keywords}"
                f"&origin=FACETED_SEARCH"
                f"&sid=E%40a"
            )
        else:
            headers["Referer"] = (
                f"https://www.linkedin.com/search/results/companies/"
                f"?keywords={keywords}"
                f"&origin=GLOBAL_SEARCH_HEADER"
            )

    return headers


def _anti_bot_sleep() -> None:
    """Random delay mimicking human browsing patterns (0.5-2s)."""
    time.sleep(random.uniform(0.5, 2.0))


def _create_session(
    cookie: Optional[str] = None,
    csrf_token: Optional[str] = None,
    keywords: Optional[str] = None,
    page_instance: Optional[str] = None,
    geo_urn: Optional[str] = None,
) -> curl_requests.Session:
    """Create a curl_cffi session with Firefox TLS fingerprint."""
    cookie = cookie or os.environ.get("LI_COOKIE", "")
    csrf_token = csrf_token or os.environ.get("LI_CSRF_TOKEN", "")
    headers = _build_anti_bot_headers(
        keywords=keywords,
        page_instance=page_instance,
        geo_urn=geo_urn,
    )
    headers["Cookie"] = cookie
    if csrf_token:
        headers["csrf-token"] = csrf_token

    # Use impersonate="firefox" to match Firefox 148 TLS fingerprint (JA3)
    session = curl_requests.Session(impersonate="firefox")
    session.headers.update(headers)
    return session


def search_geo_locations(
    keywords: str,
    cookie: Optional[str] = None,
    csrf_token: Optional[str] = None,
) -> GeoTypeaheadResponse:
    """Search for geo locations using LinkedIn's typeahead API.

    This endpoint returns location suggestions that can be used as
    filters in company/person searches.  Response values may contain
    latin1 base64 encoded URNs.

    Parameters
    ----------
    keywords : str
        Location search term (e.g. "Mumbai", "India", "vandavasi").
    cookie : str, optional
        LinkedIn session cookie string.
    csrf_token : str, optional
        CSRF token (JSESSIONID value).

    Returns
    -------
    GeoTypeaheadResponse
        Parsed list of geo location results.
    """
    cookie = cookie or os.environ.get("LI_COOKIE", "")
    csrf_token = csrf_token or os.environ.get("LI_CSRF_TOKEN", "")

    # Anti-bot: random human-like delay
    _anti_bot_sleep()

    # Build variables string matching browser request exactly
    variables_raw = (
        f"(keywords:{keywords},"
        f"query:(typeaheadFilterQuery:(geoSearchTypes:List("
        f"MARKET_AREA,COUNTRY_REGION,ADMIN_DIVISION_1,CITY"
        f"))),"
        f"type:GEO)"
    )
    variables_encoded = variables_raw.replace(" ", "%20")

    url = (
        "https://www.linkedin.com/voyager/api/graphql"
        f"?variables={variables_encoded}"
        "&queryId=voyagerSearchDashReusableTypeahead.4c7caa85341b17b470153ad3d1a29caf"
    )

    session = _create_session(
        cookie=cookie,
        csrf_token=csrf_token,
    )

    # Use curl_cffi with Firefox impersonation — matches real browser JA3 TLS fingerprint
    resp = session.get(
        url,
        timeout=30.0,
    )

    # Handle response — may be gzip compressed (curl_cffi auto-decodes)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Geo search failed: HTTP {resp.status_code} — {resp.text[:200]}"
        )

    try:
        raw = resp.json()
    except ValueError as e:
        raise RuntimeError(f"Invalid JSON response: {e}") from e

    # Parse response — LinkedIn may return under different keys
    data_section = raw.get("data", {}).get("data", {})

    # Try both possible keys
    typeahead = (
        data_section.get("searchDashReusableTypeahead")
        or data_section.get("searchDashReusableTypeaheadByType")
        or {}
    )
    elements = typeahead.get("elements", [])
    paging = typeahead.get("paging", {})
    total_count = paging.get("total", 0)

    locations = []
    for elem in elements:
        # Each element has: title (TextViewModel), trackingUrn, entityUrn, target, type
        title_vm = elem.get("title", {})
        subtitle_vm = elem.get("subtitle", {})
        target = elem.get("target", {})

        # Extract geo URN from target.*geo field
        geo_urn_raw = target.get("*geo", "")
        tracking_urn = elem.get("trackingUrn", "")

        location = GeoResult(
            title=title_vm.get("text", "") if isinstance(title_vm, dict) else str(title_vm or ""),
            subtitle=subtitle_vm.get("text", "") if subtitle_vm else "",
            tracking_urn=tracking_urn,
            entity_urn=elem.get("entityUrn", ""),
            type=elem.get("$type", "").split(".")[-1] if elem.get("$type") else "",
            fsd_geo_urn=geo_urn_raw,
        )
        locations.append(location)

    return GeoTypeaheadResponse(
        locations=locations,
        raw_count=len(locations),  # Actual count from elements
    )


def print_geo_results(results: GeoTypeaheadResponse) -> None:
    """Pretty-print geo location results."""
    print(f"\n📍 Geo locations matching keywords: {results.raw_count} found")
    print(f"{'─' * 110}")
    print(f"{'#':<4} {'Name':<35} {'Geo ID':<12} {'Tracking URN':<25} {'FSD Geo URN'}")
    print("-" * 130)

    for i, loc in enumerate(results.locations, 1):
        print(
            f"{i:<4} {(loc.title or ''):<35} "
            f"{loc.geo_id:<12} "
            f"{(loc.tracking_urn or ''):<25} "
            f"{(loc.fsd_geo_urn or '')}"
        )


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------

# Known LinkedIn geo URN IDs for common Indian cities / regions.
# Add more as needed.  Source: observe the `companyHqGeo` param in
# browser network requests when filtering on LinkedIn.
GEO_URN_MAP: dict[str, str] = {
    "india": "105214829",
    "mumbai": "106164952",
    "delhi": "106166691",
    "bengaluru": "105940533",
    "bangalore": "105940533",
    "chennai": "106888327",
    "hyderabad": "106694358",
    "pune": "106732087",
    "kolkata": "105763473",
    "ahmedabad": "105186582",
    "kochi": "105968639",
    "coimbatore": "106072425",
    "jaipur": "105848183",
    "chandigarh": "106094370",
    "gurugram": "106165353",
    "gurgaon": "106165353",
    "noida": "106693232",
    "thane": "106846986",
    "navi mumbai": "102956297",
    "usa": "103644278",
    "united states": "103644278",
    "new york": "105080838",
    "san francisco bay area": "90000084",
    "london": "101165590",
    "united kingdom": "101165590",
    "singapore": "104738515",
    "dubai": "106481873",
    "uae": "106481873",
}


def _resolve_geo_urn(location: Optional[str]) -> Optional[str]:
    """Return the LinkedIn geo URN for *location*, or ``None`` if unknown.

    Accepts either a human-readable location name (looked up in GEO_URN_MAP)
    or a raw numeric geo URN ID (passed directly through).
    """
    if not location:
        return None
    stripped = location.strip()
    # If it's purely numeric, treat it as a raw geo URN ID
    if stripped.isdigit():
        return stripped
    key = stripped.lower()
    return GEO_URN_MAP.get(key)


def _extract_geo_city(geo_title: str) -> str:
    """Extract the city/region name from a LinkedIn geo title.

    Handles formats like:
        "Chennai, Tamil Nadu, India" → "Chennai"
        "New York, United States" → "New York"
        "New York, New York, United States" → "New York"
        "San Francisco Bay Area" → "San Francisco Bay Area"
        "Greater Chennai Area" → "Greater Chennai Area"
    """
    return geo_title.split(",")[0].strip()


def _extract_location_words(text: str) -> set[str]:
    """Extract meaningful words (≥3 chars) from text.

    Returns a set of lowercase words, each at least 3 characters long.
    """
    words = set()
    for w in text.lower().split():
        w = w.strip(" ,.-")
        if len(w) >= 3:
            words.add(w)
    return words


def matches_geo_filter(
    company,
    geo_filter_words: set[str],
    search_keywords: Optional[str] = None,
) -> bool:
    """Check if a company's location matches the geo filter.

    Uses word-level matching on ``primarySubtitle`` against geo words
    AND optional search keywords (e.g. "real estate agents chennai"
    → "chennai" is a geo word in the keywords).

    Parameters
    ----------
    company : EntityResultViewModel
        The company result to check.
    geo_filter_words : set[str]
        Location words extracted from the geo title (e.g. {"chennai"}).
    search_keywords : str, optional
        Original search query for additional context matching.

    Returns
    -------
    bool
        True if at least one geo word matches the company's subtitle.
    """
    subtitle = company.primary_subtitle.text if company.primary_subtitle and company.primary_subtitle.text else ""
    if not subtitle:
        return False

    subtitle_words = _extract_location_words(subtitle)

    # Check if any geo word appears in the subtitle
    for word in geo_filter_words:
        if word in subtitle_words:
            return True

    # Also do substring match as fallback (handles "chennai" in "CHENNAI, TAMIL NADU")
    subtitle_lower = subtitle.lower()
    for word in geo_filter_words:
        if word in subtitle_lower:
            return True

    return False


def search_companies(
    keywords: str,
    location: Optional[str] = None,
    start: int = 0,
    count: int = 10,
    cookie: Optional[str] = None,
    csrf_token: Optional[str] = None,
) -> SearchResponse:
    """Search LinkedIn companies and return parsed results.

    Parameters
    ----------
    keywords : str
        Search keywords (e.g. ``"Real Estate"``).
    location : str, optional
        Human-readable city / country name.  If it cannot be resolved to a
        known geo URN the location filter is omitted entirely.
    start : int
        Pagination offset.
    count : int
        Number of results to fetch (max 10 per page on this endpoint).
    cookie : str, optional
        Full LinkedIn session cookie string.  Falls back to the ``LI_COOKIE``
        environment variable when not provided.
    csrf_token : str, optional
        CSRF token (``JSESSIONID`` value).  Falls back to the
        ``LI_CSRF_TOKEN`` env variable.

    Returns
    -------
    SearchResponse
        Pydantic-modelled response.
    """
    cookie = cookie or os.environ.get("LI_COOKIE", "")
    csrf_token = csrf_token or os.environ.get("LI_CSRF_TOKEN", "")

    # Build the query parameters list
    query_params_parts = []
    geo_urn = _resolve_geo_urn(location)
    if geo_urn:
        # IMPORTANT: geo URN must be passed WITHOUT quotes (numeric literal)
        query_params_parts.append(f"(key:companyHqGeo,value:List({geo_urn}))")
    # Always include resultType for company search
    query_params_parts.append("(key:resultType,value:List(COMPANIES))")

    # Build queryParameters string
    if query_params_parts:
        params_str = f",queryParameters:List({','.join(query_params_parts)})"
    else:
        params_str = ""

    # Determine origin: FACETED_SEARCH when geo filter is applied, GLOBAL_SEARCH_HEADER otherwise
    origin = "FACETED_SEARCH" if geo_urn else "GLOBAL_SEARCH_HEADER"

    variables_raw = (
        f"(start:{start},origin:{origin},"
        f"query:(keywords:{keywords},flagshipSearchIntent:SEARCH_SRP"
        f"{params_str},includeFiltersInResponse:false))"
    )
    # LinkedIn's Voyager API expects minimal encoding — only encode spaces
    variables_encoded = variables_raw.replace(" ", "%20")

    url = (
        "https://www.linkedin.com/voyager/api/graphql"
        f"?includeWebMetadata=true"
        f"&variables={variables_encoded}"
        "&queryId=voyagerSearchDashClusters.843215f2a3455f1bed85762a45d71be8"
    )

    # Anti-bot: human-like delay before request
    _anti_bot_sleep()

    session = _create_session(
        cookie=cookie,
        csrf_token=csrf_token,
        keywords=keywords,
        geo_urn=geo_urn,
    )
    # Remove Accept-Encoding — curl_cffi handles this automatically
    session.headers.pop("Accept-Encoding", None)

    resp = session.get(url, timeout=30.0)

    if resp.status_code != 200:
        raise RuntimeError(
            f"Company search failed: HTTP {resp.status_code} — {resp.text[:200]}"
        )

    raw = resp.json()

    # Parse the nested structure:
    # - data.data.searchDashClustersByAll → metadata + paging
    # - included[] → actual company entities (EntityResultViewModel)
    payload = raw.get("data", {}).get("data", {}).get("searchDashClustersByAll", {})
    included = raw.get("included", [])

    companies = []
    for item in included:
        item_type = item.get("$type", "")
        if "EntityResultViewModel" in item_type:
            companies.append(EntityResultViewModel.model_validate(item))

    return SearchResponse(
        metadata=SearchMetadata.model_validate(payload.get("metadata", {})),
        paging=PaginationMetadata.model_validate(payload.get("paging", {})),
        companies=companies,
    ), raw


# ---------------------------------------------------------------------------
# Convenience printers
# ---------------------------------------------------------------------------

def print_results(results: SearchResponse) -> None:
    """Pretty-print company results to the console."""
    print(f"\nTotal results: {results.metadata.total_result_count}")
    print(f"Search ID: {results.metadata.search_id}")
    if results.metadata.primary_result_type:
        print(f"Result type: {results.metadata.primary_result_type}")
    if results.metadata.filter_applied_count:
        print(f"Filters applied: {results.metadata.filter_applied_count}")
    print(f"Showing: {results.paging.start + 1}–{results.paging.start + len(results.companies)}\n")

    for i, company in enumerate(results.companies, 1):
        d = company.to_dict()
        print(f"{'─' * 80}")
        print(f"  #{i}")
        print(f"  Name:          {d['name']}")
        print(f"  Company ID:    {d['company_id']}")
        print(f"  Followers:     {d['followers']}")
        print(f"  Location:      {d['location']}")
        print(f"  Description:   {d['description'][:120]}{'...' if len(d['description']) > 120 else ''}")
        print(f"  URL:           {d['url']}")
        print(f"  Logo:          {d['logo_url']}")
        print(f"  Tracking URN:  {d['tracking_urn']}")
        print(f"  Entity URN:    {d['entity_urn']}")
        print(f"  Template:      {d['template']}")
        if d['badge_text']:
            print(f"  Badge:         {d['badge_text']}")
        print(f"  Insights:      {d['actor_insights_count']}")


def print_companies(companies: list[EntityResultViewModel], start: int = 0) -> None:
    """Print a list of companies (used by fetch_all)."""
    print(f"{'#':<4} {'Company':<45} {'Followers':<14} {'Location':<35} {'ID':<12} {'URL'}")
    print("-" * 160)
    for i, c in enumerate(companies, start + 1):
        print(f"{i:<4} {c.name:<45} {c.followers:<14} {c.location:<35} {c.company_id:<12} {c.navigation_url or ''}")


def fetch_all_companies(
    keywords: str,
    location: Optional[str] = None,
    cookie: Optional[str] = None,
    csrf_token: Optional[str] = None,
    delay: float = 5.0,
    max_retries: int = 3,
) -> list[EntityResultViewModel]:
    """Fetch ALL companies across all pages.

    Displays 10 results at a time as it paginates.
    Returns the complete deduplicated list.
    """
    import time

    all_companies: list[EntityResultViewModel] = []
    seen_urls: set[str] = set()
    page = 0
    per_page = 10
    consecutive_failures = 0

    while True:
        fetched = False
        for attempt in range(1, max_retries + 1):
            try:
                result = search_companies(
                    keywords=keywords,
                    location=location,
                    start=page * per_page,
                    count=per_page,
                    cookie=cookie,
                    csrf_token=csrf_token,
                )

                if page == 0:
                    print(f"\nFetching all companies for '{keywords}'")
                    print(f"Total results: {result.metadata.total_result_count}")
                    print()
                    print_companies(result.companies, start=0)

                # Deduplicate by URL
                new_count = 0
                for c in result.companies:
                    url = c.navigation_url or ""
                    if url not in seen_urls:
                        seen_urls.add(url)
                        all_companies.append(c)
                        new_count += 1

                if new_count < len(result.companies):
                    print(f"  ({len(result.companies) - new_count} duplicates skipped)")

                consecutive_failures = 0
                fetched = True
                break

            except Exception as e:
                wait = delay * attempt * 2
                print(f"\n  ⚠ Error on page {page + 1}, attempt {attempt}: {e}")
                print(f"  Retrying in {wait}s...")
                time.sleep(wait)

        if not fetched:
            print(f"\n  ✗ Failed after {max_retries} retries. Stopping.")
            print(f"  Fetched {len(all_companies)} companies before failure.")
            break

        page += 1

        # Save progress periodically
        if page % 20 == 0 and all_companies:
            PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
            tmp_path = str(PROGRESS_DIR / "companies_progress.csv")
            write_companies(all_companies, tmp_path, fmt="csv")
            print(f"\n  [Progress saved: {len(all_companies)} companies → {tmp_path}]")

        # Check termination
        if len(result.companies) < per_page:
            break

        # Safety: LinkedIn caps at ~1000 visible results per search
        if page >= 100:
            print(f"\n  Reached page limit (100 pages). Stopping.")
            break

        print(f"\n{'—' * 60}")
        print(f"Page {page + 1} (fetched {len(all_companies)} unique so far)")
        print_companies(result.companies, start=page * per_page)
        time.sleep(delay)

    print(f"\n{'=' * 60}")
    print(f"Done! Fetched {len(all_companies)} unique companies total across {page} pages.")
    return all_companies


def write_companies(
    companies: list[EntityResultViewModel],
    output_path: Optional[str] = None,
    fmt: str = "csv",
    minimal: bool = False,
) -> str:
    """Write companies to a file with ALL available fields.

    Parameters
    ----------
    companies : list[EntityResultViewModel]
        Company data to write.
    output_path : str, optional
        File path. Defaults to ``output/results/companies.<fmt>``.
    fmt : str
        Output format — ``"csv"`` or ``"json"``.
    minimal : bool
        If True, output only essential fields (name, industry+location, followers, description, logo_url, company_page_url, company_urn).

    Returns
    -------
    str
        The path of the written file.
    """
    if output_path is None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        output_path = str(RESULTS_DIR / f"companies.{fmt}")

    if minimal:
        minimal_headers = [
            "company_name", "industry_location", "followers",
            "description", "logo_url", "company_page_url", "company_urn",
        ]

        if fmt == "csv":
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(minimal_headers)
                for c in companies:
                    d = c.to_minimal_dict()
                    writer.writerow([
                        d["company_name"],
                        d["industry_location"],
                        d["followers"],
                        d["description"],
                        d["logo_url"],
                        d["company_page_url"],
                        d["company_urn"],
                    ])
        elif fmt == "json":
            with open(output_path, "w", encoding="utf-8") as f:
                data = [c.to_minimal_dict() for c in companies]
                json.dump(data, f, indent=2, ensure_ascii=False)
        else:
            raise ValueError(f"Unsupported format: {fmt}. Use 'csv' or 'json'.")
    else:
        # Full fields to export
        csv_headers = [
            "#", "Name", "Company ID", "Description", "Followers", "Location",
            "URL", "Logo URL", "Tracking URN", "Entity URN", "Tracking ID",
            "BSERP Navigational URL", "Actor Navigation URL", "Template",
            "Badge Text", "Badge Icon", "Actor Insights Count", "Primary Actions Count",
            "Add to Search History", "Show Additional Cluster",
        ]

        if fmt == "csv":
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(csv_headers)
                for i, c in enumerate(companies, 1):
                    d = c.to_dict()
                    writer.writerow([
                        i,
                        d["name"],
                        d["company_id"],
                        d["description"],
                        d["followers"],
                        d["location"],
                        d["url"],
                        d["logo_url"],
                        d["tracking_urn"],
                        d["entity_urn"],
                        c.tracking_id or "",
                        c.bserp_entity_navigational_url or "",
                        c.actor_navigation_url or "",
                        c.template or "",
                        c.badge_text or "",
                        c.badge_icon or "",
                        d["actor_insights_count"],
                        d["primary_actions_count"],
                        d["add_entity_to_search_history"],
                        d["show_additional_cluster"],
                    ])
        elif fmt == "json":
            with open(output_path, "w", encoding="utf-8") as f:
                data = []
                for c in companies:
                    d = c.to_dict()
                    data.append({
                        **d,
                        "tracking_id": c.tracking_id,
                        "bserp_entity_navigational_url": c.bserp_entity_navigational_url,
                        "actor_navigation_url": c.actor_navigation_url,
                        "actor_tracking_urn": c.actor_tracking_urn,
                        "template": c.template,
                        "badge_text": c.badge_text,
                        "badge_icon": c.badge_icon,
                        "badge_data": c.badge_data,
                        "ring_status": c.ring_status,
                        "actor_insights_count": d["actor_insights_count"],
                        "insights_resolution_count": len(c.insights_resolution_results) if c.insights_resolution_results else 0,
                        "primary_actions_count": d["primary_actions_count"],
                        "overflow_actions_count": len(c.overflow_actions) if c.overflow_actions else 0,
                        "lazy_loaded_actions": c.lazy_loaded_actions,
                        "add_entity_to_search_history": c.add_entity_to_search_history,
                        "show_additional_cluster": c.show_additional_cluster,
                        "search_action_type": c.search_action_type,
                        "control_name": c.control_name,
                        "entity_custom_tracking_info": c.entity_custom_tracking_info,
                        "entity_embedded_object": c.entity_embedded_object,
                        "interstitial_component": c.interstitial_component,
                        "unread_indicator_details": c.unread_indicator_details,
                    })
                json.dump(data, f, indent=2, ensure_ascii=False)
        else:
            raise ValueError(f"Unsupported format: {fmt}. Use 'csv' or 'json'.")

    print(f"Written {len(companies)} companies to {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Search LinkedIn companies with anti-bot protection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search companies
  python -m module.linkedin_search "Real Estate"

  # With location filter (uses built-in geo URN map)
  python -m module.linkedin_search "Real Estate" -l "Mumbai"

  # Look up geo URN for a location
  python -m module.linkedin_search --geo "vandavasi"

  # Fetch all results
  python -m module.linkedin_search "AI" --all
        """,
    )
    parser.add_argument("keywords", nargs="?", default=None, help="Search keywords, e.g. 'Real Estate'")
    parser.add_argument("-l", "--location", help="City or country name")
    parser.add_argument("-s", "--start", type=int, default=0, help="Pagination offset")
    parser.add_argument("-c", "--count", type=int, default=10, help="Results per page")
    parser.add_argument("--cookie", help="LinkedIn session cookie")
    parser.add_argument("--csrf", help="CSRF token (JSESSIONID value)")
    parser.add_argument("--all", action="store_true", help="Fetch ALL results across all pages")
    parser.add_argument("-o", "--output", help="Output file path (auto-detects csv/json)")
    parser.add_argument("--delay", type=float, default=3.0, help="Delay between pages in seconds")
    parser.add_argument(
        "--geo",
        metavar="LOCATION",
        help="Look up geo URN for a location via LinkedIn's typeahead API",
    )
    parser.add_argument(
        "--minimal",
        action="store_true",
        help="Output only essential fields (company_name, industry_location, followers, description, logo_url, company_page_url, company_urn)",
    )
    args = parser.parse_args()

    # Geo lookup mode
    if args.geo:
        print(f"🔍 Searching geo locations for: '{args.geo}'")
        geo_results = search_geo_locations(
            keywords=args.geo,
            cookie=args.cookie,
            csrf_token=args.csrf,
        )
        print_geo_results(geo_results)
        exit(0)

    if not args.keywords:
        parser.print_help()
        exit(1)

    if args.all:
        companies = fetch_all_companies(
            keywords=args.keywords,
            location=args.location,
            cookie=args.cookie,
            csrf_token=args.csrf,
            delay=args.delay,
        )
        if args.output:
            fmt = args.output.rsplit(".", 1)[-1] if "." in args.output else "csv"
            write_companies(companies, args.output, fmt=fmt)
    else:
        res, _raw = search_companies(
            keywords=args.keywords,
            location=args.location,
            start=args.start,
            count=args.count,
            cookie=args.cookie,
            csrf_token=args.csrf,
        )
        print_results(res)
        if args.output:
            fmt = args.output.rsplit(".", 1)[-1] if "." in args.output else "csv"
            write_companies(res.companies, args.output, fmt=fmt)
