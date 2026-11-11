"""Parity snapshot — the single source of truth for the A8 acceptance checks.

Compares what a site *thinks* its schema and automation are, so that

    fresh site (erpnext + flowire)  ==  restored prod + install-app flowire

can be proven by diffing two JSON files instead of clicking through Desk.

Usage (on a bench, one snapshot per configuration):

    bench --site flowire-dev.localhost execute flowire.tools.parity.snapshot > dev.json
    bench --site fresh.localhost       execute flowire.tools.parity.snapshot > fresh.json
    diff dev.json fresh.json

Parity is a gate, not a suggestion: ``cli()`` exits 1 on any difference, so a shell
chain or CI fails on it instead of a human reading two JSON files.

What is compared is what this app is responsible for: the schema and permissions of
the doctypes we extend, the select options of the five status/stage fields, which app
owns every Custom Field on them, the Property Setters we created, and the
Notifications / Email Templates this app ships. Stock erpnext / hrms automation is
deliberately out of scope — comparing it measures which upstream apps are installed.
"""

import json
import os
import sys

import frappe

# Doctypes whose schema and permissions must match production exactly.
DEFAULT_DOCTYPES = (
	"Lead",
	"Opportunity",
	"Communication",
	"ToDo",
	"Company Bidder",
	"EM Banks",
	"Lead Source",
)

# The status/stage option lists that drive the whole UI. A site whose select options
# drifted renders a status the frontend has no colour or transition for, so these are
# compared by name and in order, not just "the field exists".
STATUS_FIELDS = (
	("Lead", "custom_lead_status"),
	("Opportunity", "custom_opportunity_status"),
	("Opportunity", "custom_stage_1"),
	("Opportunity", "custom_status_pendingreleased"),
	("Opportunity", "custom_pg_status"),
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
	"""Read rows as plain dicts, tolerating doctypes that do not exist on a site.

	Requested keys are intersected with the columns the doctype actually has:
	these tables change shape between Frappe majors, and one absent column would
	otherwise abort the whole SELECT and silently empty the snapshot.
	"""
	if not frappe.db.exists("DocType", doctype):
		return []
	valid = set(frappe.get_meta(doctype).get_valid_columns())
	usable = [key for key in keys if key in valid]
	rows = frappe.get_all(
		doctype,
		filters=filters or {},
		fields=usable,
		order_by=order_by,
		limit_page_length=0,
	)
	return [{key: _plain(row.get(key)) for key in usable} for row in rows]


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


def _custom_fields(doctype):
	"""Every Custom Field on the doctype, and which of them nobody owns.

	``unowned`` is the number the ownership probe fails on, so parity catches drift in
	it too — a field added through Desk on one site only shows up here.
	"""
	rows = _rows(
		"Custom Field",
		("name", "fieldname", "module", "fieldtype", "options"),
		{"dt": doctype},
		"fieldname asc",
	)
	unowned = [row["fieldname"] for row in rows if row.get("module") != "Flowire"]
	return {"total": len(rows), "owned": len(rows) - len(unowned), "unowned": unowned}


def _doctype_snapshot(doctype):
	if not frappe.db.exists("DocType", doctype):
		return {"missing": True}

	return {
		"is_custom": _plain(frappe.db.get_value("DocType", doctype, "custom")),
		"autoname": _plain(frappe.db.get_value("DocType", doctype, "autoname")),
		"fields": _fields(doctype),
		"custom_fields": _custom_fields(doctype),
		"permissions": _permissions(doctype),
		"property_setters": _rows(
			"Property Setter",
			PROPERTY_SETTER_KEYS,
			{"doc_type": doctype},
			"field_name asc, property asc",
		),
	}


def _automation():
	"""Only the automation this app is responsible for.

	Deliberately *not* every Notification and Email Template on the site: those are
	stock erpnext / hrms rows, so comparing them measures which upstream apps happen to
	be installed rather than whether two Flowire sites match. Measured: a fresh
	erpnext+flowire site and a dev site that also has hrms differed by 52 such rows and
	by nothing else. The app's own set is declared in ``flowire.setup.notifications`` —
	the same names that ``sync()`` replays — so this list cannot drift from it.
	"""
	from flowire.setup.notifications import OUR_NOTIFICATIONS, OUR_TEMPLATES

	return {
		# Behaviour must live in doc_events. A Server Script left enabled on one of our
		# doctypes is a real divergence, while the rows themselves cannot ship from an
		# app and are therefore not comparable.
		"enabled_server_scripts": [
			row["name"]
			for row in _rows(
				"Server Script",
				SERVER_SCRIPT_KEYS,
				{"reference_doctype": ("in", list(DEFAULT_DOCTYPES))},
				"name asc",
			)
			if not row.get("disabled")
		],
		"notifications": _rows(
			"Notification", NOTIFICATION_KEYS, {"name": ("in", list(OUR_NOTIFICATIONS))}, "name asc"
		),
		"email_templates": _rows(
			"Email Template", ("name",), {"name": ("in", list(OUR_TEMPLATES))}, "name asc"
		),
	}


def _status_options():
	"""Options for each status/stage field, whether it is customized or stock."""
	options = {}
	for doctype, fieldname in STATUS_FIELDS:
		value = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname}, "options")
		if value is None:
			value = frappe.db.get_value("DocField", {"parent": doctype, "fieldname": fieldname}, "options")
		options[f"{doctype}.{fieldname}"] = value
	return options


def snapshot(doctypes=None) -> dict:
	"""Return the full parity snapshot as a dict of JSON-stable values."""
	doctypes = tuple(doctypes or DEFAULT_DOCTYPES)
	return {
		"doctypes": {doctype: _doctype_snapshot(doctype) for doctype in doctypes},
		"status_options": _status_options(),
		"automation": _automation(),
	}


def snapshot_json(doctypes=None) -> str:
	"""Same snapshot as ``snapshot()``, serialised with sorted keys for diffing."""
	return json.dumps(snapshot(doctypes), indent=2, sort_keys=True, default=str)


def dump(out=None, doctypes=None) -> str:
	"""Write the snapshot to a file and return its path.

	Used by the acceptance checks, which compare three files:

	    bench --site <dev>       execute flowire.tools.parity.dump
	    bench --site <fresh>     execute flowire.tools.parity.dump --kwargs '{"out": "/tmp/fresh.json"}'
	    bench --site <rehearsal> execute flowire.tools.parity.dump --kwargs '{"out": "/tmp/rehearsal.json"}'

	Redirecting ``bench execute`` output instead would work, but the CLI prints the
	return value as a repr, which corrupts the JSON it is supposed to preserve.
	"""
	out = out or frappe.conf.get("flowire_parity_out") or "/tmp/flowire-parity.json"
	os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
	with open(out, "w", encoding="utf-8") as handle:
		handle.write(snapshot_json(doctypes))
	return out


# ─── compare ──────────────────────────────────────────────────────────────────
#
# A snapshot says what one site looks like. Parity is the *diff* between two, and it
# has to be a gate rather than a report: any difference exits 1, so a shell chain or
# CI fails on it instead of relying on a human reading two JSON files.
#
# Nothing is ignored any more: `_automation()` reports only what this app is
# responsible for, so a difference anywhere is a real difference.
IGNORED_PATHS: tuple[str, ...] = ()


def _flatten(value, prefix=""):
	"""Flatten a snapshot into {path: leaf} so a diff can name the exact row."""
	if isinstance(value, dict):
		if not value:
			return {prefix: {}}
		flat = {}
		for key in sorted(value, key=str):
			flat.update(_flatten(value[key], f"{prefix}.{key}" if prefix else str(key)))
		return flat
	if isinstance(value, list):
		if not value:
			return {prefix: []}
		flat = {}
		for index, item in enumerate(value):
			flat.update(_flatten(item, f"{prefix}[{index}]"))
		return flat
	return {prefix: value}


def _ignored(path):
	return any(
		path == ignored or path.startswith(f"{ignored}.") or path.startswith(f"{ignored}[")
		for ignored in IGNORED_PATHS
	)


def compare(left: dict, right: dict) -> list[str]:
	"""Every difference between two snapshots, as human-readable lines."""
	left_flat = _flatten(left)
	right_flat = _flatten(right)
	differences = []

	for path in sorted(set(left_flat) | set(right_flat)):
		if _ignored(path):
			continue
		if path not in left_flat:
			differences.append(f"{path}: only on the right ({right_flat[path]!r})")
		elif path not in right_flat:
			differences.append(f"{path}: only on the left ({left_flat[path]!r})")
		elif left_flat[path] != right_flat[path]:
			differences.append(f"{path}: {left_flat[path]!r} != {right_flat[path]!r}")

	return differences


def compare_files(left_path: str, right_path: str) -> list[str]:
	"""Compare two snapshot files written by :func:`dump`."""
	with open(left_path, encoding="utf-8") as handle:
		left = json.load(handle)
	with open(right_path, encoding="utf-8") as handle:
		right = json.load(handle)
	return compare(left, right)


def cli(left: str, right: str, out: str | None = None) -> str:
	"""Gate entry point: diff two snapshot files, exit 1 on any difference.

	    bench --site <any> execute flowire.tools.parity.cli \
	        --kwargs '{"left": "/tmp/dev.json", "right": "/tmp/fresh.json"}'

	``left`` is the reference (production / dev), ``right`` the candidate site.
	"""
	differences = compare_files(left, right)

	lines = [f"left  {left}", f"right {right}", ""]
	lines.extend(f"  - {difference}" for difference in differences)
	if differences:
		lines.append(f"PARITY FAIL ({len(differences)} difference(s))")
	else:
		lines.append("PARITY PASS — the two sites are identical where it matters")

	report = "\n".join(lines)
	print(report)

	if out:
		os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
		with open(out, "w", encoding="utf-8") as handle:
			handle.write(report + "\n")

	if differences:
		sys.exit(1)
	return report
