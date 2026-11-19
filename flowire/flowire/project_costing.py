"""Server-side project costing and resource summaries.

Actual transactions remain in ERPNext/HRMS. This module reads submitted source
records and never writes derived financial totals back to standard doctypes.
"""

import re
from datetime import timedelta

import frappe
from frappe.utils import flt, getdate, now_datetime, today

PROJECT_COSTING_ROLES = {
	"System Manager",
	"Accounts Manager",
	"Projects Manager",
	"HR Manager",
}
EMPLOYEE_COSTING_ROLES = {"System Manager", "Accounts Manager", "HR Manager"}
HOURS_PER_WORKING_DAY = 8
HALF_DAY_HOURS = HOURS_PER_WORKING_DAY / 2
WEEKDAYS = {
	"Monday": 0,
	"Tuesday": 1,
	"Wednesday": 2,
	"Thursday": 3,
	"Friday": 4,
	"Saturday": 5,
	"Sunday": 6,
}


def _require_roles(allowed_roles: set[str]):
	if not allowed_roles.intersection(frappe.get_roles()):
		frappe.throw("You do not have permission to view project costing data.", frappe.PermissionError)


def _require_hrms():
	missing = [
		doctype
		for doctype in ("Employee", "Timesheet", "Timesheet Detail", "Holiday List")
		if not frappe.db.exists("DocType", doctype)
	]
	if missing:
		frappe.throw(
			"Project costing resource features require the compatible HRMS app. "
			f"Missing DocType(s): {', '.join(missing)}."
		)


def _sum_sql(query: str, values) -> float:
	rows = frappe.db.sql(query, values, as_list=True)
	return flt(rows[0][0]) if rows and rows[0][0] is not None else 0


def _project_contract_value(project: str, sales_order: str | None) -> float:
	return _sum_sql(
		"""
		SELECT SUM(soi.base_net_amount)
		FROM `tabSales Order Item` soi
		INNER JOIN `tabSales Order` so ON so.name = soi.parent
		WHERE so.docstatus = 1
			AND (
				soi.project = %s
				OR (
					COALESCE(soi.project, '') = ''
					AND (
						so.project = %s
						OR (so.name = %s AND COALESCE(so.project, '') = '')
					)
				)
			)
		""",
		(project, project, sales_order or ""),
	)


def _project_revenue(project: str) -> float:
	return _sum_sql(
		"""
		SELECT SUM(
			CASE
				WHEN si.is_return = 1 THEN -ABS(sii.base_net_amount)
				ELSE sii.base_net_amount
			END
		)
		FROM `tabSales Invoice Item` sii
		INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE si.docstatus = 1
			AND (
				sii.project = %s
				OR (COALESCE(sii.project, '') = '' AND si.project = %s)
			)
		""",
		(project, project),
	)


def _project_purchase_cost(project: str) -> float:
	return _sum_sql(
		"""
		SELECT SUM(
			CASE
				WHEN pi.is_return = 1 THEN -ABS(pii.base_net_amount)
				ELSE pii.base_net_amount
			END
		)
		FROM `tabPurchase Invoice Item` pii
		INNER JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
		WHERE pi.docstatus = 1
			AND (
				pii.project = %s
				OR (COALESCE(pii.project, '') = '' AND pi.project = %s)
			)
		""",
		(project, project),
	)


def _project_expense_cost(project: str) -> float:
	return _sum_sql(
		"""
		SELECT SUM(ecd.base_sanctioned_amount)
		FROM `tabExpense Claim Detail` ecd
		INNER JOIN `tabExpense Claim` ec ON ec.name = ecd.parent
		WHERE ec.docstatus = 1
			AND ec.approval_status = 'Approved'
			AND (
				ecd.project = %s
				OR (COALESCE(ecd.project, '') = '' AND ec.project = %s)
			)
		""",
		(project, project),
	)


def _project_labor_cost(project: str) -> tuple[float, int, int]:
	rows = frappe.db.sql(
		"""
		SELECT
			SUM(base_costing_amount),
			SUM(CASE WHEN td.hours > 0 AND COALESCE(td.costing_rate, 0) <= 0 THEN 1 ELSE 0 END),
			SUM(
				CASE WHEN td.hours > 0 AND NOT EXISTS (
					SELECT 1
					FROM `tabEmployee Cost Rate` ecr
					WHERE ecr.employee = ts.employee
						AND ecr.company = ts.company
						AND ecr.effective_date <= COALESCE(DATE(td.from_time), ts.start_date)
				) THEN 1 ELSE 0 END
			)
		FROM `tabTimesheet Detail` td
		INNER JOIN `tabTimesheet` ts ON ts.name = td.parent
		WHERE td.docstatus = 1 AND td.project = %s
		""",
		(project,),
		as_list=True,
	)
	if not rows:
		return 0, 0, 0
	return flt(rows[0][0]), int(rows[0][1] or 0), int(rows[0][2] or 0)


def _project_progress(project: str) -> float:
	rows = frappe.db.sql(
		"""
		SELECT
			COUNT(*),
			SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END)
		FROM `tabTask`
		WHERE project = %s AND status NOT IN ('Template', 'Cancelled')
		""",
		(project,),
		as_list=True,
	)
	total = int(rows[0][0] or 0) if rows else 0
	completed = int(rows[0][1] or 0) if rows else 0
	return completed / total * 100 if total else 0


def _build_financial_payload(
	project_doc,
	*,
	currency: str | None,
	contract_value: float,
	actual_revenue: float,
	labor_cost: float,
	purchase_cost: float,
	expense_cost: float,
	progress_percentage: float,
	budget: float | None,
	estimate_count: int = 0,
	uncosted_timesheet_rows: int = 0,
	unmatched_rate_rows: int = 0,
	assigned_employees: list | None = None,
) -> dict:
	"""Assemble the payload shared by the single-project and portfolio endpoints.

	Both paths must agree to the last decimal, so the derived figures live here once
	rather than in each query strategy.
	"""
	total_cost = labor_cost + purchase_cost + expense_cost
	profit = actual_revenue - total_cost
	end_date = getdate(project_doc.expected_end_date) if project_doc.expected_end_date else None
	overdue = bool(
		end_date
		and getdate(today()) > end_date
		and project_doc.status != "Completed"
	)

	warnings = []
	if uncosted_timesheet_rows:
		warnings.append(
			f"{uncosted_timesheet_rows} submitted project timesheet row(s) have no costing rate."
		)
	if unmatched_rate_rows:
		warnings.append(
			f"{unmatched_rate_rows} submitted project timesheet row(s) have no Employee Cost Rate "
			"effective on the work date."
		)
	if estimate_count > 1:
		warnings.append("More than one Approved cost estimate is linked to this project or Sales Order.")

	return {
		"project": project_doc.name,
		"project_name": project_doc.project_name,
		"customer": project_doc.customer,
		"currency": currency,
		"contract_value": contract_value,
		"actual_revenue": actual_revenue,
		"labor_cost": labor_cost,
		"purchase_cost": purchase_cost,
		"expense_cost": expense_cost,
		"total_cost": total_cost,
		"profit": profit,
		"margin_percentage": profit / actual_revenue * 100 if actual_revenue else None,
		"is_profitable": profit > 0,
		"budget": budget,
		"is_over_budget": total_cost > budget if budget is not None else None,
		"over_budget_amount": max(total_cost - budget, 0) if budget is not None else None,
		"start_date": project_doc.expected_start_date,
		"end_date": project_doc.expected_end_date,
		"status": project_doc.status,
		"progress_percentage": progress_percentage,
		"is_overdue": overdue,
		"labor_cost_complete": not uncosted_timesheet_rows and not unmatched_rate_rows,
		"assigned_employees": assigned_employees or [],
		"warnings": warnings,
	}


def _project_financials(project_doc) -> dict:
	"""One project, priced with the same per-document queries as the portfolio endpoint."""
	project = project_doc.name
	contract_value = _project_contract_value(project, project_doc.sales_order)
	actual_revenue = _project_revenue(project)
	labor_cost, uncosted_timesheet_rows, unmatched_rate_rows = _project_labor_cost(project)
	purchase_cost = _project_purchase_cost(project)
	expense_cost = _project_expense_cost(project)

	estimate_or_filters = [{"project": project}]
	if project_doc.sales_order:
		estimate_or_filters.append({"sales_order": project_doc.sales_order})
	estimates = frappe.get_all(
		"Project Cost Estimate",
		filters={"status": "Approved"},
		or_filters=estimate_or_filters,
		fields=["estimated_total_cost"],
		limit_page_length=0,
	)

	allocations = frappe.get_all(
		"Resource Allocation",
		filters={"project": project},
		fields=[
			"employee",
			"role",
			"allocation_percentage",
			"planned_hours",
			"start_date",
			"end_date",
		],
		order_by="start_date asc",
		limit_page_length=0,
	)
	employee_names = {}
	if allocations:
		employees = {row.employee for row in allocations}
		employee_names = {
			row.name: row.employee_name
			for row in frappe.get_all(
				"Employee",
				filters={"name": ["in", list(employees)]},
				fields=["name", "employee_name"],
				limit_page_length=0,
			)
		}
	for allocation in allocations:
		allocation.employee_name = employee_names.get(allocation.employee)

	return _build_financial_payload(
		project_doc,
		currency=frappe.db.get_value("Company", project_doc.company, "default_currency")
		if project_doc.company
		else None,
		contract_value=contract_value,
		actual_revenue=actual_revenue,
		labor_cost=labor_cost,
		purchase_cost=purchase_cost,
		expense_cost=expense_cost,
		progress_percentage=_project_progress(project),
		budget=flt(estimates[0].estimated_total_cost) if len(estimates) == 1 else None,
		estimate_count=len(estimates),
		uncosted_timesheet_rows=uncosted_timesheet_rows,
		unmatched_rate_rows=unmatched_rate_rows,
		assigned_employees=allocations,
	)


def _grouped_totals(query: str, values: dict, field: str = "total") -> dict:
	"""Key a grouped SUM query by the project it was attributed to."""
	return {
		row.project: flt(row.get(field))
		for row in frappe.db.sql(query, values, as_dict=True)
		if row.get("project")
	}


def _bulk_contract_value() -> dict:
	"""Submitted Sales Order item value, by item project → order project → linked project."""
	return _grouped_totals(
		"""
		SELECT
			COALESCE(NULLIF(soi.project, ''), NULLIF(so.project, ''), linked.name) AS project,
			SUM(soi.base_net_amount) AS total
		FROM `tabSales Order Item` soi
		INNER JOIN `tabSales Order` so ON so.name = soi.parent
		LEFT JOIN `tabProject` linked
			ON linked.sales_order = so.name
			AND COALESCE(so.project, '') = ''
			AND COALESCE(soi.project, '') = ''
		WHERE so.docstatus = 1
		GROUP BY 1
		""",
		{},
	)


def _bulk_revenue() -> dict:
	return _grouped_totals(
		"""
		SELECT
			COALESCE(NULLIF(sii.project, ''), si.project) AS project,
			SUM(
				CASE
					WHEN si.is_return = 1 THEN -ABS(sii.base_net_amount)
					ELSE sii.base_net_amount
				END
			) AS total
		FROM `tabSales Invoice Item` sii
		INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE si.docstatus = 1
		GROUP BY 1
		""",
		{},
	)


def _bulk_purchase_cost() -> dict:
	return _grouped_totals(
		"""
		SELECT
			COALESCE(NULLIF(pii.project, ''), pi.project) AS project,
			SUM(
				CASE
					WHEN pi.is_return = 1 THEN -ABS(pii.base_net_amount)
					ELSE pii.base_net_amount
				END
			) AS total
		FROM `tabPurchase Invoice Item` pii
		INNER JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
		WHERE pi.docstatus = 1
		GROUP BY 1
		""",
		{},
	)


def _bulk_expense_cost() -> dict:
	return _grouped_totals(
		"""
		SELECT
			COALESCE(NULLIF(ecd.project, ''), ec.project) AS project,
			SUM(ecd.base_sanctioned_amount) AS total
		FROM `tabExpense Claim Detail` ecd
		INNER JOIN `tabExpense Claim` ec ON ec.name = ecd.parent
		WHERE ec.docstatus = 1
			AND ec.approval_status = 'Approved'
		GROUP BY 1
		""",
		{},
	)


def _bulk_labor_cost() -> dict:
	rows = frappe.db.sql(
		"""
		SELECT
			td.project AS project,
			SUM(td.base_costing_amount) AS labor_cost,
			SUM(CASE WHEN td.hours > 0 AND COALESCE(td.costing_rate, 0) <= 0 THEN 1 ELSE 0 END) AS uncosted,
			SUM(
				CASE WHEN td.hours > 0 AND NOT EXISTS (
					SELECT 1
					FROM `tabEmployee Cost Rate` ecr
					WHERE ecr.employee = ts.employee
						AND ecr.company = ts.company
						AND ecr.effective_date <= COALESCE(DATE(td.from_time), ts.start_date)
				) THEN 1 ELSE 0 END
			) AS unmatched
		FROM `tabTimesheet Detail` td
		INNER JOIN `tabTimesheet` ts ON ts.name = td.parent
		WHERE td.docstatus = 1 AND COALESCE(td.project, '') != ''
		GROUP BY td.project
		""",
		{},
		as_dict=True,
	)
	return {
		row.project: {
			"labor_cost": flt(row.labor_cost),
			"uncosted": int(row.uncosted or 0),
			"unmatched": int(row.unmatched or 0),
		}
		for row in rows
		if row.project
	}


def _bulk_progress() -> dict:
	rows = frappe.db.sql(
		"""
		SELECT
			project,
			COUNT(*) AS total,
			SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) AS completed
		FROM `tabTask`
		WHERE status NOT IN ('Template', 'Cancelled') AND COALESCE(project, '') != ''
		GROUP BY project
		""",
		{},
		as_dict=True,
	)
	return {
		row.project: {"total": int(row.total or 0), "completed": int(row.completed or 0)}
		for row in rows
		if row.project
	}


def _bulk_estimates() -> dict:
	rows = frappe.db.sql(
		"""
		SELECT
			COALESCE(NULLIF(e.project, ''), linked.name) AS project,
			COUNT(*) AS estimate_count,
			MAX(e.estimated_total_cost) AS amount
		FROM `tabProject Cost Estimate` e
		LEFT JOIN `tabProject` linked
			ON linked.sales_order = e.sales_order
			AND COALESCE(e.project, '') = ''
		WHERE e.status = 'Approved'
		GROUP BY 1
		""",
		{},
		as_dict=True,
	)
	return {
		row.project: {"count": int(row.estimate_count or 0), "amount": flt(row.amount)}
		for row in rows
		if row.project
	}


def _company_projects_financials(company: str) -> list[dict]:
	"""Every visible project of a company, priced in a fixed number of queries."""
	currency = frappe.db.get_value("Company", company, "default_currency")
	projects = frappe.get_list(
		"Project",
		filters={"company": company},
		fields=[
			"name",
			"project_name",
			"customer",
			"company",
			"status",
			"expected_start_date",
			"expected_end_date",
			"sales_order",
		],
		order_by="name asc",
		limit_page_length=0,
	)
	if not projects:
		return []

	contract = _bulk_contract_value()
	revenue = _bulk_revenue()
	purchase = _bulk_purchase_cost()
	expense = _bulk_expense_cost()
	labor = _bulk_labor_cost()
	progress = _bulk_progress()
	estimates = _bulk_estimates()

	rows = []
	for raw in projects:
		project = frappe._dict(raw)
		labor_row = labor.get(project.name) or {}
		progress_row = progress.get(project.name) or {}
		estimate_row = estimates.get(project.name) or {}
		total_tasks = int(progress_row.get("total") or 0)
		completed = int(progress_row.get("completed") or 0)
		estimate_count = int(estimate_row.get("count") or 0)

		rows.append(
			_build_financial_payload(
				project,
				currency=currency,
				contract_value=contract.get(project.name, 0),
				actual_revenue=revenue.get(project.name, 0),
				labor_cost=labor_row.get("labor_cost", 0),
				purchase_cost=purchase.get(project.name, 0),
				expense_cost=expense.get(project.name, 0),
				progress_percentage=completed / total_tasks * 100 if total_tasks else 0,
				budget=estimate_row.get("amount") if estimate_count == 1 else None,
				estimate_count=estimate_count,
				uncosted_timesheet_rows=labor_row.get("uncosted", 0),
				unmatched_rate_rows=labor_row.get("unmatched", 0),
			)
		)
	return rows


@frappe.whitelist()
def get_project_financials(project: str) -> dict:
	"""Return current submitted project financials, progress, and overdue state."""
	_require_roles(PROJECT_COSTING_ROLES)
	_require_hrms()

	if not frappe.db.exists("Project", project):
		frappe.throw(f"Project {project} does not exist.", frappe.DoesNotExistError)
	if not frappe.has_permission("Project", "read", project):
		frappe.throw("You do not have permission to view this project.", frappe.PermissionError)

	return _project_financials(frappe.get_doc("Project", project))


def calculate_available_hours(
	start_date,
	end_date,
	weekly_off: str | None,
	holidays: dict,
	list_start=None,
	list_end=None,
	employment_start=None,
	employment_end=None,
) -> float | None:
	"""Calculate capacity from an employee holiday calendar and an 8-hour day."""
	start = getdate(start_date)
	end = getdate(end_date)
	if end < start:
		frappe.throw("End Date cannot be earlier than Start Date.")

	if (list_start and start < getdate(list_start)) or (list_end and end > getdate(list_end)):
		return None

	weekly_off_days = {
		WEEKDAYS[day.strip()]
		for day in re.split(r"[\n,;]+", weekly_off or "")
		if day.strip() in WEEKDAYS
	}
	employment_start = getdate(employment_start) if employment_start else None
	employment_end = getdate(employment_end) if employment_end else None

	hours = 0
	current = start
	while current <= end:
		if employment_start and current < employment_start:
			current += timedelta(days=1)
			continue
		if employment_end and current > employment_end:
			break
		if current.weekday() in weekly_off_days:
			current += timedelta(days=1)
			continue

		holiday = holidays.get(current)
		if holiday is not None:
			if holiday:
				hours += HALF_DAY_HOURS
			current += timedelta(days=1)
			continue

		hours += HOURS_PER_WORKING_DAY
		current += timedelta(days=1)

	return hours


def _employee_record(employee: str) -> dict:
	if not frappe.db.exists("Employee", employee):
		frappe.throw(f"Employee {employee} does not exist.", frappe.DoesNotExistError)

	fields = {field.fieldname for field in frappe.get_meta("Employee").fields}
	selected_fields = ["employee_name", "company", "holiday_list", "date_of_joining"]
	if "relieving_date" in fields:
		selected_fields.append("relieving_date")

	return frappe.db.get_value("Employee", employee, selected_fields, as_dict=True)


def _employee_calendar(employee: dict, calendar_cache: dict | None = None) -> dict | None:
	holiday_list_name = employee.holiday_list or frappe.db.get_value(
		"Company", employee.company, "default_holiday_list"
	)
	if not holiday_list_name:
		return None

	calendar_cache = calendar_cache if calendar_cache is not None else {}
	if holiday_list_name not in calendar_cache:
		if not frappe.db.exists("Holiday List", holiday_list_name):
			calendar_cache[holiday_list_name] = None
		else:
			holiday_list = frappe.get_doc("Holiday List", holiday_list_name)
			calendar_cache[holiday_list_name] = {
				"weekly_off": holiday_list.weekly_off,
				"holidays": {
					getdate(row.holiday_date): bool(row.is_half_day)
					for row in holiday_list.holidays
					if row.holiday_date
				},
				"list_start": holiday_list.from_date,
				"list_end": holiday_list.to_date,
			}

	holiday_calendar = calendar_cache[holiday_list_name]
	if not holiday_calendar:
		return None

	return {
		**holiday_calendar,
		"employment_start": employee.date_of_joining,
		"employment_end": employee.get("relieving_date"),
	}


def _calendar_capacity(calendar: dict | None, start_date, end_date) -> float | None:
	if not calendar:
		return None
	return calculate_available_hours(
		start_date,
		end_date,
		calendar["weekly_off"],
		calendar["holidays"],
		calendar["list_start"],
		calendar["list_end"],
		calendar["employment_start"],
		calendar["employment_end"],
	)


def _get_period(start_date=None, end_date=None):
	end = getdate(end_date or today())
	start = getdate(start_date or end.replace(day=1))
	if end < start:
		frappe.throw("End Date cannot be earlier than Start Date.")
	return start, end


def _active_cost_rate(employee: str, company: str, effective_date):
	rows = frappe.get_all(
		"Employee Cost Rate",
		filters={
			"employee": employee,
			"company": company,
			"is_active": 1,
			"effective_date": ["<=", effective_date],
		},
		fields=["cost_rate_per_hour", "billing_rate_per_hour", "effective_date"],
		order_by="effective_date desc",
		limit_page_length=1,
	)
	return rows[0] if rows else None


@frappe.whitelist()
def get_employee_summary(employee: str, start_date=None, end_date=None) -> dict:
	"""Return allocation, timesheet, utilization, and labor-cost data for one employee."""
	_require_roles(EMPLOYEE_COSTING_ROLES)
	_require_hrms()

	if not frappe.has_permission("Employee", "read", employee):
		frappe.throw("You do not have permission to view this employee.", frappe.PermissionError)

	start, end = _get_period(start_date, end_date)
	employee_doc = _employee_record(employee)
	calendar = _employee_calendar(employee_doc)
	available_hours = _calendar_capacity(calendar, start, end)

	rows = frappe.db.sql(
		"""
		SELECT
			COALESCE(SUM(td.hours), 0),
			COALESCE(SUM(
				CASE WHEN COALESCE(td.project, '') != ''
					THEN COALESCE(td.base_costing_amount, 0)
					ELSE 0
				END
			), 0)
		FROM `tabTimesheet Detail` td
		INNER JOIN `tabTimesheet` ts ON ts.name = td.parent
		WHERE ts.employee = %s
			AND ts.docstatus = 1
			AND COALESCE(DATE(td.from_time), ts.start_date) BETWEEN %s AND %s
		""",
		(employee, start, end),
		as_list=True,
	)
	actual_hours = flt(rows[0][0]) if rows else 0
	project_labor_cost = flt(rows[0][1]) if rows else 0

	allocations = frappe.get_all(
		"Resource Allocation",
		filters={"employee": employee},
		fields=[
			"name",
			"project",
			"role",
			"allocation_percentage",
			"planned_hours",
			"start_date",
			"end_date",
		],
		order_by="start_date asc",
		limit_page_length=0,
	)
	project_names = {row.project for row in allocations}
	project_rows = frappe.get_all(
		"Project",
		filters={"name": ["in", list(project_names)]} if project_names else {"name": ""},
		fields=["name", "project_name", "status"],
		limit_page_length=0,
	)
	projects = {row.name: row for row in project_rows}
	today_date = getdate(today())
	current_projects = []
	future_projects = []
	planned_hours = 0
	planned_hours_complete = bool(calendar) or not allocations
	current_allocation_percentage = 0

	for allocation in allocations:
		project_row = projects.get(allocation.project)
		allocation.project_name = project_row.project_name if project_row else None
		allocation.project_status = project_row.status if project_row else None
		allocation_start = getdate(allocation.start_date)
		allocation_end = getdate(allocation.end_date)
		if (
			project_row
			and project_row.status not in ("Completed", "Cancelled")
			and allocation_start <= today_date <= allocation_end
		):
			current_projects.append(allocation)
			current_allocation_percentage += flt(allocation.allocation_percentage)
		elif (
			project_row
			and project_row.status not in ("Completed", "Cancelled")
			and allocation_start > today_date
		):
			future_projects.append(allocation)

		overlap_start = max(start, allocation_start)
		overlap_end = min(end, allocation_end)
		if overlap_start > overlap_end or not flt(allocation.planned_hours):
			continue

		allocation_capacity = _calendar_capacity(calendar, allocation_start, allocation_end)
		period_capacity = _calendar_capacity(calendar, overlap_start, overlap_end)
		if allocation_capacity is None or period_capacity is None:
			planned_hours_complete = False
		elif allocation_capacity:
			planned_hours += flt(allocation.planned_hours) * period_capacity / allocation_capacity

	cost_rate = _active_cost_rate(employee, employee_doc.company, today_date)
	currency = (
		frappe.db.get_value("Company", employee_doc.company, "default_currency")
		if employee_doc.company
		else None
	)
	warnings = []
	if available_hours is None:
		warnings.append("Available hours cannot be calculated: the employee's holiday calendar is missing or does not cover the selected period.")
	if not planned_hours_complete:
		warnings.append("Planned hours cannot be fully prorated because a holiday calendar is unavailable for an allocation period.")
	if current_allocation_percentage > 100:
		warnings.append(
			f"Current project allocations total {current_allocation_percentage:g}% of capacity."
		)
	if not cost_rate:
		warnings.append("No active Employee Cost Rate is effective today.")

	return {
		"employee": employee,
		"employee_name": employee_doc.employee_name,
		"company": employee_doc.company,
		"currency": currency,
		"period_start": start,
		"period_end": end,
		"assigned_projects": allocations,
		"current_projects": current_projects,
		"future_projects": future_projects,
		"planned_hours": planned_hours if planned_hours_complete else None,
		"actual_hours": actual_hours,
		"available_hours": available_hours,
		"utilization_percentage": (
			actual_hours / available_hours * 100 if available_hours else None
		),
		"project_labor_cost": project_labor_cost,
		"cost_rate_per_hour": flt(cost_rate.cost_rate_per_hour) if cost_rate else None,
		"billing_rate_per_hour": flt(cost_rate.billing_rate_per_hour) if cost_rate else None,
		"current_allocation_percentage": current_allocation_percentage,
		"warnings": warnings,
	}


def _executive_project_row(project: dict) -> dict:
	return {
		fieldname: project.get(fieldname)
		for fieldname in (
			"project",
			"project_name",
			"customer",
			"contract_value",
			"actual_revenue",
			"total_cost",
			"profit",
			"margin_percentage",
			"status",
			"start_date",
			"end_date",
			"progress_percentage",
			"is_overdue",
		)
	}


def _aggregate_executive_projects(projects: list[dict]) -> dict:
	project_rows = [_executive_project_row(project) for project in projects]
	total_contract_value = sum(flt(project.get("contract_value")) for project in project_rows)
	total_revenue = sum(flt(project.get("actual_revenue")) for project in project_rows)
	total_cost = sum(flt(project.get("total_cost")) for project in project_rows)
	total_profit = sum(flt(project.get("profit")) for project in project_rows)
	profitable = sorted(
		(project for project in project_rows if flt(project.get("profit")) > 0),
		key=lambda project: (-flt(project.get("profit")), project.get("project_name") or ""),
	)
	loss_making = sorted(
		(project for project in project_rows if flt(project.get("profit")) < 0),
		key=lambda project: (flt(project.get("profit")), project.get("project_name") or ""),
	)

	return {
		"total_projects": len(project_rows),
		"active_projects": sum(
			project.get("status") not in ("Completed", "Cancelled") for project in project_rows
		),
		"completed_projects": sum(project.get("status") == "Completed" for project in project_rows),
		"overdue_projects": sum(bool(project.get("is_overdue")) for project in project_rows),
		"total_contract_value": total_contract_value,
		"total_revenue": total_revenue,
		"total_cost": total_cost,
		"total_profit": total_profit,
		"average_margin_percentage": total_profit / total_revenue * 100 if total_revenue else None,
		"top_profitable_projects": profitable[:5],
		"projects_running_at_loss": loss_making[:5],
		"project_warnings": [
			{
				"project": project.get("project"),
				"project_name": project.get("project_name"),
				"warnings": project.get("warnings"),
			}
			for project in projects
			if project.get("warnings")
		],
	}


def _utilization_unavailable(start_date, end_date, reason: str) -> dict:
	"""Utilization shape returned when the caller may not read Employee records.

	The executive summary still returns project financials, but never a partial or zero
	utilization figure that could be mistaken for a measured value.
	"""
	return {
		"period_start": start_date,
		"period_end": end_date,
		"permitted": False,
		"employee_count": 0,
		"employees_with_timesheets": 0,
		"employees_with_capacity": 0,
		"employees_missing_capacity": 0,
		"actual_hours": 0,
		"available_hours": None,
		"capacity_complete": False,
		"utilization_percentage": None,
		"warnings": [reason],
	}


def _executive_employee_utilization(company: str, start_date, end_date) -> dict:
	if not frappe.has_permission("Employee", "read"):
		return _utilization_unavailable(
			start_date,
			end_date,
			"Employee utilization is unavailable because you do not have permission to read "
			"Employee records.",
		)

	employee_fields = {field.fieldname for field in frappe.get_meta("Employee").fields}
	fields = ["name", "company", "holiday_list", "date_of_joining"]
	if "relieving_date" in employee_fields:
		fields.append("relieving_date")
	employees = frappe.get_list(
		"Employee",
		filters={"company": company},
		fields=fields,
		order_by="name asc",
		limit_page_length=0,
	)
	employee_names = [employee.name for employee in employees]
	actual_hours_by_employee = {}
	if employee_names:
		rows = frappe.db.sql(
			"""
			SELECT ts.employee, COALESCE(SUM(td.hours), 0) AS actual_hours
			FROM `tabTimesheet Detail` td
			INNER JOIN `tabTimesheet` ts ON ts.name = td.parent
			WHERE ts.company = %s
				AND ts.docstatus = 1
				AND COALESCE(DATE(td.from_time), ts.start_date) BETWEEN %s AND %s
				AND ts.employee IN %s
			GROUP BY ts.employee
			""",
			(company, start_date, end_date, tuple(employee_names)),
			as_dict=True,
		)
		actual_hours_by_employee = {row.employee: flt(row.actual_hours) for row in rows}

	total_actual_hours = sum(actual_hours_by_employee.values())
	total_available_hours = 0
	employees_with_capacity = 0
	employees_missing_capacity = 0
	calendar_cache = {}
	for employee in employees:
		calendar = _employee_calendar(employee, calendar_cache)
		available_hours = _calendar_capacity(calendar, start_date, end_date)
		if available_hours is None:
			employees_missing_capacity += 1
		else:
			total_available_hours += available_hours
			if available_hours > 0:
				employees_with_capacity += 1

	capacity_complete = employees_missing_capacity == 0
	warnings = []
	if employees_missing_capacity:
		warnings.append(
			f"Available hours are incomplete for {employees_missing_capacity} employee(s) "
			"because a holiday calendar is missing or does not cover the selected period."
		)

	return {
		"period_start": start_date,
		"period_end": end_date,
		"permitted": True,
		"employee_count": len(employees),
		"employees_with_timesheets": sum(
			actual_hours_by_employee.get(employee, 0) > 0 for employee in employee_names
		),
		"employees_with_capacity": employees_with_capacity,
		"employees_missing_capacity": employees_missing_capacity,
		"actual_hours": total_actual_hours,
		"available_hours": total_available_hours if capacity_complete else None,
		"capacity_complete": capacity_complete,
		"utilization_percentage": (
			total_actual_hours / total_available_hours * 100
			if capacity_complete and total_available_hours
			else None
		),
		"warnings": warnings,
	}


@frappe.whitelist()
def get_projects_financials(company: str) -> dict:
	"""Return every visible company project's financials in a fixed number of queries.

	The project dashboard needs the whole portfolio; calling `get_project_financials`
	once per project would issue a dozen queries each.
	"""
	_require_roles(PROJECT_COSTING_ROLES)
	_require_hrms()

	if not frappe.db.exists("Company", company):
		frappe.throw(f"Company {company} does not exist.", frappe.DoesNotExistError)
	if not frappe.has_permission("Company", "read", company):
		frappe.throw("You do not have permission to view this company.", frappe.PermissionError)

	return {
		"company": company,
		"currency": frappe.db.get_value("Company", company, "default_currency"),
		"financials_as_of": today(),
		"projects": _company_projects_financials(company),
	}


@frappe.whitelist()
def get_executive_summary(company: str, start_date=None, end_date=None) -> dict:
	"""Return company-level project financials and employee utilization."""
	_require_roles(PROJECT_COSTING_ROLES)
	_require_hrms()

	if not frappe.db.exists("Company", company):
		frappe.throw(f"Company {company} does not exist.", frappe.DoesNotExistError)
	if not frappe.has_permission("Company", "read", company):
		frappe.throw("You do not have permission to view this company.", frappe.PermissionError)

	start, end = _get_period(start_date, end_date)
	projects = _company_projects_financials(company)
	summary = _aggregate_executive_projects(projects)
	summary.update(
		{
			"company": company,
			"currency": frappe.db.get_value("Company", company, "default_currency"),
			"financials_as_of": today(),
			"employee_utilization": _executive_employee_utilization(company, start, end),
		}
	)
	return summary


def _timesheet_work_date(row, doc):
	value = row.from_time or doc.get("start_date")
	return getdate(value) if value else None


def _timesheet_rate_issues(doc) -> list[str]:
	issues = []
	project_rows = [row for row in doc.get("time_logs") or [] if row.project]
	if not project_rows:
		return issues
	if not doc.employee:
		return ["Select an employee before submitting project time."]

	employee_company = frappe.db.get_value("Employee", doc.employee, "company")
	company = doc.company or employee_company
	if not company:
		return [f"Employee {doc.employee} is not linked to a company."]

	company_currency = frappe.db.get_value("Company", company, "default_currency")
	timesheet_currency = doc.currency or company_currency
	exchange_rate = flt(doc.exchange_rate)
	if timesheet_currency == company_currency:
		exchange_rate = exchange_rate or 1
	elif exchange_rate <= 0:
		issues.append(
			f"Timesheet currency {timesheet_currency} needs a positive exchange rate to "
			f"{company_currency}."
		)

	for row in project_rows:
		work_date = _timesheet_work_date(row, doc)
		if not work_date:
			issues.append(f"Project time row {row.idx} has no work date.")
			continue
		rate = _active_cost_rate(doc.employee, company, work_date)
		if not rate:
			issues.append(
				f"No active Employee Cost Rate exists for {doc.employee} on {work_date} "
				f"for Project {row.project}."
			)

	return issues


def apply_employee_cost_rates(doc, method=None):
	"""Use the effective employee rate for project time while preserving ERPNext fields."""
	if doc.docstatus or not doc.employee:
		return

	for row in doc.get("time_logs") or []:
		if not row.project:
			continue
		work_date = _timesheet_work_date(row, doc)
		if not work_date:
			continue

		employee_company = frappe.db.get_value("Employee", doc.employee, "company")
		company = doc.company or employee_company
		if not company:
			continue

		rate = _active_cost_rate(doc.employee, company, work_date)
		if not rate:
			continue

		company_currency = frappe.db.get_value("Company", company, "default_currency")
		timesheet_currency = doc.currency or company_currency
		exchange_rate = flt(doc.exchange_rate)
		if timesheet_currency == company_currency:
			exchange_rate = exchange_rate or 1
		if exchange_rate <= 0:
			continue

		row.costing_rate = flt(rate.cost_rate_per_hour) / exchange_rate


def validate_project_timesheet_rates(doc, method=None):
	"""Block submission of project hours that cannot be costed deterministically."""
	issues = _timesheet_rate_issues(doc)
	if issues:
		frappe.throw(
			"\n".join(issues),
			title="Project labor cost rate required",
		)


# ─── Stored project fields ────────────────────────────────────────────────────
#
# The same figures the API returns, but written onto the Project so they are visible on the
# document itself. Read-only and permlevel 2 (see flowire.setup.project_fields).


def _project_planned_labor(project: str) -> tuple[float, float]:
	"""Planned hours and their cost, from this project's resource allocations."""
	allocations = frappe.get_all(
		"Resource Allocation",
		filters={"project": project},
		fields=["employee", "planned_hours", "start_date"],
		limit_page_length=0,
	)
	hours_total = 0.0
	cost_total = 0.0
	rate_cache = {}

	for allocation in allocations:
		hours = flt(allocation.planned_hours)
		hours_total += hours
		if not hours or not allocation.employee:
			continue

		company = frappe.db.get_value("Employee", allocation.employee, "company")
		if not company:
			continue

		# The rate in force when the allocation starts is the one it was planned at.
		effective_on = getdate(allocation.start_date) if allocation.start_date else getdate(today())
		key = (allocation.employee, company, effective_on)
		if key not in rate_cache:
			rate_cache[key] = _active_cost_rate(allocation.employee, company, effective_on)

		rate = rate_cache[key]
		if rate:
			cost_total += hours * flt(rate.cost_rate_per_hour)

	return hours_total, cost_total


def _has_project_fields() -> bool:
	return frappe.db.has_column("Project", "custom_flowire_profit")


@frappe.whitelist()
def refresh_project(project: str) -> dict:
	"""Recompute one project's stored fields on demand."""
	_require_roles(PROJECT_COSTING_ROLES)
	_require_hrms()

	if not frappe.db.exists("Project", project):
		frappe.throw(f"Project {project} does not exist.", frappe.DoesNotExistError)
	if not frappe.has_permission("Project", "read", project):
		frappe.throw("You do not have permission to view this project.", frappe.PermissionError)

	values = refresh_project_fields(project)
	frappe.db.commit()
	return values


def refresh_project_fields(project: str) -> dict:
	"""Write the Flowire cost fields onto a Project.

	Runs from transaction hooks as well as on demand, so it must never raise for a project
	that no longer exists or a site that has not migrated yet: bookkeeping must not break a
	submit.
	"""
	if not _has_project_fields() or not frappe.db.exists("Project", project):
		return {}

	# A hook fired from inside a refresh must not start another one.
	if frappe.flags.get("flowire_refreshing_project"):
		return {}

	frappe.flags.flowire_refreshing_project = True
	try:
		project_row = frappe.db.get_value(
			"Project", project, ["sales_order", "company"], as_dict=True
		)
		if not project_row:
			return {}

		contract_value = _project_contract_value(project, project_row.sales_order)
		actual_revenue = _project_revenue(project)
		labor_cost, _uncosted, _unmatched = _project_labor_cost(project)
		purchase_cost = _project_purchase_cost(project)
		expense_cost = _project_expense_cost(project)
		planned_hours, planned_labor_cost = _project_planned_labor(project)

		total_cost = labor_cost + purchase_cost + expense_cost
		profit = actual_revenue - total_cost
		margin = profit / actual_revenue * 100 if actual_revenue else 0

		# Revenue and total cost are NOT stored: ERPNext already keeps them as
		# `total_billed_amount` and the three native cost fields.
		values = {
			"custom_contract_value": contract_value,
			"custom_flowire_profit": profit,
			"custom_flowire_margin_percent": margin,
			"custom_planned_hours": planned_hours,
			"custom_planned_labor_cost": planned_labor_cost,
			"custom_flowire_refreshed_on": now_datetime(),
		}
		frappe.db.set_value("Project", project, values, update_modified=False)
		return values
	finally:
		frappe.flags.flowire_refreshing_project = False


def refresh_projects_for(doc, method=None):
	"""doc_event dispatcher: refresh every project a submitted/cancelled document touches."""
	projects = set()

	header = doc.get("project")
	if header:
		projects.add(header)

	# Sales/Purchase Invoice and Order lines, Timesheet time logs, Expense Claim expenses.
	for table in ("items", "time_logs", "expenses"):
		for row in doc.get(table) or []:
			project = row.get("project")
			if project:
				projects.add(project)

	for project in projects:
		refresh_project_fields(project)


# ─── Project attribution on financial documents ───────────────────────────────

def fill_header_project(doc, method=None):
	"""Fill a blank document project from the lines when they all name the same one.

	ERPNext totals `Project.total_sales_amount` per *document*, so an order whose project
	is only on its rows leaves the project reading zero while the line-aware Flowire
	revenue shows the money. Filling the header keeps the two in step. A document that
	spans several projects is left alone and stays attributed per line.
	"""
	if doc.get("project"):
		return

	projects = {row.get("project") for row in doc.get("items") or [] if row.get("project")}
	if len(projects) == 1:
		doc.project = projects.pop()


# ─── Opportunity → Project ────────────────────────────────────────────────────

PO_RECEIVED_STAGE = "PO Received"


def _project_name_for(opportunity_doc) -> str:
	"""The project's name: the opportunity's own name for it, else customer + PO number."""
	preferred = (opportunity_doc.get("custom_project_name") or opportunity_doc.get("title") or "").strip()
	if preferred:
		return preferred
	party = (
		opportunity_doc.get("customer_name")
		or opportunity_doc.get("party_name")
		or opportunity_doc.name
	)
	return f"{party} – {opportunity_doc.get('custom_po_no') or opportunity_doc.name}"


def _existing_project_for(opportunity_doc) -> str | None:
	"""The project already standing for this opportunity, if there is one.

	The explicit link is authoritative; an exact name within the same company is the
	fallback for projects created before the link existed.
	"""
	linked = frappe.db.get_value("Project", {"custom_opportunity": opportunity_doc.name}, "name")
	if linked:
		return linked

	name = _project_name_for(opportunity_doc)
	if not name:
		return None

	filters = {"project_name": name}
	if opportunity_doc.get("company"):
		filters["company"] = opportunity_doc.company
	return frappe.db.get_value("Project", filters, "name")


@frappe.whitelist()
def get_or_create_project_from_opportunity(opportunity: str) -> dict:
	"""Return the project this opportunity belongs to, creating it once if needed.

	Idempotent by design: clicking twice, or two users clicking at the same moment, must
	land on one project rather than two.
	"""
	if not frappe.db.exists("Opportunity", opportunity):
		frappe.throw(f"Opportunity {opportunity} does not exist.", frappe.DoesNotExistError)
	if not frappe.has_permission("Opportunity", "read", opportunity):
		frappe.throw("You do not have permission to view this opportunity.", frappe.PermissionError)

	opportunity_doc = frappe.get_doc("Opportunity", opportunity)
	if opportunity_doc.get("sales_stage") != PO_RECEIVED_STAGE:
		frappe.throw(
			f"A project can be created once the opportunity stage is {PO_RECEIVED_STAGE}.",
			frappe.ValidationError,
		)

	existing = _existing_project_for(opportunity_doc)
	if existing:
		# Stamp the link on a project that predates the field, so later clicks are exact.
		if not frappe.db.get_value("Project", existing, "custom_opportunity"):
			frappe.db.set_value(
				"Project", existing, "custom_opportunity", opportunity, update_modified=False
			)
		return {"project": existing, "created": False}

	if not frappe.has_permission("Project", "create"):
		frappe.throw("You do not have permission to create projects.", frappe.PermissionError)

	project = frappe.get_doc(
		{
			"doctype": "Project",
			"project_name": _project_name_for(opportunity_doc),
			"status": "Open",
			"company": opportunity_doc.get("company"),
			# Project.customer is a Customer link, so only a Customer-based opportunity maps.
			"customer": opportunity_doc.get("party_name")
			if opportunity_doc.get("opportunity_from") == "Customer"
			else None,
			"expected_start_date": today(),
			"expected_end_date": opportunity_doc.get("expected_closing"),
			"estimated_costing": flt(opportunity_doc.get("opportunity_amount")),
			"custom_opportunity": opportunity,
			"notes": f"Created from Opportunity {opportunity} "
			f"(stage: {opportunity_doc.get('sales_stage')}).",
		}
	).insert()

	return {"project": project.name, "created": True}
