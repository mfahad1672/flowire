import frappe
from frappe.model.document import Document
from frappe.utils import flt


ESTIMATE_COST_FIELDS = (
	"estimated_labor_cost",
	"estimated_purchase_cost",
	"estimated_travel_cost",
	"estimated_software_cost",
	"estimated_subcontractor_cost",
	"estimated_miscellaneous_cost",
)


def calculate_estimate_values(values: dict) -> dict:
	"""Return derived estimate totals using the cost-category inputs."""
	expense_cost = sum(flt(values.get(fieldname)) for fieldname in ESTIMATE_COST_FIELDS[2:])
	total_cost = flt(values.get("estimated_labor_cost")) + flt(
		values.get("estimated_purchase_cost")
	) + expense_cost
	revenue = flt(values.get("estimated_revenue"))
	profit = revenue - total_cost

	return {
		"estimated_expense_cost": expense_cost,
		"estimated_total_cost": total_cost,
		"expected_profit": profit,
		"expected_margin_percent": (profit / revenue * 100) if revenue else 0,
	}


class ProjectCostEstimate(Document):
	def validate(self):
		self._set_company()
		self._validate_amounts()

		for fieldname, value in calculate_estimate_values(self.as_dict()).items():
			self.set(fieldname, value)

		self._validate_approved_project_estimate()

	def _set_company(self):
		linked_company = None
		for doctype, name in (
			("Project", self.project),
			("Sales Order", self.sales_order),
			("Quotation", self.quotation),
			("Opportunity", self.opportunity),
		):
			if name and frappe.db.exists(doctype, name):
				if not any(field.fieldname == "company" for field in frappe.get_meta(doctype).fields):
					continue
				company = frappe.db.get_value(doctype, name, "company")
				if company:
					if linked_company and linked_company != company:
						frappe.throw(
							f"Linked documents do not use the same company "
							f"({linked_company} and {company})."
						)
					if self.company and self.company != company:
						frappe.throw(
							f"Company {self.company} does not match linked {doctype} {name} "
							f"({company})."
						)
					linked_company = company

		if linked_company:
			self.company = linked_company
			return
		if self.company:
			return

		frappe.throw("Company is required to calculate this estimate in a consistent currency.")

	def _validate_amounts(self):
		for fieldname in ("estimated_revenue", *ESTIMATE_COST_FIELDS):
			if flt(self.get(fieldname)) < 0:
				label = fieldname.replace("_", " ").capitalize()
				frappe.throw(f"{label} cannot be negative.")

	def _validate_approved_project_estimate(self):
		if self.status != "Approved":
			return

		for fieldname, label in (("project", "Project"), ("sales_order", "Sales Order")):
			value = self.get(fieldname)
			if not value:
				continue

			existing = frappe.db.get_value(
				"Project Cost Estimate",
				{fieldname: value, "status": "Approved"},
				"name",
			)
			if existing and existing != self.name:
				frappe.throw(f"{label} {value} already has an approved cost estimate ({existing}).")
