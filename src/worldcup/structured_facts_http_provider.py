import json
import urllib.error
import urllib.parse
import urllib.request

from .provider_contracts import (
    STRUCTURED_FACTS_API_BASE_URL_ENV,
    STRUCTURED_FACTS_PROVIDER_TOKEN_ENV,
    StructuredFactsPayloadError,
    env_value,
    validate_structured_facts_payload,
)
from .structured_facts_store import ingest_structured_facts_payload


DEFAULT_TIMEOUT_SECONDS = 20


class StructuredFactsHttpProviderError(ValueError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def safe_endpoint_label(url):
    parsed = urllib.parse.urlparse(url or "")
    if not parsed.scheme or not parsed.netloc:
        return "invalid-url"
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def append_query_params(url, params):
    params = {key: value for key, value in (params or {}).items() if value not in (None, "")}
    if not params:
        return url
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.extend((key, str(value)) for key, value in params.items())
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def fetch_structured_facts_payload(
    base_url=None,
    token=None,
    match_id=None,
    snapshot_time=None,
    timeout=DEFAULT_TIMEOUT_SECONDS,
    opener=None,
    environ=None,
):
    base_url = base_url or env_value(STRUCTURED_FACTS_API_BASE_URL_ENV, environ=environ)
    token = token if token is not None else env_value(STRUCTURED_FACTS_PROVIDER_TOKEN_ENV, environ=environ)
    if not base_url:
        raise StructuredFactsHttpProviderError(
            "STRUCTURED_FACTS_PROVIDER_URL_MISSING",
            "Structured facts provider URL is required.",
        )
    if not token:
        raise StructuredFactsHttpProviderError(
            "STRUCTURED_FACTS_PROVIDER_TOKEN_MISSING",
            "Structured facts provider token is required.",
            details={"endpoint": safe_endpoint_label(base_url)},
        )

    request_url = append_query_params(base_url, {
        "matchId": match_id,
        "snapshotTime": snapshot_time,
    })
    request = urllib.request.Request(
        request_url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "MatchOracle-StructuredFactsFetcher/1.0",
        },
        method="GET",
    )
    opener = opener or urllib.request.urlopen
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as failure:
        raise StructuredFactsHttpProviderError(
            "STRUCTURED_FACTS_PROVIDER_HTTP_ERROR",
            "Structured facts provider returned an HTTP error.",
            details={"status": failure.code, "endpoint": safe_endpoint_label(base_url)},
        ) from failure
    except urllib.error.URLError as failure:
        raise StructuredFactsHttpProviderError(
            "STRUCTURED_FACTS_PROVIDER_REQUEST_FAILED",
            "Structured facts provider request failed.",
            details={"endpoint": safe_endpoint_label(base_url), "reason": str(failure.reason)},
        ) from failure

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as failure:
        raise StructuredFactsHttpProviderError(
            "STRUCTURED_FACTS_PROVIDER_JSON_INVALID",
            "Structured facts provider response must be valid JSON.",
            details={"endpoint": safe_endpoint_label(base_url), "line": failure.lineno, "column": failure.colno},
        ) from failure

    validate_structured_facts_payload(payload)
    return payload


def fetch_validate_and_optionally_ingest_structured_facts(
    base_url=None,
    token=None,
    match_id=None,
    snapshot_time=None,
    timeout=DEFAULT_TIMEOUT_SECONDS,
    store_path=None,
    created_by="structured_facts_http_provider",
    dry_run=False,
    opener=None,
    environ=None,
):
    payload = fetch_structured_facts_payload(
        base_url=base_url,
        token=token,
        match_id=match_id,
        snapshot_time=snapshot_time,
        timeout=timeout,
        opener=opener,
        environ=environ,
    )
    validation = validate_structured_facts_payload(payload)
    result = {
        "status": "VALIDATED" if dry_run else "INGESTED",
        "source": payload.get("source"),
        "snapshotTime": payload.get("snapshotTime") or payload.get("snapshot_time"),
        "validation": validation,
        "factKeys": sorted((payload.get("facts") or {}).keys()),
    }
    if dry_run:
        return result
    ingestion = ingest_structured_facts_payload(payload, path=store_path, created_by=created_by)
    result["ingestion"] = ingestion
    return result
