from datetime import date
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from flowire.flowire.doctype.project_cost_estimate.project_cost_estimate import (
	calculate_estimate_values,
)
from flowire.flowire.project_costing import (
	_active_cost_rate,
	_timesheet_rate_issues,
	apply_employee_cost_rates,
	calculate_available_hours,
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
