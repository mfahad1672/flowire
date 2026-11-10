"""orphans.py — find customizations that exist ONLY in the database.

The question it answers: "if I built a fresh site from `install-app erpnext`
+ `install-app flowire`, what would be missing?"

Classification per record:
  in app      module = 'Flowire'            -> in files/git, arrives automatically
  system      is_system_generated = 1       -> ERPNext created it itself; not ours
  OTHER       everything else               -> created by hand/Desk/frontend.
                                               This is what a fresh site loses.

Read-only. Never prints secrets.

    docker cp tools/orphans.py flowire-frappe-backend:/tmp/
    docker exec --user frappe flowire-frappe-backend bash -lc \
        "cd frappe-bench && python3 /tmp/orphans.py flowire.local"
"""

import subprocess
import sys

# (label, table, has_is_system_generated)
CHECKS = [
    ("Custom Field",     "tabCustom Field",    True),
    ("Property Setter",  "tabProperty Setter", True),
    ("Client Script",    "tabClient Script",   False),
    ("Server Script",    "tabServer Script",   False),
    ("Print Format",     "tabPrint Format",    False),
    ("Report",           "tabReport",          False),
    ("Notification",     "tabNotification",    False),
    ("Email Template",   "tabEmail Template",  False),
    ("Workflow",         "tabWorkflow",        False),
    ("Web Form",         "tabWeb Form",        False),
    ("Assignment Rule",  "tabAssignment Rule", False),
]


def count(site: str, table: str, where: str = "") -> int | None:
    sql = f"select count(*) from `{table}`" + (f" where {where}" if where else "")
    try:
        proc = subprocess.run(
            ["bench", "--site", site, "mariadb", "-e", sql],
            capture_output=True, text=True, timeout=90, check=False,
        )
    except Exception:  # noqa: BLE001
        return None
    if proc.returncode != 0:
        return None
    for ln in reversed([x.strip() for x in proc.stdout.splitlines() if x.strip()]):
        if ln.isdigit():
            return int(ln)
    return None


def classify(site: str, table: str, has_flag: bool):
    """Return (total, in_app, system, other) — any element may be None."""
    total = count(site, table)
    if total is None:
        return None, None, None, None
    owned = count(site, table, "module = 'Flowire'") or 0

    if has_flag:
        system = count(site, table, "IFNULL(is_system_generated,0) = 1") or 0
        # Neither app-owned nor ERPNext's own => hand-made, DB-only.
        other = count(
            site, table,
            "IFNULL(is_system_generated,0) = 0 AND IFNULL(module,'') <> 'Flowire'",
        )
    else:
        system = 0
        other = count(site, table, "IFNULL(module,'') = ''")

    return total, owned, system, (other or 0)


def rows(site: str, sql: str) -> list[str]:
    """Run a query and return its data lines (header stripped)."""
    try:
        proc = subprocess.run(
            ["bench", "--site", site, "mariadb", "-e", sql],
            capture_output=True, text=True, timeout=90, check=False,
        )
    except Exception:  # noqa: BLE001
        return []
    if proc.returncode != 0:
        return []
    out = [ln.rstrip() for ln in proc.stdout.splitlines() if ln.strip()]
    return out[1:] if out else []


# Queries for `--list`: exactly the records counted as OTHER above.
LIST_QUERIES = [
    ("Custom Field",
     "select name, dt, fieldname from `tabCustom Field` "
     "where IFNULL(is_system_generated,0)=0 AND IFNULL(module,'')<>'Flowire' order by dt"),
    ("Property Setter",
     "select name, doc_type, field_name, property from `tabProperty Setter` "
     "where IFNULL(is_system_generated,0)=0 AND IFNULL(module,'')<>'Flowire'"),
    ("Server Script",
     "select name, reference_doctype, disabled from `tabServer Script` "
     "where IFNULL(module,'')=''"),
    ("Print Format",
     "select name, doc_type from `tabPrint Format` where IFNULL(module,'')=''"),
    ("Notification",
     "select name, document_type, enabled from `tabNotification` "
     "where IFNULL(module,'')=''"),
    ("DocType custom=1",
     "select name, module from `tabDocType` where custom=1"),
]


def print_list(site: str) -> None:
    print()
    print("=" * 78)
    print("THE RECORDS THEMSELVES")
    print("=" * 78)
    for label, sql in LIST_QUERIES:
        data = rows(site, sql)
        print(f"\n-- {label} ({len(data)}) --")
        if not data:
            print("   (none)")
            continue
        for line in data:
            print(f"   {line}")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    site = args[0] if args else "flowire.local"
    want_list = "--list" in sys.argv

    print("=" * 78)
    print(f"SEPARATION AUDIT — is every customization owned by the app?   [{site}]")
    print("=" * 78)
    print()
    print(f"{'what':19s} {'total':>6s} {'in app':>7s} {'system':>7s} {'OTHER':>6s}  verdict")
    print("-" * 78)

    review = []
    for label, table, has_flag in CHECKS:
        total, owned, system, other = classify(site, table, has_flag)
        if total is None:
            print(f"{label:19s} {'n/a':>6s}")
            continue
        if other and other > 0:
            verdict = "REVIEW"
            review.append((label, other))
        else:
            verdict = "clean"
        print(f"{label:19s} {total:>6d} {owned:>7d} {system:>7d} {other:>6d}  {verdict}")

    # DocTypes created in the database rather than shipped by an app.
    dt_custom = count(site, "tabDocType", "custom = 1")
    dt_app = count(site, "tabDocType", "module = 'Flowire' AND IFNULL(custom,0) = 0")
    if dt_custom is not None:
        verdict = "REVIEW" if dt_custom else "clean"
        if dt_custom:
            review.append(("DocType custom=1", dt_custom))
        print(f"{'DocType custom=1':19s} {dt_custom:>6d} {(dt_app or 0):>7d} {0:>7d} "
              f"{dt_custom:>6d}  {verdict}")

    print("-" * 78)
    print()
    print("  'in app' = module=Flowire          -> ships with install-app flowire")
    print("  'system' = is_system_generated=1   -> ERPNext made it itself, ignore")
    print("  'OTHER'  = hand/Desk/frontend-made -> a fresh site LOSES it")
    print()

    if not review:
        print("  RESULT: nothing outside the app. Separation is complete.")
    else:
        print("  RESULT: these need a decision —")
        for label, n in review:
            print(f"          {label:22s} {n} record(s)")
        print()
        print("  For each: either move it into the app (fixtures / code / patch),")
        print("  or confirm it is stock ERPNext and safe to drop from the list.")

    if want_list:
        print_list(site)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
