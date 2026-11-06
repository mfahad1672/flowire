"""Parity snapshot — the single source of truth for the A8 acceptance checks.

Compares what a site *thinks* its schema and automation are, so that

    fresh site (erpnext + flowire)  ==  restored prod + install-app flowire

can be proven by diffing two JSON files instead of clicking through Desk.

Usage (on a bench, one snapshot per configuration):

    bench --site flowire-dev.localhost execute flowire.tools.parity.snapshot > dev.json
    bench --site fresh.localhost       execute flowire.tools.parity.snapshot > fresh.json
    diff dev.json fresh.json

Server Scripts are expected to differ on a fresh site (they do not exist there);
everything else must be identical.
"""

import json

import frappe

# Doctypes whose schema and permissions must match production exactly.
DEFAULT_DOCTYPES = (
	"Lead",
	"Opportunity",
	"Communication",
	"ToDo",
	"Company Bidder",
	"EM Banks",
)

# Field attributes that determine form layout and data integrity.
# Deliberately excludes description/label: copy tweaks are not parity breakages.
FIELD_KEYS = (
	"fieldname",
	"fieldtype",
	"options",
	"insert_after",
	"reqd",
	"hidden",
	"read_only",
	"permlevel",
)

PERM_KEYS = (
	"role",
	"permlevel",
	"read",
	"write",
	"create",
	"delete",
	"submit",
	"cancel",
	"amend",
	"report",
	"export",
	"share",
	"print",
	"email",
	"if_owner",
)

PROPERTY_SETTER_KEYS = (
	"doc_type",
	"field_name",
	"property",
	"value",
	"property_type",
	"module",
	"is_system_generated",
)

SERVER_SCRIPT_KEYS = (
	"name",
	"script_type",
	"reference_doctype",
	"doctype_event",
	"disabled",
)

NOTIFICATION_KEYS = (
	"name",
	"document_type",
	"event",
	"enabled",
	"channel",
)


def _plain(value):
	"""Coerce a Frappe value into something json-stable and diff-friendly."""
	if value is None or isinstance(value, (bool, int, float, str)):
		return value
	return str(value)


def _rows(doctype, keys, filters=None, order_by="name asc"):
	"""Read rows as plain dicts, tolerating doctypes that do not exist on a site."""
	if not frappe.db.exists("DocType", doctype):
		return []
	rows = frappe.get_all(
		doctype,
		filters=filters or {},
		fields=list(keys),
		order_by=order_by,
		limit_page_length=0,
	)
	return [{key: _plain(row.get(key)) for key in keys} for row in rows]


def _fields(doctype):
	meta = frappe.get_meta(doctype)
	rows = [{key: _plain(df.get(key)) for key in FIELD_KEYS} for df in meta.fields]
	rows.sort(key=lambda row: row["fieldname"] or "")
	return rows


def _permissions(doctype):
	"""Standard DocPerm rows, Custom DocPerm rows and the resolved permissions.

	Both raw tables are kept: Frappe ignores DocPerm entirely once a doctype has a
	single Custom DocPerm row, so a diff on the resolved set alone hides a
	half-exported permission matrix.
	"""
	return {
		"docperm": _rows("DocPerm", PERM_KEYS, {"parent": doctype}, "role asc, permlevel asc"),
		"custom_docperm": _rows(
			"Custom DocPerm", PERM_KEYS, {"parent": doctype}, "role asc, permlevel asc"
		),
		"effective": [
			{key: _plain(perm.get(key)) for key in PERM_KEYS}
			for perm in sorted(
				frappe.get_meta(doctype).get_permissions(),
				key=lambda perm: (str(perm.get("role")), perm.get("permlevel") or 0),
			)
		],
	}


def _doctype_snapshot(doctype):
	if not frappe.db.exists("DocType", doctype):
		return {"missing": True}

	return {
		"is_custom": _plain(frappe.db.get_value("DocType", doctype, "custom")),
		"autoname": _plain(frappe.db.get_value("DocType", doctype, "autoname")),
		"fields": _fields(doctype),
		"permissions": _permissions(doctype),
		"property_setters": _rows(
			"Property Setter",
			PROPERTY_SETTER_KEYS,
			{"doc_type": doctype},
			"field_name asc, property asc",
		),
	}


def _automation():
	"""Everything that behaves at runtime rather than describing a schema."""
	return {
		"server_scripts": _rows("Server Script", SERVER_SCRIPT_KEYS),
		"notifications": _rows("Notification", NOTIFICATION_KEYS),
		"email_templates": _rows("Email Template", ("name",)),
	}


def snapshot(doctypes=None) -> dict:
	"""Return the full parity snapshot as a dict of JSON-stable values."""
	doctypes = tuple(doctypes or DEFAULT_DOCTYPES)
	return {
		"doctypes": {doctype: _doctype_snapshot(doctype) for doctype in doctypes},
		"automation": _automation(),
	}


def snapshot_json(doctypes=None) -> str:
	"""Same snapshot as ``snapshot()``, serialised with sorted keys for diffing."""
	return json.dumps(snapshot(doctypes), indent=2, sort_keys=True, default=str)
