"""Fields the app must create in code rather than ship as a fixture.

Four CRM columns are **app-owned but version-dependent**, which is why they are the
one thing here that fixtures cannot express:

    Lead.source             Lead.campaign_name
    Opportunity.source       Opportunity.campaign

ERPNext v15 ships all four natively. ERPNext **v16 dropped them** (measured on
erpnext 16.54: no ``DocField`` of those names on either doctype), so on v16 they can
only exist as Custom Fields — and a site installed from fixtures alone would have no
Source or Campaign field at all, while ``Lead.source`` stays a Link field the
frontend reads and writes.

Shipping them as ``Custom Field`` fixtures would fix v16 and *break* v15: Frappe
would try to create a second column with a name the doctype already owns. So the
fixture filter in ``hooks.py`` deliberately excludes these four, and this module
creates them instead, guarded by what the doctype actually has:

    already a Custom Field  -> keep it, only re-stamp module=Flowire if it is blank
    a stock DocField        -> leave it alone (ERPNext still ships the field)
    a bare table column     -> leave it alone (never touch an orphan column)
    none of the above       -> create it, owned by Flowire

Runs from ``after_install`` and ``after_migrate``, so a fresh site gets them and an
existing one converges. Idempotent; missing doctypes are skipped so the app can be
installed before erpnext finishes; nothing here may break a migration.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

MODULE = "Flowire"

# Mirrors the reference site exactly (measured): labels, types, options and the
# position each field had on the form. `insert_after` is what keeps the form in the
# same order on every site.
OUR_VERSION_FIELDS = (
	{
		"dt": "Lead",
		"fieldname": "source",
		"label": "Source",
		"fieldtype": "Link",
		"options": "Lead Source",
		"insert_after": "status",
	},
	{
		"dt": "Lead",
		"fieldname": "campaign_name",
		"label": "Campaign",
		"fieldtype": "Link",
		"options": "Campaign",
		"insert_after": "source",
	},
	{
		"dt": "Opportunity",
		"fieldname": "source",
		"label": "Source",
		"fieldtype": "Link",
		"options": "Lead Source",
		"insert_after": "status",
	},
	{
		"dt": "Opportunity",
		"fieldname": "campaign",
		"label": "Campaign",
		"fieldtype": "Link",
		"options": "Campaign",
		"insert_after": "source",
	},
)


def sync() -> int:
	"""Create/adopt the version-dependent fields. Returns how many were created."""
	created = 0
	for spec in OUR_VERSION_FIELDS:
		created += _ensure(spec)
	if created:
		frappe.clear_cache()
	frappe.logger().info(f"[flowire] schema.sync created {created} version-dependent field(s)")
	return created


def _ensure(spec: dict) -> int:
	"""Create one field if the doctype does not already have it. 1 when created."""
	dt = spec["dt"]
	fieldname = spec["fieldname"]

	if not frappe.db.exists("DocType", dt):
		return 0

	existing = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fieldname}, "name")
	if existing:
		# Already ours in substance — a blank module is what the ownership probe fails on.
		if frappe.db.get_value("Custom Field", existing, "module") != MODULE:
			frappe.db.set_value("Custom Field", existing, "module", MODULE, update_modified=False)
		return 0

	# ERPNext still ships the field natively (v15): the app must not add a second column.
	if frappe.db.exists("DocField", {"parent": dt, "fieldname": fieldname}):
		return 0

	# A column with no DocField/Custom Field behind it: an orphan, not ours to map.
	if frappe.db.has_column(dt, fieldname):
		frappe.logger().warning(
			f"[flowire] {dt}.{fieldname} is a table column with no field definition; left untouched"
		)
		return 0

	create_custom_field(dt, {k: v for k, v in spec.items() if k != "dt"} | {"module": MODULE}, is_system_generated=False)
	return 1
