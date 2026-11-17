import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate


class ResourceAllocation(Document):
	def validate(self):
		if flt(self.allocation_percentage) < 0 or flt(self.allocation_percentage) > 100:
			frappe.throw("Allocation Percentage must be between 0 and 100.")

		if flt(self.planned_hours) < 0:
			frappe.throw("Planned Hours cannot be negative.")

		if self.start_date and self.end_date and getdate(self.end_date) < getdate(self.start_date):
			frappe.throw("End Date cannot be earlier than Start Date.")

		self._validate_no_overlapping_allocation()

	def _validate_no_overlapping_allocation(self):
		if not self.project or not self.employee or not self.start_date:
			return

		existing = frappe.db.sql(
			"""
			SELECT name
			FROM `tabResource Allocation`
			WHERE project = %(project)s
				AND employee = %(employee)s
				AND name != %(name)s
				AND COALESCE(end_date, '9999-12-31') >= %(start_date)s
				AND COALESCE(%(end_date)s, '9999-12-31') >= start_date
			LIMIT 1
			""",
			{
				"project": self.project,
				"employee": self.employee,
				"name": self.name or "",
				"start_date": self.start_date,
				"end_date": self.end_date,
			},
			as_dict=True,
		)
		if existing:
			frappe.throw(
				f"Employee {self.employee} already has an overlapping allocation on "
				f"Project {self.project} ({existing[0].name})."
			)
