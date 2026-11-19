"""Project fields Flowire owns and keeps up to date.

ERPNext already maintains the cost aggregates on Project, and refreshes them when a linked
transaction is submitted **or cancelled**:

    total_costing_amount   labour, from submitted Timesheets
    total_expense_claim    approved Expense Claims
    total_purchase_cost    submitted Purchase Invoices
    total_billed_amount    Sales Invoices
    gross_margin           billed - (labour + purchase + material)

Those stay exactly as they are — read-only, and they already add and subtract. This module
only adds what ERPNext cannot express:

    * the contract value (ERPNext's `estimated_costing` is a manual budget, not the order),
    * planned labour committed by a Resource Allocation, before any timesheet exists, and
    * profit and margin **including expense claims**. `gross_margin` deliberately excludes
      them (see `Project.calculate_gross_margin`), so it is not the same number.

Two fields that merely duplicated native data were retired in the same change, so a project
never carries the same figure twice:

    custom_actual_revenue      == total_billed_amount
    custom_flowire_cost_total  == total_costing_amount + total_purchase_cost
                                  + total_expense_claim

Idempotent: runs from ``after_install`` and ``after_migrate``, like ``schema.sync``.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

MODULE = "Flowire"
DT = "Project"

# Ordered. `insert_after` chains them into one two-column section on the form.
PROJECT_FIELDS = (
	{
		"fieldname": "custom_opportunity",
		"label": "Opportunity",
		"fieldtype": "Link",
		"options": "Opportunity",
		"insert_after": "sales_order",
		# Not a financial figure: set when a project is created from an opportunity, and
		# editable so it can be corrected.
		"read_only": 0,
		"permlevel": 0,
	},
	{
		"fieldname": "custom_costing_section",
		"label": "Project Costing",
		"fieldtype": "Section Break",
		"insert_after": "custom_opportunity",
		"collapsible": 1,
	},
	{
		"fieldname": "custom_contract_value",
		"label": "Contract Value",
		"fieldtype": "Currency",
		"insert_after": "custom_costing_section",
		"description": "Submitted sales orders, else the approved estimate.",
	},
	{
		"fieldname": "custom_planned_hours",
		"label": "Planned Hours",
		"fieldtype": "Float",
		"insert_after": "custom_contract_value",
		"description": "Sum of the planned hours on this project's resource allocations.",
	},
	{
		"fieldname": "custom_costing_col_break",
		"label": "",
		"fieldtype": "Column Break",
		"insert_after": "custom_planned_hours",
	},
	{
		"fieldname": "custom_planned_labor_cost",
		"label": "Planned Labour Cost",
		"fieldtype": "Currency",
		"insert_after": "custom_costing_col_break",
		"description": "Planned hours priced at each employee's effective cost rate.",
	},
	{
		"fieldname": "custom_flowire_profit",
		"label": "Profit (incl. expenses)",
		"fieldtype": "Currency",
		"insert_after": "custom_planned_labor_cost",
		"description": "Revenue minus labour, purchase and expense claims. Differs from "
		"ERPNext's Gross Margin, which ignores expense claims.",
	},
	{
		"fieldname": "custom_flowire_margin_percent",
		"label": "Margin % (incl. expenses)",
		"fieldtype": "Percent",
		"insert_after": "custom_flowire_profit",
		"description": "Profit divided by revenue.",
	},
	{
		"fieldname": "custom_flowire_refreshed_on",
		"label": "Costing Refreshed On",
		"fieldtype": "Datetime",
		"insert_after": "custom_flowire_margin_percent",
		"read_only": 1,
		"permlevel": 0,
	},
)

# Fields that only duplicated native data. Removed on migrate, column included.
RETIRED_FIELDS = ("custom_actual_revenue", "custom_flowire_cost_total")

LAYOUT_TYPES = {"Section Break", "Column Break"}


def sync() -> int:
	"""Create, re-anchor and retire fields so every site converges. Returns created count."""
	if not frappe.db.exists("DocType", DT):
		return 0

	created = 0
	for spec in PROJECT_FIELDS:
		created += _ensure(spec)

	frappe.db.commit()
	# Anchors exist now, so re-anchoring cannot point at a missing field.
	for spec in PROJECT_FIELDS:
		_reanchor(spec)

	retired = _retire()

	frappe.clear_cache(doctype=DT)
	frappe.logger().info(
		f"[flowire] project_fields.sync created {created}, retired {retired} field(s)"
	)
	return created


def _ensure(spec: dict) -> int:
	fieldname = spec["fieldname"]
	existing = frappe.db.get_value("Custom Field", {"dt": DT, "fieldname": fieldname}, "name")
	if existing:
		# A blank module is what the ownership probe fails on; re-stamp it, change nothing else.
		if frappe.db.get_value("Custom Field", existing, "module") != MODULE:
			frappe.db.set_value("Custom Field", existing, "module", MODULE, update_modified=False)
		return 0

	is_layout = spec["fieldtype"] in LAYOUT_TYPES
	payload = {
		"fieldname": fieldname,
		"label": spec.get("label"),
		"fieldtype": spec["fieldtype"],
		"options": spec.get("options"),
		"insert_after": spec["insert_after"],
		"description": spec.get("description"),
		"collapsible": spec.get("collapsible"),
		"read_only": 0 if is_layout else spec.get("read_only", 1),
		"permlevel": 0 if is_layout else spec.get("permlevel", 2),
		"module": MODULE,
	}
	create_custom_field(
		DT,
		{key: value for key, value in payload.items() if value is not None},
		is_system_generated=False,
	)
	return 1


def _reanchor(spec: dict) -> None:
	"""Keep the form layout and wording identical on a site where the fields already existed."""
	name = frappe.db.get_value("Custom Field", {"dt": DT, "fieldname": spec["fieldname"]}, "name")
	if not name:
		return

	wanted = {
		"insert_after": spec["insert_after"],
		"label": spec.get("label"),
		"description": spec.get("description"),
	}
	for field, value in wanted.items():
		if frappe.db.get_value("Custom Field", name, field) != value:
			frappe.db.set_value("Custom Field", name, field, value, update_modified=False)


def _retire() -> int:
	retired = 0
	for fieldname in RETIRED_FIELDS:
		name = frappe.db.get_value("Custom Field", {"dt": DT, "fieldname": fieldname}, "name")
		if not name:
			continue

		frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)
		# Frappe normally drops the column with the field; be explicit so a site that
		# somehow kept it does not end up with an unmapped column.
		if frappe.db.has_column(DT, fieldname):
			frappe.db.sql_ddl(f"ALTER TABLE `tab{DT}` DROP COLUMN `{fieldname}`")
		retired += 1
	return retired
