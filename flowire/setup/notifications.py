"""Notifications and Email Templates, captured from the reference site.

These are database rows, so they cannot be authored in a repository by hand
without risking a silent divergence from what production actually sends. Instead
the content travels in one direction only:

	capture()  — run once on the REFERENCE site (or its restored copy). Serialises
	             the live Notification / Email Template rows into ``data/*.json``,
	             replacing the frontend URL with a token.

	sync()     — run on every install and migrate. Replays those definitions onto
	             the current site and points System Settings at them.

The token is what keeps this app free of environment detail: the repository holds
``{{FRONTEND_URL}}``, and each site substitutes its own
``flowire_frontend_url`` from ``site_config.json``.

Both directions are defensive — a missing data file, a missing config key or a
doctype that does not exist logs a warning and returns. Nothing here may ever
break ``bench migrate``.
"""

import json
import re
from pathlib import Path

import frappe

DATA_DIR = Path(__file__).parent / "data"
NOTIFICATIONS_FILE = DATA_DIR / "notifications.json"
TEMPLATES_FILE = DATA_DIR / "email_templates.json"

# Substituted at sync time from site_config.flowire_frontend_url.
FRONTEND_URL_TOKEN = "{{FRONTEND_URL}}"

CONFIG_KEY = "flowire_frontend_url"

# The definitions this app owns (§1 #10 and #11 of the separation plan). Named
# explicitly so capture never picks up an unrelated notification a site added.
OUR_NOTIFICATIONS = (
	"CRM Assignment Email",
	"CRM Unassignment Email",
	"CRM Lead Owner Email",
	"CRM Opportunity Owner Email",
)
OUR_TEMPLATES = (
	"CRM Welcome Email",
	"CRM Reset Password",
)

# System Settings fields that must point at the templates above.
SYSTEM_SETTINGS_TEMPLATE_FIELDS = {
	"welcome_email_template": "CRM Welcome Email",
	"reset_password_template": "CRM Reset Password",
}

# Bookkeeping columns that describe *where a row came from*, not what it means.
# Copying these onto another site would forge its audit trail.
SYSTEM_FIELDS = frozenset(
	{
		"name",
		"owner",
		"creation",
		"modified",
		"modified_by",
		"docstatus",
		"idx",
		"parent",
		"parentfield",
		"parenttype",
		"amended_from",
		"_user_tags",
		"_comments",
		"_assign",
		"_liked_by",
	}
)

LAYOUT_FIELDTYPES = frozenset({"Section Break", "Column Break", "Tab Break", "Heading"})

URL_RE = re.compile(r"https?://[^\s\"'<>)]+")


# ─── capture ──────────────────────────────────────────────────────────────────


def _capture_row(doctype: str, name: str, frontend_url: str) -> dict | None:
	"""Serialise one document, dropping bookkeeping fields and abstracting URLs."""
	if not frappe.db.exists(doctype, name):
		return None

	doc = frappe.get_doc(doctype, name)
	meta = frappe.get_meta(doctype)

	data = {}
	for df in meta.fields:
		if df.fieldtype in LAYOUT_FIELDTYPES:
			continue
		value = doc.get(df.fieldname)
		if df.fieldtype == "Table":
			data[df.fieldname] = [
				{key: row for key, row in child.as_dict().items() if key not in SYSTEM_FIELDS}
				for child in (value or [])
			]
			continue
		if df.fieldname == "name":
			continue
		data[df.fieldname] = value

	data.pop("name", None)
	return _abstract_urls(data, frontend_url)


def _abstract_urls(value, frontend_url: str):
	"""Replace this site's frontend URL with the token, recursively."""
	if isinstance(value, str):
		if frontend_url and frontend_url in value:
			value = value.replace(frontend_url, FRONTEND_URL_TOKEN)
		# A bare URL that is not this site's frontend (e.g. a hard-coded
		# netlogg.ai link) is left alone — rewriting it would be a guess.
		return value
	if isinstance(value, list):
		return [_abstract_urls(item, frontend_url) for item in value]
	if isinstance(value, dict):
		return {key: _abstract_urls(item, frontend_url) for key, item in value.items()}
	return value


def capture(doctype_names: dict | None = None) -> dict:
	"""Dump our Notifications and Email Templates into ``data/*.json``.

	Run on the reference site (production or its restored copy) only:

	    bench --site <reference> execute flowire.setup.notifications.capture
	"""
	doctype_names = doctype_names or {
		"Notification": OUR_NOTIFICATIONS,
		"Email Template": OUR_TEMPLATES,
	}

	frontend_url = frappe.conf.get(CONFIG_KEY) or ""
	if not frontend_url:
		frappe.logger().warning(
			f"[flowire] {CONFIG_KEY} is not set; captured notifications keep their literal URLs"
		)

	DATA_DIR.mkdir(parents=True, exist_ok=True)
	written = {}

	for doctype, names in doctype_names.items():
		rows = {}
		for name in names:
			row = _capture_row(doctype, name, frontend_url)
			if row is None:
				continue
			rows[name] = row

		path = NOTIFICATIONS_FILE if doctype == "Notification" else TEMPLATES_FILE
		path.write_text(json.dumps(rows, indent=2, sort_keys=True, default=str), encoding="utf-8")
		written[path.name] = len(rows)

	frappe.logger().info(f"[flowire] captured {written} from {frappe.local.site}")
	return written


# ─── sync ─────────────────────────────────────────────────────────────────────


def _load(path: Path) -> dict:
	if not path.exists():
		frappe.logger().warning(f"[flowire] {path.name} missing — nothing to sync")
		return {}
	try:
		return json.loads(path.read_text(encoding="utf-8"))
	except (OSError, ValueError) as exc:
		frappe.logger().warning(f"[flowire] cannot read {path.name}: {exc}")
		return {}


def _apply_urls(value, frontend_url: str):
	"""Reverse of ``_abstract_urls`` — put this site's URL back in."""
	if isinstance(value, str):
		return value.replace(FRONTEND_URL_TOKEN, frontend_url)
	if isinstance(value, list):
		return [_apply_urls(item, frontend_url) for item in value]
	if isinstance(value, dict):
		return {key: _apply_urls(item, frontend_url) for key, item in value.items()}
	return value


def _upsert(doctype: str, name: str, data: dict) -> str:
	"""Create or update one document; returns 'created' | 'updated' | 'skipped'."""
	if not frappe.db.exists("DocType", doctype):
		frappe.logger().warning(f"[flowire] doctype {doctype} not installed — skipping {name}")
		return "skipped"

	payload = dict(data)
	# Child tables must be re-keyed as full dicts with doctype set, which they
	# already carry from as_dict().
	try:
		if frappe.db.exists(doctype, name):
			doc = frappe.get_doc(doctype, name)
			doc.update(payload)
			doc.save(ignore_permissions=True)
			return "updated"

		doc = frappe.get_doc({"doctype": doctype, "name": name, **payload})
		doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
		return "created"
	except Exception as exc:  # never break migrate over a notification
		frappe.logger().error(f"[flowire] could not sync {doctype} '{name}': {exc}")
		return "skipped"


def sync() -> dict:
	"""Replay the captured definitions onto the current site."""
	frontend_url = frappe.conf.get(CONFIG_KEY) or ""
	if not frontend_url:
		frappe.logger().warning(
			f"[flowire] {CONFIG_KEY} is not set — leaving notifications untouched. "
			"Set it with: bench --site <site> set-config " + CONFIG_KEY + " <url>"
		)
		return {"skipped": "no frontend url"}

	notifications = _load(NOTIFICATIONS_FILE)
	templates = _load(TEMPLATES_FILE)

	if not notifications and not templates:
		return {"skipped": "no captured data"}

	results = {}
	for name, data in notifications.items():
		results[f"Notification:{name}"] = _upsert(
			"Notification", name, _apply_urls(data, frontend_url)
		)
	for name, data in templates.items():
		results[f"Email Template:{name}"] = _upsert(
			"Email Template", name, _apply_urls(data, frontend_url)
		)

	results.update(_link_templates())
	frappe.db.commit()
	frappe.logger().info(f"[flowire] notification sync: {results}")
	return results


def _link_templates() -> dict:
	"""Point System Settings at our two templates."""
	if not frappe.db.exists("DocType", "System Settings"):
		return {}

	settings = frappe.get_single("System Settings")
	changed = {}
	for fieldname, template in SYSTEM_SETTINGS_TEMPLATE_FIELDS.items():
		if not frappe.db.exists("Email Template", template):
			continue
		if settings.get(fieldname) == template:
			continue
		settings.set(fieldname, template)
		changed[fieldname] = template

	if changed:
		settings.save(ignore_permissions=True)
	return changed


def verify() -> dict:
	"""Report whether the live rows still match the captured definitions.

	Used by the A6 acceptance check; never mutates anything.
	"""
	frontend_url = frappe.conf.get(CONFIG_KEY) or ""
	report = {"frontend_url": bool(frontend_url), "notifications": {}, "templates": {}}

	for name, expected in _load(NOTIFICATIONS_FILE).items():
		if not frappe.db.exists("Notification", name):
			report["notifications"][name] = "missing"
			continue
		live = _capture_row("Notification", name, frontend_url)
		report["notifications"][name] = "match" if live == expected else "differs"

	for name, expected in _load(TEMPLATES_FILE).items():
		if not frappe.db.exists("Email Template", name):
			report["templates"][name] = "missing"
			continue
		live = _capture_row("Email Template", name, frontend_url)
		report["templates"][name] = "match" if live == expected else "differs"

	return report
