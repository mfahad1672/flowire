from datetime import date
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from flowire.flowire.doctype.project_cost_estimate.project_cost_estimate import (
	calculate_estimate_values,
)
from flowire.flowire.project_costing import (
	_aggregate_executive_projects,
	_executive_employee_utilization,
	_timesheet_rate_issues,
	apply_employee_cost_rates,
	calculate_available_hours,
	get_executive_summary,
)


class TestProjectCostingCalculations(IntegrationTestCase):
	def test_estimate_totals_include_all_cost_categories(self):
		values = calculate_estimate_values(
			{
				"estimated_revenue": 10000,
				"estimated_labor_cost": 1000,
				"estimated_purchase_cost": 2000,
				"estimated_travel_cost": 100,
				"estimated_software_cost": 200,
				"estimated_subcontractor_cost": 300,
				"estimated_miscellaneous_cost": 400,
			}
		)

		self.assertEqual(values["estimated_expense_cost"], 1000)
		self.assertEqual(values["estimated_total_cost"], 4000)
		self.assertEqual(values["expected_profit"], 6000)
		self.assertEqual(values["expected_margin_percent"], 60)

	def test_zero_revenue_has_zero_estimated_margin(self):
		values = calculate_estimate_values(
			{
				"estimated_revenue": 0,
				"estimated_labor_cost": 100,
			}
		)

		self.assertEqual(values["expected_profit"], -100)
		self.assertEqual(values["expected_margin_percent"], 0)

	def test_available_hours_obey_holidays_and_employment_dates(self):
		hours = calculate_available_hours(
			"2026-11-16",
			"2026-11-22",
			"Sunday",
			{
				# A full holiday and a half-day holiday.
				date(2026, 11, 18): False,
				date(2026, 11, 19): True,
			},
			list_start="2026-01-01",
			list_end="2026-12-31",
			employment_start="2026-11-17",
		)

		self.assertEqual(hours, 28)

	def test_capacity_is_unknown_outside_holiday_list_coverage(self):
		hours = calculate_available_hours(
			"2027-01-01",
			"2027-01-05",
			"Sunday",
			{},
			list_start="2026-01-01",
			list_end="2026-12-31",
		)

		self.assertIsNone(hours)

	def test_project_timesheet_uses_company_rate_converted_to_timesheet_currency(self):
		row = frappe._dict({"project": "PROJECT-1", "from_time": "2026-11-16 09:00:00"})
		doc = frappe._dict(
			{
				"employee": "EMPLOYEE-1",
				"company": "COMPANY-1",
				"currency": "EUR",
				"exchange_rate": 0.8,
				"docstatus": 0,
				"time_logs": [row],
			}
		)

		with (
			patch("flowire.flowire.project_costing.frappe.db.get_value", side_effect=["COMPANY-1", "USD"]),
			patch(
				"flowire.flowire.project_costing._active_cost_rate",
				return_value=frappe._dict({"cost_rate_per_hour": 200}),
			),
		):
			apply_employee_cost_rates(doc)

		self.assertEqual(row.costing_rate, 250)

	def test_project_timesheet_without_effective_rate_is_blocked(self):
		doc = frappe._dict(
			{
				"employee": "EMPLOYEE-1",
				"company": "COMPANY-1",
				"currency": "USD",
				"exchange_rate": 1,
				"time_logs": [
					frappe._dict(
						{
							"project": "PROJECT-1",
							"from_time": "2026-11-16 09:00:00",
							"idx": 1,
						}
					)
				],
			}
		)

		with (
			patch("flowire.flowire.project_costing.frappe.db.get_value", side_effect=["COMPANY-1", "USD"]),
			patch("flowire.flowire.project_costing._active_cost_rate", return_value=None),
		):
			issues = _timesheet_rate_issues(doc)

		self.assertEqual(len(issues), 1)
		self.assertIn("No active Employee Cost Rate", issues[0])

	def test_nonproject_timesheet_is_not_blocked_by_project_rate_rule(self):
		doc = frappe._dict({"time_logs": [frappe._dict({"project": None})]})

		with patch("flowire.flowire.project_costing.frappe.db.get_value") as get_value:
			issues = _timesheet_rate_issues(doc)

		self.assertEqual(issues, [])
		get_value.assert_not_called()

	def test_executive_rollup_uses_weighted_margin_and_ranks_projects(self):
		projects = [
			{
				"project": "PROJECT-1",
				"project_name": "Profitable",
				"status": "Working",
				"contract_value": 1200,
				"actual_revenue": 800,
				"total_cost": 400,
				"profit": 400,
				"margin_percentage": 50,
				"is_overdue": True,
				"warnings": ["Uncosted timesheet row"],
			},
			{
				"project": "PROJECT-2",
				"project_name": "Loss",
				"status": "Completed",
				"contract_value": 500,
				"actual_revenue": 200,
				"total_cost": 300,
				"profit": -100,
				"margin_percentage": -50,
				"is_overdue": False,
				"warnings": [],
			},
			{
				"project": "PROJECT-3",
				"project_name": "Cancelled",
				"status": "Cancelled",
				"contract_value": 0,
				"actual_revenue": 0,
				"total_cost": 0,
				"profit": 0,
				"margin_percentage": None,
				"is_overdue": False,
				"warnings": [],
			},
		]

		summary = _aggregate_executive_projects(projects)

		self.assertEqual(summary["total_projects"], 3)
		self.assertEqual(summary["active_projects"], 1)
		self.assertEqual(summary["completed_projects"], 1)
		self.assertEqual(summary["overdue_projects"], 1)
		self.assertEqual(summary["total_contract_value"], 1700)
		self.assertEqual(summary["total_revenue"], 1000)
		self.assertEqual(summary["total_cost"], 700)
		self.assertEqual(summary["total_profit"], 300)
		self.assertEqual(summary["average_margin_percentage"], 30)
		self.assertEqual(summary["top_profitable_projects"][0]["project"], "PROJECT-1")
		self.assertEqual(summary["projects_running_at_loss"][0]["project"], "PROJECT-2")
		self.assertEqual(summary["project_warnings"][0]["project"], "PROJECT-1")

	def test_executive_utilization_is_unknown_when_any_employee_capacity_is_missing(self):
		employees = [
			frappe._dict(
				{
					"name": "EMPLOYEE-1",
					"company": "COMPANY-1",
					"holiday_list": "HOLIDAY-LIST-1",
					"date_of_joining": "2026-01-01",
				}
			),
			frappe._dict(
				{
					"name": "EMPLOYEE-2",
					"company": "COMPANY-1",
					"holiday_list": "HOLIDAY-LIST-2",
					"date_of_joining": "2026-01-01",
				}
			),
		]

		with (
			patch("flowire.flowire.project_costing.frappe.has_permission", return_value=True),
			patch(
				"flowire.flowire.project_costing.frappe.get_meta",
				return_value=frappe._dict({"fields": [frappe._dict({"fieldname": "relieving_date"})]}),
			),
			patch("flowire.flowire.project_costing.frappe.get_list", return_value=employees),
			patch(
				"flowire.flowire.project_costing.frappe.db.sql",
				return_value=[
					frappe._dict({"employee": "EMPLOYEE-1", "actual_hours": 12}),
					frappe._dict({"employee": "EMPLOYEE-2", "actual_hours": 4}),
				],
			),
			patch(
				"flowire.flowire.project_costing._employee_calendar",
				side_effect=[{"calendar": "known"}, None],
			),
			patch(
				"flowire.flowire.project_costing._calendar_capacity",
				side_effect=[80, None],
			),
		):
			summary = _executive_employee_utilization(
				"COMPANY-1",
				date(2026, 1, 1),
				date(2026, 1, 31),
			)

		self.assertEqual(summary["employee_count"], 2)
		self.assertEqual(summary["employees_with_timesheets"], 2)
		self.assertEqual(summary["actual_hours"], 16)
		self.assertIsNone(summary["available_hours"])
		self.assertIsNone(summary["utilization_percentage"])
		self.assertEqual(summary["employees_missing_capacity"], 1)
		self.assertTrue(summary["permitted"])

	def test_executive_utilization_degrades_when_employee_read_is_denied(self):
		with (
			patch("flowire.flowire.project_costing.frappe.has_permission", return_value=False),
			patch("flowire.flowire.project_costing.frappe.get_list") as get_list,
		):
			summary = _executive_employee_utilization(
				"COMPANY-1",
				date(2026, 11, 1),
				date(2026, 11, 30),
			)

		self.assertFalse(summary["permitted"])
		self.assertIsNone(summary["utilization_percentage"])
		self.assertIsNone(summary["available_hours"])
		self.assertFalse(summary["capacity_complete"])
		self.assertEqual(summary["employee_count"], 0)
		self.assertEqual(summary["actual_hours"], 0)
		self.assertEqual(len(summary["warnings"]), 1)
		self.assertIn("do not have permission to read Employee", summary["warnings"][0])
		# Employee records must not be read at all when permission is denied.
		get_list.assert_not_called()

	def test_executive_summary_uses_company_projects_and_selected_utilization_period(self):
		project_summaries = [
			{
				"project": "PROJECT-1",
				"project_name": "Project One",
				"status": "Working",
				"contract_value": 1000,
				"actual_revenue": 500,
				"total_cost": 300,
				"profit": 200,
				"warnings": [],
			},
			{
				"project": "PROJECT-2",
				"project_name": "Project Two",
				"status": "Completed",
				"contract_value": 800,
				"actual_revenue": 400,
				"total_cost": 450,
				"profit": -50,
				"warnings": [],
			},
		]

		with (
			patch("flowire.flowire.project_costing._require_roles"),
			patch("flowire.flowire.project_costing._require_hrms"),
			patch("flowire.flowire.project_costing.today", return_value="2026-11-17"),
			patch("flowire.flowire.project_costing.frappe.db.exists", return_value=True),
			patch("flowire.flowire.project_costing.frappe.has_permission", return_value=True),
			patch(
				"flowire.flowire.project_costing.frappe.db.get_value",
				return_value="USD",
			),
			patch(
				"flowire.flowire.project_costing.frappe.get_list",
				return_value=[
					frappe._dict({"name": "PROJECT-1"}),
					frappe._dict({"name": "PROJECT-2"}),
				],
			) as get_list,
			patch(
				"flowire.flowire.project_costing.get_project_financials",
				side_effect=project_summaries,
			) as get_project_financials,
			patch(
				"flowire.flowire.project_costing._executive_employee_utilization",
				return_value={"utilization_percentage": 25},
			) as employee_utilization,
		):
			summary = get_executive_summary(
				"COMPANY-1",
				"2026-11-01",
				"2026-11-17",
			)

		get_list.assert_called_once_with(
			"Project",
			filters={"company": "COMPANY-1"},
			fields=["name"],
			order_by="name asc",
			limit_page_length=0,
		)
		get_project_financials.assert_any_call("PROJECT-1")
		get_project_financials.assert_any_call("PROJECT-2")
		employee_utilization.assert_called_once_with(
			"COMPANY-1",
			date(2026, 11, 1),
			date(2026, 11, 17),
		)
		self.assertEqual(summary["currency"], "USD")
		self.assertEqual(summary["total_projects"], 2)
		self.assertEqual(summary["total_profit"], 150)
		self.assertEqual(summary["employee_utilization"]["utilization_percentage"], 25)
