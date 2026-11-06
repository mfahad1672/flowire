"""Read-only inventory of a reference site — the input for A2 and A4.

This exists because the audit has to run where the data lives. It works over the
REST API *or* directly on the box, and always produces the same JSON, so the
inventory, the fixtures and the DocType definitions are all derived from one dump
instead of three separate reads.

WHY JSON AND NOT A TEXT REPORT
------------------------------
``scripts/multitenancy_audit.py`` prints human-readable tables, which is right for
a person reading a terminal but loses the exact field order, option lists and
notification bodies that the fixture export needs. This emits the raw values.

HOW TO RUN — pick one
---------------------
On the site's own bench (recommended; no credentials involved)::

    bench --site <site> execute flowire.tools.audit_reference.run

That requires ``flowire`` to be installed. To audit a site that does not have the
app yet (the normal case — you audit *before* installing)::

    bench --site <site> console
    >>> exec(open("/path/to/flowire/tools/audit_reference.py").read())

Either way the dump is written to ``/tmp/flowire-audit.json`` (override with
``--out`` / the ``flowire_audit_out`` config key) and the path is returned.

READ-ONLY
---------
Every query is a SELECT. Nothing is created, updated, migrated or repaired. Each
section is individually guarded, so a missing doctype on an older site narrows the
report instead of aborting it.
"""

import json
import os

import frappe

DEFAULT_OUT = "/tmp/flowire-audit.json"
CONFIG_OUT_KEY = "flowire_audit_out"

# Every field the app needs to reproduce a Custom Field byte-for-byte.
CUSTOM_FIELD_FIELDS = (
	"name", "dt", "fieldname", "label", "fieldtype", "options", "insert_after",
	"reqd", "hidden", "read_only", "permlevel", "module", "is_system_generated",
	"default", "depends_on", "mandatory_depends_on", "read_only_depends_on",
	"description", "in_list_view", "in_standard_filter", "in_global_search",
	"in_preview", "no_copy", "allow_on_submit", "ignore_xss_filter", "unique",
	"search_index", "precision", "length", "translatable", "collapsible",
	"fetch_from", "fetch_if_empty", "set_only_once", "print_hide",
	"print_hide_if_no_value", "allow_in_quick_entry", "bold", "report_hide",
	"non_negative", "hide_border", "show_days", "show_seconds", "max_height",
	"align", "columns", "button_color", "allow_bulk_edit", "creation", "owner",
)

PROPERTY_SETTER_FIELDS = (
	"name", "doc_type", "field_name", "property", "value", "property_type",
	"module", "is_system_generated", "creation", "owner",
)

CUSTOM_DOCPERM_FIELDS = (
	"name", "parent", "role", "permlevel", "read", "write", "create", "delete",
	"submit", "cancel", "amend", "report", "export", "import", "share", "print",
	"email", "if_owner", "select", "creation", "owner",
)

SERVER_SCRIPT_FIELDS = (
	"name", "script_type", "reference_doctype", "doctype_event", "disabled",
	"script", "creation", "owner", "module", "enabled",
)

NOTIFICATION_FIELDS = (
	"name", "document_type", "event", "enabled", "channel", "subject",
	"condition", "message", "message_type", "send_system_notification",
	"attach_print", "print_format", "creation", "owner", "module",
)

EMAIL_TEMPLATE_FIELDS = ("name", "subject", "response", "response_html", "use_html", "creation", "owner")

# Doctypes whose records are business data — counted, never exported.
BUSINESS_DOCTYPES = ("Company Bidder", "EM Banks")


def _all(doctype, fields, filters=None):
	"""Read every row, tolerating a doctype that is not installed.

	The requested field list is intersected with the columns the doctype actually
	has: these doctypes gain and lose columns between Frappe majors (v16 dropped
	``Custom Field.show_days`` and renamed Server Script's ``enabled`` to
	``disabled``), and asking for a column that is not there aborts the whole
	SELECT rather than skipping it.
	"""
	if not frappe.db.exists("DocType", doctype):
		return {"__missing__": True}
	try:
		valid = set(frappe.get_meta(doctype).get_valid_columns())
		usable = [field for field in fields if field in valid]
		rows = frappe.get_all(
			doctype, filters=filters or {}, fields=usable,
			order_by="name asc", limit_page_length=0,
		)
		return [_plain(row) for row in rows]
	except Exception as exc:
		return {"__error__": str(exc)}


def _plain(row):
	return {key: (value if value is None or isinstance(value, (bool, int, float, str)) else str(value))
	        for key, value in dict(row).items()}


def _safe(fn, label):
	"""Run a section; a failure narrows the report instead of aborting it."""
	try:
		return fn()
	except Exception as exc:
		frappe.logger().warning(f"[flowire] audit section {label} failed: {exc}")
		return {"__error__": f"{label}: {exc}"}


def _versions():
	out = {}
	try:
		from frappe.utils.change_log import get_versions
		out = {app: {"version": meta.get("version"), "branch": meta.get("branch_version")}
		       for app, meta in (get_versions() or {}).items()}
	except Exception as exc:
		out = {"__error__": str(exc)}
	out["__installed__"] = frappe.get_installed_apps()
	return out


def _doctype_definition(doctype):
	"""Full definition of one DocType, for A4 (custom -> real)."""
	if not frappe.db.exists("DocType", doctype):
		return {"__missing__": True}
	doc = frappe.get_doc("DocType", doctype).as_dict()
	for key in ("_user_tags", "_comments", "_assign", "_liked_by"):
		doc.pop(key, None)
	doc["__record_count__"] = frappe.db.count(doctype)
	return doc


def _business_counts():
	counts = {}
	for doctype in BUSINESS_DOCTYPES:
		if frappe.db.exists("DocType", doctype):
			counts[doctype] = frappe.db.count(doctype)
		else:
			counts[doctype] = None
	return counts


def _system_settings():
	if not frappe.db.exists("DocType", "System Settings"):
		return {}
	try:
		settings = frappe.get_single("System Settings")
		return {
			"welcome_email_template": settings.get("welcome_email_template"),
			"reset_password_template": settings.get("reset_password_template"),
		}
	except Exception as exc:
		return {"__error__": str(exc)}


def _role_profile_rows():
	roles = _all("Role", ("name", "disabled", "desk_access"))
	if isinstance(roles, dict):
		return roles
	return [row for row in roles if row.get("name") not in _STANDARD_ROLES_HINT]


_STANDARD_ROLES_HINT = {
	"Administrator", "Guest", "All", "Desk User", "System Manager", "Report Manager",
	"Script Manager", "Translator", "Website Manager", "Newsletter Manager",
	"Sales Master Manager", "Sales Manager", "Sales User", "Purchase Master Manager",
	"Purchase Manager", "Purchase User", "Accounts Manager", "Accounts User",
	"Stock Manager", "Stock User", "Item Manager", "Manufacturing Manager",
	"Manufacturing User", "Quality Manager", "Quality User", "Support Team",
	"Projects Manager", "Projects User", "HR Manager", "HR User", "Employee",
	"Auditor", "Analytics", "Maintenance Manager", "Maintenance User",
	"Instructor", "Student", "Education Manager", "LMS",
}


def run(out=None):
	"""Collect everything and write it as JSON. Returns the output path."""
	out = out or frappe.conf.get(CONFIG_OUT_KEY) or DEFAULT_OUT

	dump = {
		"generated_at": frappe.utils.now(),
		"site": frappe.local.site,
		"versions": _safe(_versions, "versions"),
		"custom_fields": _safe(
			lambda: _all("Custom Field", CUSTOM_FIELD_FIELDS), "custom_fields"),
		"property_setters": _safe(
			lambda: _all("Property Setter", PROPERTY_SETTER_FIELDS), "property_setters"),
		"custom_docperms": _safe(
			lambda: _all("Custom DocPerm", CUSTOM_DOCPERM_FIELDS), "custom_docperms"),
		"server_scripts": _safe(
			lambda: _all("Server Script", SERVER_SCRIPT_FIELDS), "server_scripts"),
		"notifications": _safe(
			lambda: _all("Notification", NOTIFICATION_FIELDS), "notifications"),
		"email_templates": _safe(
			lambda: _all("Email Template", EMAIL_TEMPLATE_FIELDS), "email_templates"),
		"client_scripts": _safe(
			lambda: _all("Client Script", ("name", "dt", "view", "enabled", "script")), "client_scripts"),
		"workflows": _safe(
			lambda: _all("Workflow", ("name", "document_type", "is_active")), "workflows"),
		"reports": _safe(
			lambda: _all("Report", ("name", "report_type", "ref_doctype", "is_standard", "module")),
			"reports"),
		"print_formats": _safe(
			lambda: _all("Print Format", ("name", "doc_type", "standard", "module")), "print_formats"),
		"custom_roles": _safe(_role_profile_rows, "custom_roles"),
		"role_profiles": _safe(lambda: _all("Role Profile", ("name",)), "role_profiles"),
		"system_settings": _safe(_system_settings, "system_settings"),
		"business_counts": _safe(_business_counts, "business_counts"),
		"doctype_definitions": {
			doctype: _safe(lambda d=doctype: _doctype_definition(d), f"doctype:{doctype}")
			for doctype in BUSINESS_DOCTYPES
		},
	}

	payload = json.dumps(dump, indent=2, sort_keys=True, default=str)
	os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
	with open(out, "w", encoding="utf-8") as handle:
		handle.write(payload)

	return out


def summary(out=None):
	"""Run the audit and print a one-line-per-section summary plus the dump path."""
	path = run(out)

	with open(path, encoding="utf-8") as handle:
		dump = json.load(handle)

	lines = [f"site: {dump['site']}", f"dump: {path}"]
	for key, value in dump.items():
		if key in ("generated_at", "site", "doctype_definitions"):
			continue
		if isinstance(value, list):
			lines.append(f"  {key:22s} {len(value)}")
		elif isinstance(value, dict) and "__error__" in value:
			lines.append(f"  {key:22s} ERROR {value['__error__']}")
		elif isinstance(value, dict):
			lines.append(f"  {key:22s} {value}")

	print("\n".join(lines))
	return path


if __name__ == "__main__":
	summary()
