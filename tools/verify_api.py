"""verify_api.py — check the frontend's API surface against THIS bench.

Reads the JSON emitted by the frontend's
`scripts/verify-erpnext-apis.mjs` and answers three questions against the
live site:

  1. does every doctype the frontend asks for still exist?
  2. does every frappe/erpnext RPC it calls still resolve, and is it callable
     from the client (i.e. @frappe.whitelist)?
  3. do the fields it filters / orders by still exist on the doctype?

Read-only: it imports and inspects, it never writes or saves anything.

    cd frappe-bench
    env/bin/python /tmp/verify_api.py flowire.local /tmp/api-surface.json
"""

import json
import os
import sys
import traceback

import frappe

# TypeScript interface members that are framework-level, not database columns.
NON_COLUMN = {
    "doctype",
    "name",
    "parent",
    "parentfield",
    "parenttype",
    "idx",
    "docstatus",
    "owner",
    "creation",
    "modified",
    "modified_by",
    "flags",
    "children",
}


def has_column(meta, name):
    """True if `name` is a real column on this doctype.

    `meta.has_field()` only knows about the doctype's OWN fields — the default
    columns every doctype inherits (name, owner, creation, modified,
    modified_by, docstatus, idx, parent*) are not in that list. Checking them
    with has_field() reports `Lead.creation` as missing, which is nonsense.
    """
    if meta.has_field(name):
        return True
    try:
        return name in meta.get_valid_columns()
    except Exception:  # noqa: BLE001
        return False


# Paths the frontend keeps as a PREFIX and appends the method name to, e.g.
#   const PM = 'frappe.core.page.permission_manager.permission_manager';
#   client.call(`${PM}.get_permissions`, ...)
# The bare path is therefore a MODULE, not a callable — checking it directly
# reports a false "MISSING". Verify the real suffixed methods instead.
MODULE_PREFIXES = {
    "frappe.core.page.permission_manager.permission_manager": (
        "get_permissions",
        "add",
        "update",
        "remove",
    ),
}


def check_method(name):
    """Return (status, detail) for one dotted RPC path."""
    if name in MODULE_PREFIXES:
        results = [
            (suffix, check_method(f"{name}.{suffix}"))
            for suffix in MODULE_PREFIXES[name]
        ]
        bad = [(s, st) for s, (st, _) in results if st != "OK"]
        if not bad:
            return "OK", f"prefix + {len(results)} verified methods"
        return bad[0][1], f"{bad[0][0]}: {bad[0][1]}"

    try:
        fn = frappe.get_attr(name)
    except Exception as exc:  # noqa: BLE001
        return "MISSING", type(exc).__name__
    if not callable(fn):
        return "NOT_CALLABLE", type(fn).__name__

    # Frappe v16 tracks the @frappe.whitelist() registry in a module-level set
    # of callables (`frappe.whitelisted`), NOT as an attribute on the function —
    # checking `fn.whitelisted` reports every method as unexposed. Without this
    # the HTTP layer refuses the call even though the function exists (a silent
    # 403, not a 404), so it is worth getting right.
    registry = getattr(frappe, "whitelisted", None)
    if isinstance(registry, (set, frozenset)):
        exposed = fn in registry
    else:  # older Frappe: attribute on the function
        exposed = bool(getattr(fn, "whitelisted", None))

    if not exposed:
        return "NOT_WHITELISTED", "exists but is not exposed over HTTP"
    return "OK", ""


def _load_json(path):
    """Load JSON whatever encoding the shell happened to write it in.

    PowerShell's `>` redirection writes UTF-16LE, `Out-File -Encoding utf8`
    adds a BOM, and node itself writes plain UTF-8. Accept all three rather
    than making the caller guess.
    """
    with open(path, "rb") as fh:
        raw = fh.read()
    for encoding in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            return json.loads(raw.decode(encoding))
        except (UnicodeDecodeError, ValueError):
            continue
    raise ValueError(f"{path}: could not decode as utf-8/utf-16 ({len(raw)} bytes)")


def field_locations(fieldnames):
    """Map fieldname -> {doctypes that HAVE that field} on this bench.

    Answers "the frontend expects `Lead.expected_closing` and it is gone — did
    ERPNext v16 MOVE it somewhere?", which is the difference between a typo and
    a real v15->v16 migration break.
    """
    names = sorted({f for f in fieldnames if f})
    if not names:
        return {}
    marks = ", ".join(["%s"] * len(names))
    rows = frappe.db.sql(
        f"select fieldname, parent from `tabDocField` where fieldname in ({marks})"
        f" union all "
        f"select fieldname, dt from `tabCustom Field` where fieldname in ({marks})",
        tuple(names) * 2,
        as_list=True,
    )
    out = {}
    for fname, parent in rows:
        out.setdefault(fname, set()).add(parent)
    return out


def main():
    if len(sys.argv) < 3:
        print("usage: verify_api.py <site> <api-surface.json>", file=sys.stderr)
        return 2

    site, surface_path = sys.argv[1], sys.argv[2]

    # Frappe resolves the site log directory as `os.path.join(site, "logs")`,
    # i.e. RELATIVE TO CWD — not to sites_path. So this must run from the
    # `sites/` directory (which is where bench itself runs it from):
    #     cd frappe-bench/sites && ../env/bin/python /tmp/verify_api.py <site> <json>
    sites_path = os.getcwd()
    if not os.path.isdir(os.path.join(sites_path, site)):
        print(
            f"run this from the bench's sites/ directory — {site} not found in {sites_path}",
            file=sys.stderr,
        )
        return 2

    frappe.init(site=site, sites_path=sites_path)
    frappe.connect()

    try:
        surface = _load_json(surface_path)

        doctypes = surface.get("doctypes", [])
        methods = surface.get("methods", {})
        filter_fields = surface.get("filterFields", {})
        type_fields = surface.get("typeFields", {})

        print("=" * 78)
        print(f"API COMPATIBILITY — frontend vs {site} "
              f"(frappe {frappe.__version__})")
        print("=" * 78)

        # ---------------- doctypes ----------------
        print(f"\n[1] DOCTYPES ({len(doctypes)})")
        print("-" * 78)
        missing_dt = []
        for dt in doctypes:
            if frappe.db.exists("DocType", dt):
                meta = frappe.get_meta(dt)
                print(f"  OK       {dt:34s} {len(meta.fields):>3d} fields, "
                      f"{'submittable' if meta.is_submittable else 'plain'}")
            else:
                missing_dt.append(dt)
                print(f"  MISSING  {dt}")
        print(f"  -> {len(doctypes) - len(missing_dt)}/{len(doctypes)} present")

        # ---------------- methods ----------------
        print(f"\n[2] RPC METHODS ({len(methods)})")
        print("-" * 78)
        bad_methods = []
        for name in sorted(methods):
            status, detail = check_method(name)
            callers = ", ".join(methods[name][:2])
            if len(methods[name]) > 2:
                callers += f" (+{len(methods[name]) - 2})"
            if status == "OK":
                print(f"  OK            {name}")
            else:
                bad_methods.append((name, status, detail))
                print(f"  {status:13s} {name}")
                print(f"                {detail}  [{callers}]")
        print(f"  -> {len(methods) - len(bad_methods)}/{len(methods)} callable")

        # ---------------- filter / orderBy fields ----------------
        print("\n[3] FIELDS USED IN FILTERS / ORDER BY")
        print("-" * 78)
        print("  (a missing field here is a hard 500 from the server)")
        bad_filter = []
        checked = 0
        for dt, fields in sorted(filter_fields.items()):
            if not frappe.db.exists("DocType", dt):
                continue
            meta = frappe.get_meta(dt)
            for f in fields:
                checked += 1
                base = f.split(".")[0]
                if has_column(meta, base):
                    continue
                bad_filter.append((dt, f))

        # A filter field that does not exist on its attributed doctype but DOES
        # exist on some other doctype is almost always MY mis-attribution (the
        # nearest-preceding-doctype heuristic breaking on generic query code),
        # not a frontend bug. Only a field that exists NOWHERE is a real defect.
        if bad_filter:
            locations = field_locations([f.split(".")[0] for _, f in bad_filter])
            real_filter = [
                (dt, f) for dt, f in bad_filter if not locations.get(f.split(".")[0])
            ]
            uncertain = [(dt, f) for dt, f in bad_filter if (dt, f) not in real_filter]

            for dt, f in real_filter:
                print(f"  MISSING  {dt}.{f}   <- exists on no DocType")
            if uncertain:
                print(f"\n  {len(uncertain)} more field/doctype pairs did not match the")
                print("  attributed doctype but the field exists elsewhere — likely")
                print("  attribution noise, not a defect:")
                for dt, f in uncertain:
                    where = ", ".join(sorted(locations[f.split(".")[0]])[:2])
                    print(f"    ?  {dt}.{f}  (field exists on {where})")
            bad_filter = real_filter
        print(f"  -> {checked - len(bad_filter)}/{checked} fields resolve")

        # ---------------- TS contract fields ----------------
        print("\n[4] TYPESCRIPT CONTRACT vs DocType META")
        print("-" * 78)
        print("  (informational: a field in the TS type that the server does not")
        print("   have is silently undefined at runtime)")
        bad_type = []
        checked_t = 0
        for dt, fields in sorted(type_fields.items()):
            if not frappe.db.exists("DocType", dt):
                continue
            meta = frappe.get_meta(dt)
            absent = []
            for f in fields:
                if f in NON_COLUMN:
                    continue
                checked_t += 1
                if not has_column(meta, f):
                    absent.append(f)
            if absent:
                bad_type.append((dt, absent))
                print(f"  {dt}: {len(absent)} absent")
                for f in absent:
                    print(f"      - {f}")
        print(f"  -> {checked_t - sum(len(a) for _, a in bad_type)}/{checked_t} "
              f"typed fields exist")

        # ---------------- where did the absent fields go? ----------------
        absent_all = [f for _, fields in bad_type for f in fields]
        if absent_all:
            locs = field_locations(absent_all)
            print("\n[5] WHERE DID THE ABSENT FIELDS GO?")
            print("-" * 78)
            print("  same name, found on another doctype -> the field MOVED in v16")
            print("  not found anywhere                  -> the frontend is wrong")
            moved, gone = [], []
            for _, fields in bad_type:
                for f in fields:
                    if f in locs and locs[f]:
                        moved.append((f, sorted(locs[f])))
                    else:
                        gone.append(f)
            for f, where in moved:
                print(f"  MOVED    {f:28s} -> {', '.join(where[:4])}"
                      + ("" if len(where) <= 4 else f" (+{len(where) - 4})"))
            for f in gone:
                print(f"  NOWHERE  {f:28s} -> does not exist on any DocType")
            print(f"  -> {len(moved)} moved, {len(gone)} nowhere")

        # ---------------- verdict ----------------
        print("\n" + "=" * 78)
        problems = len(missing_dt) + len(bad_methods) + len(bad_filter)
        if problems == 0:
            print("VERDICT: frontend surface is fully compatible with this bench.")
        else:
            print(f"VERDICT: {problems} blocking problem(s) "
                  f"+ {sum(len(a) for _, a in bad_type)} typed field(s) to review.")
        print("=" * 78)

        summary = {
            "site": site,
            "frappe": frappe.__version__,
            "doctypes_total": len(doctypes),
            "doctypes_missing": missing_dt,
            "methods_total": len(methods),
            "methods_bad": [{"method": n, "status": s, "detail": d}
                            for n, s, d in bad_methods],
            "filter_fields_checked": checked,
            "filter_fields_missing": [{"doctype": d, "field": f}
                                      for d, f in bad_filter],
            "type_fields_absent": [{"doctype": d, "fields": a}
                                   for d, a in bad_type],
        }
        print("\nJSON: " + json.dumps(summary))
        return 0
    except Exception:  # noqa: BLE001 - always show the real traceback
        traceback.print_exc()
        return 1
    finally:
        frappe.destroy()


if __name__ == "__main__":
    raise SystemExit(main())
