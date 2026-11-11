"""v16 ownership probe — which app owns every CRM customization on a site.

Why: `bench update` replaces apps/frappe and apps/erpnext wholesale. Anything that lives in the
database but not in an app (a Custom Field with a blank module, a doctype a setup script created)
survives today's site and disappears on a fresh one. This prints, per doctype, how many Custom Fields
belong to `flowire`, how many belong to nobody, and the option lists that must not change.

READ-ONLY. Two ways to run:

    bench --site <site> console < scripts/v16-probe.py
    python3 scripts/v16-probe.py <site> [--dump]

Exit code 1 when an invariant fails, so it can gate a phase (R-23.3).
"""

import sys

import frappe

CRM_DOCTYPES = ("Lead", "Opportunity", "Prospect", "Company Bidder", "EM Banks")
STATUS_FIELDS = (
    ("Lead", "custom_lead_status"),
    ("Opportunity", "custom_opportunity_status"),
    ("Opportunity", "custom_stage_1"),
    ("Opportunity", "custom_status_pendingreleased"),
    ("Opportunity", "custom_pg_status"),
)
OWNER_MODULE = "Flowire"


def boot(site=None):
    """Initialise frappe only when the caller (bench console) has not already done it."""
    if getattr(frappe.local, "site", None):
        return
    if not site:
        print("usage: python3 v16-probe.py <site>   (or run it through `bench console`)")
        raise SystemExit(2)
    frappe.init(site=site, sites_path=".")
    frappe.connect()


def option_source(doctype, fieldname):
    """Options for a field whether it is a Custom Field (customized) or a stock DocField."""
    options = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname}, "options")
    if options is None:
        options = frappe.db.get_value("DocField", {"parent": doctype, "fieldname": fieldname}, "options")
    return options


def report():
    """Print the ownership table; return the list of invariant failures."""
    failures = []

    for doctype in CRM_DOCTYPES + ("Lead Source", "Sales Stage"):
        row = frappe.db.get_value("DocType", doctype, ["module", "custom", "istable"], as_dict=True)
        if row is None:
            print(f"DOCTYPE {doctype:<16} MISSING")
            failures.append(f"{doctype} does not exist")
            continue
        print(f"DOCTYPE {doctype:<16} module={row.module or '-':<10} custom={row.custom}")

    for doctype in CRM_DOCTYPES:
        total = frappe.db.count("Custom Field", {"dt": doctype})
        ours = frappe.db.count("Custom Field", {"dt": doctype, "module": OWNER_MODULE})
        print(f"CF      {doctype:<16} total={total:<3} {OWNER_MODULE}={ours:<3} unowned={total - ours}")
        if total != ours:
            unowned = frappe.get_all(
                "Custom Field",
                filters={"dt": doctype, "module": ("not in", [OWNER_MODULE])},
                fields=["fieldname"],
                order_by="fieldname asc",
            )
            names = ", ".join(row.fieldname for row in unowned)
            print(f"        unowned fields: {names}")
            failures.append(f"{doctype}: {total - ours} custom field(s) not owned by {OWNER_MODULE}")

    setters = frappe.db.count("Property Setter", {"module": OWNER_MODULE})
    perms = frappe.db.count("Custom DocPerm", {"parent": ("in", list(CRM_DOCTYPES))})
    print(f"PSETTER Property Setter module={OWNER_MODULE}: {setters}")
    print(f"PERM    Custom DocPerm (our parents): {perms}")
    print(f"LEADSRC Lead Source rows: {frappe.db.count('Lead Source')}")
    print(f"CORE    CRM Lead doctype present (standalone crm app): {bool(frappe.db.exists('DocType', 'CRM Lead'))}")

    enabled = frappe.db.count("Server Script", {"disabled": 0})
    print(f"SCRIPT  Server Scripts: {frappe.db.count('Server Script')} total, {enabled} enabled")
    if enabled:
        failures.append(f"{enabled} Server Script(s) enabled — behaviour must live in doc_events")

    for doctype, fieldname in STATUS_FIELDS:
        print(f"OPTIONS {doctype}.{fieldname} = {option_source(doctype, fieldname)!r}")

    print()
    if failures:
        print(f"RESULT FAIL ({len(failures)})")
        for failure in failures:
            print(f"  - {failure}")
    else:
        print("RESULT PASS — every CRM customization is owned by an app")
    return failures


def dump_fields():
    """Every Custom Field on Lead/Opportunity, for the baseline snapshot."""
    for doctype in ("Lead", "Opportunity"):
        rows = frappe.get_all(
            "Custom Field",
            filters={"dt": doctype},
            fields=["fieldname", "fieldtype", "options", "module", "label"],
            order_by="fieldname asc",
        )
        print(f"=== {doctype} custom fields ({len(rows)}) ===")
        for row in rows:
            print(f"{row.fieldname} | {row.fieldtype} | {row.options or ''} | {row.module or '-'} | {row.label}")


def main():
    site = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None
    boot(site)
    if "--dump" in sys.argv:
        dump_fields()
        return 0
    return 1 if report() else 0


if __name__ == "__main__":
    sys.exit(main())
