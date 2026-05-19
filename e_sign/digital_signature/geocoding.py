"""Reverse geocoding for signer location capture.

Converts (lat, lng) coordinates received from the browser's
navigator.geolocation API into a human-readable address that gets
stamped into the PDF signature dictionary and stored in the audit log.

Provider is configurable via DSC Settings:
  - nominatim: free OpenStreetMap service, requires identifying User-Agent
  - google:    Google Maps Geocoding API, requires API key

Results are cached in Frappe's Redis for 24h, keyed by coords rounded to
4 decimal places (~11m), to avoid hammering Nominatim's 1 req/sec limit.
"""

import json

import frappe
import requests

_CACHE_TTL_SECONDS = 24 * 60 * 60
_HTTP_TIMEOUT_SECONDS = 6


def _cache_key(lat, lng):
	return f"e_sign:geocode:{round(float(lat), 4)}:{round(float(lng), 4)}"


def reverse_geocode(lat, lng):
	"""Resolve (lat, lng) to a structured result.

	Returns:
		dict with keys:
			address  — str, human-readable address (or "lat,lng" fallback)
			provider — str, "nominatim" / "google" / "fallback"
			ok       — bool, True if a real address was resolved
			raw      — dict, provider-specific raw response (for audit)
	"""
	if lat is None or lng is None:
		return _fallback(lat, lng, reason="missing-coords")

	try:
		lat_f = float(lat)
		lng_f = float(lng)
	except (TypeError, ValueError):
		return _fallback(lat, lng, reason="bad-coords")

	cached = frappe.cache().get_value(_cache_key(lat_f, lng_f))
	if cached:
		try:
			return json.loads(cached if isinstance(cached, str) else cached.decode("utf-8"))
		except Exception:
			pass

	settings = frappe.get_single("DSC Settings")
	provider = (settings.geocoding_provider or "nominatim").lower()

	try:
		if provider == "google":
			result = _google(settings, lat_f, lng_f)
		else:
			result = _nominatim(settings, lat_f, lng_f)
	except Exception as exc:
		frappe.log_error(
			title="DSC reverse_geocode failed",
			message=f"provider={provider} lat={lat_f} lng={lng_f} err={exc}",
		)
		result = _fallback(lat_f, lng_f, reason=f"{provider}-error")

	if result.get("ok"):
		frappe.cache().set_value(
			_cache_key(lat_f, lng_f),
			json.dumps(result),
			expires_in_sec=_CACHE_TTL_SECONDS,
		)

	return result


def _nominatim(settings, lat, lng):
	user_agent = settings.geocoding_user_agent or "e_sign DSC Signing"
	resp = requests.get(
		"https://nominatim.openstreetmap.org/reverse",
		params={"lat": lat, "lon": lng, "format": "jsonv2", "zoom": 18, "addressdetails": 1},
		headers={"User-Agent": user_agent, "Accept-Language": "en"},
		timeout=_HTTP_TIMEOUT_SECONDS,
	)
	resp.raise_for_status()
	data = resp.json()
	address = data.get("display_name")
	if not address:
		return _fallback(lat, lng, reason="nominatim-empty")
	return {"address": address, "provider": "nominatim", "ok": True, "raw": data}


def _google(settings, lat, lng):
	api_key = settings.get_password("geocoding_api_key", raise_exception=False) if settings.geocoding_api_key else None
	if not api_key:
		return _fallback(lat, lng, reason="google-missing-key")
	resp = requests.get(
		"https://maps.googleapis.com/maps/api/geocode/json",
		params={"latlng": f"{lat},{lng}", "key": api_key},
		timeout=_HTTP_TIMEOUT_SECONDS,
	)
	resp.raise_for_status()
	data = resp.json()
	results = data.get("results") or []
	if not results:
		return _fallback(lat, lng, reason="google-empty")
	return {
		"address": results[0].get("formatted_address") or f"{lat},{lng}",
		"provider": "google",
		"ok": True,
		"raw": {"status": data.get("status"), "first": results[0]},
	}


def _fallback(lat, lng, reason):
	return {
		"address": f"{lat},{lng}" if lat is not None and lng is not None else "",
		"provider": "fallback",
		"ok": False,
		"raw": {"reason": reason},
	}
