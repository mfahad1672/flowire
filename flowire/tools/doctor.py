"""Operational check for a site running the flowire app.

Answers the questions the acceptance checks ask, in one command, without a
browser:

    bench --site <site> execute flowire.tools.doctor.run

Reports:

* which app version is installed
* whether the ``doc_events`` from ``hooks.py`` are actually registered by Frappe
  (a typo in a dotted path is silently ignored at import time, so this is worth
  asserting rather than assuming)
* whether the fixture-owned records are tagged with ``module = Flowire``
* whether the legacy Server Scripts are disabled
* which patches the site has already executed

Read-only.
"""

import frappe

EXPECTED_DOC_EVENTS = {
	"Lead": "flowire.crm.sharing.share_with_owner",
	"Opportunity": "flowire.crm.sharing.share_with_owner",
	"ToDo": "flowire.crm.sharing.share_on_assignment",
	"Notification Settings": "flowire.crm.notification_settings.default_assignment_email_off",
}


def _hooks():
	"""Compare what hooks.py declares against what Frappe resolved."""
	from frappe import get_doc_hooks

	resolved = get_doc_hooks()
	report = {}
	for doctype, handler in EXPECTED_DOC_EVENTS.items():
		events = resolved.get(doctype, {})
		found = any(handler in (handlers or [])
		            for handlers in events.values())
		report[doctype] = "wired" if found else "MISSING"
	return report


def _tagged():
	return {
		"custom_fields": frappe.db.count("Custom Field", {"module": "Flowire"}),
		"property_setters": frappe.db.count("Property Setter", {"module": "Flowire"}),
	}


def _legacy_scripts():
	if not frappe.db.exists("DocType", "Server Script"):
		return {}
	rows = frappe.get_all(
		"Server Script",
		filters={"name": ["like", "CRM %"]},
		fields=["name", "disabled"],
		limit_page_length=0,
	)
	return {row.name: ("disabled" if row.disabled else "STILL ENABLED") for row in rows}


def _patches():
	try:
		rows = frappe.get_all(
			"Patch Log",
			filters={"patch": ["like", "flowire.%"]},
			fields=["patch", "creation"],
			order_by="creation asc",
			limit_page_length=0,
		)
		return [f"{row.patch.split('.')[-1]} @ {row.creation}" for row in rows]
	except Exception as exc:
		return [f"error: {exc}"]


def _business_data():
	return {
		doctype: frappe.db.count(doctype)
		for doctype in ("Company Bidder", "EM Banks")
		if frappe.db.exists("DocType", doctype)
	}


def run() -> dict:
	report = {
		"site": frappe.local.site,
		"flowire": next(
			(meta.get("version") for app, meta in _versions().items() if app == "flowire"), None
		),
		"doc_events": _hooks(),
		"tagged": _tagged(),
		"legacy_server_scripts": _legacy_scripts(),
		"patches_executed": _patches(),
		"business_data": _business_data(),
	}

	print(f"site: {report['site']}  flowire {report['flowire']}")
	print("\ndoc_events (from hooks.py)")
	for doctype, status in report["doc_events"].items():
		print(f"  {doctype:22s} {status}")

	print("\nfixture ownership (module = Flowire)")
	for key, count in report["tagged"].items():
		print(f"  {key:22s} {count}")

	print("\nlegacy Server Scripts")
	for name, status in report["legacy_server_scripts"].items():
		print(f"  {name:38s} {status}")
	if not report["legacy_server_scripts"]:
		print("  (none present)")

	print("\npatches executed")
	for line in report["patches_executed"]:
		print(f"  {line}")

	print("\nbusiness data (must never be exported)")
	for doctype, count in report["business_data"].items():
		print(f"  {doctype:22s} {count}")

	return report


def _versions():
	from frappe.utils.change_log import get_versions

	return get_versions() or {}
