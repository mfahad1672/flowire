"""Ownership tests — the invariants ``tools/v16-probe.py`` reports on.

The probe is the gate; these are the same invariants expressed as assertions so a
regression fails in CI (`bench --site <site> run-tests --app flowire`) instead of
being spotted by eye in a probe dump.

v16 conventions: :class:`frappe.tests.IntegrationTestCase` (not the removed
``unittest`` helpers), and no test writes outside a rolled-back transaction.
"""

import json
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase

MODULE = "Flowire"

# The doctypes the frontend depends on; the probe asserts the same list.
CRM_DOCTYPES = ("Lead", "Opportunity", "Prospect", "Company Bidder", "EM Banks")

# Option lists that must not drift: the UI renders a status by name.
EXPECTED_STATUS_OPTIONS = {
	"Lead.custom_lead_status": "New\nContacted\nNurturing\nQualified\nUnqualified\nConverted\nLost",
	"Opportunity.custom_opportunity_status": "New\nOpen\nIn Review\nConverted\nWon\nLost",
	"Opportunity.custom_stage_1": None,
	"Opportunity.custom_status_pendingreleased": "Not Required\nPending\nSubmitted\nReleased",
	"Opportunity.custom_pg_status": "Not Required\nPending\nSubmitted\nReleased",
}

LEAD_SOURCE_ROWS = 14


class TestLeadSourceOwnership(IntegrationTestCase):
	def test_lead_source_is_owned_by_the_app(self):
		row = frappe.db.get_value("DocType", "Lead Source", ["custom", "module"], as_dict=True)
		self.assertIsNotNone(row, "Lead Source does not exist on this site")
		self.assertEqual(row.custom, 0, "Lead Source is still a custom (database-only) DocType")
		self.assertEqual(row.module, MODULE)

	def test_lead_source_definition_ships_as_a_file(self):
		# A file in the app is what makes the DocType survive `bench update`; without one
		# `remove_orphan_doctypes()` is entitled to delete it and its table.
		path = Path(frappe.get_app_path("flowire")) / "flowire" / "doctype" / "lead_source"
		self.assertTrue((path / "lead_source.json").is_file(), f"missing doctype file under {path}")

	def test_lead_source_rows_survived(self):
		self.assertEqual(
			frappe.db.count("Lead Source"),
			LEAD_SOURCE_ROWS,
			"the option list behind Lead.source / Opportunity.source lost rows",
		)

	def test_lead_source_rows_ship_as_a_fixture(self):
		path = Path(frappe.get_app_path("flowire")) / "fixtures" / "lead_source.json"
		self.assertTrue(path.is_file(), "flowire/fixtures/lead_source.json is missing")
		rows = json.loads(path.read_text(encoding="utf-8"))
		self.assertEqual(len(rows), LEAD_SOURCE_ROWS)
		self.assertTrue(all(row["doctype"] == "Lead Source" for row in rows))


class TestNothingIsUnowned(IntegrationTestCase):
	def test_every_custom_field_on_our_doctypes_is_ours(self):
		unowned = {}
		for doctype in CRM_DOCTYPES:
			rows = frappe.get_all(
				"Custom Field",
				filters={"dt": doctype, "module": ("not in", [MODULE])},
				pluck="fieldname",
				limit_page_length=0,
			)
			if rows:
				unowned[doctype] = rows
		self.assertEqual(unowned, {}, f"Custom Field(s) not owned by {MODULE}: {unowned}")

	def test_every_app_doctype_has_a_definition_file(self):
		"""Guards the one way this app could lose data: an orphan-reaped DocType."""
		app_path = Path(frappe.get_app_path("flowire"))
		missing = []
		for name in frappe.get_all(
			"DocType", filters={"module": MODULE, "custom": 0}, pluck="name", limit_page_length=0
		):
			folder = name.lower().replace(" ", "_")
			if not (app_path / "flowire" / "doctype" / folder / f"{folder}.json").is_file():
				missing.append(name)
		self.assertEqual(missing, [], f"DocType(s) claimed by {MODULE} with no file in the app: {missing}")

	def test_behaviour_lives_in_doc_events_not_server_scripts(self):
		enabled = frappe.get_all(
			"Server Script", filters={"disabled": 0}, pluck="name", limit_page_length=0
		)
		self.assertEqual(enabled, [], f"Server Script(s) enabled — port them to doc_events: {enabled}")

	def test_status_options_are_unchanged(self):
		for path, expected in EXPECTED_STATUS_OPTIONS.items():
			doctype, fieldname = path.split(".", 1)
			value = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname}, "options")
			if value is None:
				value = frappe.db.get_value("DocField", {"parent": doctype, "fieldname": fieldname}, "options")
			self.assertEqual(value, expected, f"{path} options drifted")


class TestFixturesAndSchema(IntegrationTestCase):
	def test_fixtures_cover_lead_source_and_the_permission_parents(self):
		from flowire import hooks

		exported = {entry["dt"] for entry in hooks.fixtures}
		self.assertIn("Lead Source", exported)
		self.assertIn("Custom Field", exported)
		self.assertIn("Property Setter", exported)

		perm_entry = next(entry for entry in hooks.fixtures if entry["dt"] == "Custom DocPerm")
		parents = next(
			condition[2] for condition in perm_entry["filters"] if condition[0] == "parent"
		)
		self.assertEqual(set(CRM_DOCTYPES) - set(parents), set())

	def test_version_dependent_fields_are_not_exported_as_fixtures(self):
		"""They are created per site by ``flowire.setup.schema`` (see its docstring)."""
		from flowire import hooks

		entry = next(e for e in hooks.fixtures if e["dt"] == "Custom Field")
		excluded = next(condition[2] for condition in entry["filters"] if condition[0] == "name")
		self.assertEqual(set(excluded), set(hooks.VERSION_DEPENDENT_FIELDS))

	def test_schema_sync_is_idempotent(self):
		from flowire.setup import schema

		self.assertEqual(schema.sync(), 0, "schema.sync() created a field on a converged site")

	def test_version_dependent_fields_exist_and_are_owned(self):
		from flowire.setup import schema

		for spec in schema.OUR_VERSION_FIELDS:
			exists = frappe.db.exists("Custom Field", {"dt": spec["dt"], "fieldname": spec["fieldname"]})
			native = frappe.db.exists("DocField", {"parent": spec["dt"], "fieldname": spec["fieldname"]})
			self.assertTrue(
				exists or native,
				f"{spec['dt']}.{spec['fieldname']} exists on neither erpnext nor this app",
			)
			if exists:
				self.assertEqual(
					frappe.db.get_value("Custom Field", exists, "module"),
					MODULE,
					f"{spec['dt']}.{spec['fieldname']} is not owned by {MODULE}",
				)
