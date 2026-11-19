"""Project-aware payables and receivables.

ERPNext reports these in aggregate; the MVP needs them grouped by project so it is obvious
which project is carrying the cash. Aging is measured from the due date as at ``as_of``.

Read-only: nothing here writes to a standard doctype.
"""

import frappe
from frappe.utils import flt, getdate, today

# Executive joins this set once the role exists (see the permissions patch).
FINANCE_ROLES = {"System Manager", "Accounts Manager", "Accounts User"}

BUCKETS = ("current", "0-30", "31-60", "61-90", "90+")


def _require_finance_roles():
	if not FINANCE_ROLES.intersection(frappe.get_roles()):
		frappe.throw(
			"You do not have permission to view payables and receivables.",
			frappe.PermissionError,
		)


def _aging_bucket(days_overdue: int) -> str:
	if days_overdue <= 0:
		return "current"
	if days_overdue <= 30:
		return "0-30"
	if days_overdue <= 60:
		return "31-60"
	if days_overdue <= 90:
		return "61-90"
	return "90+"


def _outstanding_invoices(company: str, as_of, doctype: str, party_field: str, name_field: str):
	"""Submitted invoices with money outstanding, with the project they belong to.

	The project falls back to the first line that names one, because an invoice entered
	against several projects still has to appear under the one it mostly concerns.
	"""
	child = f"`tab{doctype} Item`"
	return frappe.db.sql(
		f"""
		SELECT
			inv.name AS voucher,
			inv.{party_field} AS party,
			inv.{name_field} AS party_name,
			inv.posting_date,
			inv.due_date,
			inv.outstanding_amount,
			COALESCE(
				NULLIF(inv.project, ''),
				(
					SELECT item.project
					FROM {child} item
					WHERE item.parent = inv.name
						AND COALESCE(item.project, '') != ''
					LIMIT 1
				)
			) AS project
		FROM `tab{doctype}` inv
		WHERE inv.docstatus = 1
			AND inv.company = %(company)s
			AND inv.outstanding_amount > 0
			AND inv.posting_date <= %(as_of)s
		""",
		{"company": company, "as_of": as_of},
		as_dict=True,
	)


def _summarise(company: str, as_of: str, doctype: str, party_field: str, name_field: str) -> dict:
	rows = _outstanding_invoices(company, as_of, doctype, party_field, name_field)
	as_of_date = getdate(as_of)

	project_names = {row.project for row in rows if row.project}
	projects = {}
	if project_names:
		projects = {
			project.name: project.project_name
			for project in frappe.get_all(
				"Project",
				filters={"name": ["in", list(project_names)]},
				fields=["name", "project_name"],
				limit_page_length=0,
			)
		}

	groups = {}
	bucket_totals = dict.fromkeys(BUCKETS, 0.0)
	total = 0.0
	overdue_total = 0.0

	for row in rows:
		due = getdate(row.due_date) if row.due_date else getdate(row.posting_date)
		days_overdue = (as_of_date - due).days
		bucket = _aging_bucket(days_overdue)
		amount = flt(row.outstanding_amount)

		key = (row.project or None, row.party)
		group = groups.get(key)
		if group is None:
			group = {
				"project": row.project,
				"project_name": projects.get(row.project),
				"party": row.party,
				"party_name": row.party_name,
				"outstanding": 0.0,
				"overdue": 0.0,
				"invoices": 0,
				"buckets": dict.fromkeys(BUCKETS, 0.0),
			}
			groups[key] = group

		group["outstanding"] += amount
		group["buckets"][bucket] += amount
		group["invoices"] += 1
		bucket_totals[bucket] += amount
		total += amount

		if days_overdue > 0:
			group["overdue"] += amount
			overdue_total += amount

	return {
		"company": company,
		"currency": frappe.db.get_value("Company", company, "default_currency"),
		"as_of": as_of_date,
		"total_outstanding": total,
		"total_overdue": overdue_total,
		"buckets": bucket_totals,
		"rows": sorted(groups.values(), key=lambda group: (-group["outstanding"], group["project_name"] or "")),
	}


def _resolve_company(company: str | None) -> str:
	if company:
		if not frappe.db.exists("Company", company):
			frappe.throw(f"Company {company} does not exist.", frappe.DoesNotExistError)
		if not frappe.has_permission("Company", "read", company):
			frappe.throw("You do not have permission to view this company.", frappe.PermissionError)
		return company

	default = frappe.defaults.get_user_default("Company") or frappe.get_all(
		"Company", pluck="name", limit=1
	)
	if not default:
		frappe.throw("No company is available.", frappe.DoesNotExistError)
	return default[0] if isinstance(default, list) else default


@frappe.whitelist()
def get_payables(company: str | None = None, as_of: str | None = None) -> dict:
	"""Outstanding supplier invoices by project and supplier, with aging."""
	_require_finance_roles()
	company = _resolve_company(company)
	return _summarise(company, as_of or today(), "Purchase Invoice", "supplier", "supplier_name")


@frappe.whitelist()
def get_receivables(company: str | None = None, as_of: str | None = None) -> dict:
	"""Outstanding customer invoices by project and customer, with aging."""
	_require_finance_roles()
	company = _resolve_company(company)
	return _summarise(company, as_of or today(), "Sales Invoice", "customer", "customer_name")
