"""Server-side project costing and resource summaries.

Actual transactions remain in ERPNext/HRMS. This module reads submitted source
records and never writes derived financial totals back to standard doctypes.
"""

import re
from datetime import timedelta

import frappe
from frappe.utils import flt, getdate, today

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


@frappe.whitelist()
def get_project_financials(project: str) -> dict:
	"""Return current submitted project financials, progress, and overdue state."""
	_require_roles(PROJECT_COSTING_ROLES)
	_require_hrms()

	if not frappe.db.exists("Project", project):
		frappe.throw(f"Project {project} does not exist.", frappe.DoesNotExistError)
	if not frappe.has_permission("Project", "read", project):
		frappe.throw("You do not have permission to view this project.", frappe.PermissionError)

	project_doc = frappe.get_doc("Project", project)
	contract_value = _project_contract_value(project, project_doc.sales_order)
	actual_revenue = _project_revenue(project)
	labor_cost, uncosted_timesheet_rows, unmatched_rate_rows = _project_labor_cost(project)
	purchase_cost = _project_purchase_cost(project)
	expense_cost = _project_expense_cost(project)
	total_cost = labor_cost + purchase_cost + expense_cost
	profit = actual_revenue - total_cost

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
	budget = flt(estimates[0].estimated_total_cost) if len(estimates) == 1 else None
	end_date = getdate(project_doc.expected_end_date) if project_doc.expected_end_date else None
	overdue = bool(
		end_date
		and getdate(today()) > end_date
		and project_doc.status != "Completed"
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
	if len(estimates) > 1:
		warnings.append("More than one Approved cost estimate is linked to this project or Sales Order.")

	return {
		"project": project,
		"project_name": project_doc.project_name,
		"customer": project_doc.customer,
		"currency": frappe.db.get_value("Company", project_doc.company, "default_currency")
		if project_doc.company
		else None,
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
		"progress_percentage": _project_progress(project),
		"is_overdue": overdue,
		"labor_cost_complete": not uncosted_timesheet_rows and not unmatched_rate_rows,
		"assigned_employees": allocations,
		"warnings": warnings,
	}


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


def _employee_calendar(employee: dict) -> dict | None:
	holiday_list_name = employee.holiday_list or frappe.db.get_value(
		"Company", employee.company, "default_holiday_list"
	)
	if not holiday_list_name or not frappe.db.exists("Holiday List", holiday_list_name):
		return None

	holiday_list = frappe.get_doc("Holiday List", holiday_list_name)
	holidays = {
		getdate(row.holiday_date): bool(row.is_half_day)
		for row in holiday_list.holidays
		if row.holiday_date
	}
	return {
		"weekly_off": holiday_list.weekly_off,
		"holidays": holidays,
		"list_start": holiday_list.from_date,
		"list_end": holiday_list.to_date,
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
