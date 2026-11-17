import frappe
from frappe.model.document import Document
from frappe.utils import flt


class EmployeeCostRate(Document):
	def validate(self):
		employee_company = frappe.db.get_value("Employee", self.employee, "company")
		if not employee_company:
			frappe.throw(f"Employee {self.employee} must be linked to a company.")

		if self.company and self.company != employee_company:
			frappe.throw(
				f"Company {self.company} does not match employee {self.employee}'s company "
				f"({employee_company})."
			)

		self.company = employee_company

		if flt(self.cost_rate_per_hour) <= 0:
			frappe.throw("Cost Rate Per Hour must be greater than zero.")

		if flt(self.billing_rate_per_hour) < 0:
			frappe.throw("Billing Rate Per Hour cannot be negative.")

		existing = frappe.db.get_value(
			"Employee Cost Rate",
			{
				"employee": self.employee,
				"company": self.company,
				"effective_date": self.effective_date,
			},
			"name",
		)
		if existing and existing != self.name:
			frappe.throw(
				f"Employee {self.employee} already has a cost rate effective on "
				f"{self.effective_date} ({existing})."
			)

		self._validate_rate_not_used()

	def on_trash(self):
		self._validate_rate_not_used(check_existing=True)

	def _validate_rate_not_used(self, check_existing=False):
		previous = self.get_doc_before_save()
		if not check_existing and not previous:
			return

		if (
			not check_existing
			and previous.cost_rate_per_hour == self.cost_rate_per_hour
			and previous.billing_rate_per_hour == self.billing_rate_per_hour
			and previous.effective_date == self.effective_date
			and previous.company == self.company
		):
			return

		effective_date = previous.effective_date if previous else self.effective_date
		if not frappe.db.exists("DocType", "Timesheet Detail"):
			return

		used = frappe.db.sql(
			"""
			SELECT td.name
			FROM `tabTimesheet Detail` td
			INNER JOIN `tabTimesheet` ts ON ts.name = td.parent
			WHERE ts.employee = %s
				AND ts.docstatus = 1
				AND COALESCE(td.project, '') != ''
				AND COALESCE(DATE(td.from_time), ts.start_date) >= %s
			LIMIT 1
			""",
			(self.employee, effective_date),
			as_list=True,
		)
		if used:
			frappe.throw(
				"Cost rates referenced by submitted project Timesheets cannot be changed or "
				"deleted. Add a new effective-dated rate instead."
			)
