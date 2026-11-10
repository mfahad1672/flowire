"""check_sites.py — read-only report of every site on this bench.

Run inside the bench container:

    docker cp D:/CRM/flowire/tools/check_sites.py flowire-frappe-backend:/tmp/
    docker exec --user frappe flowire-frappe-backend bash -lc \
        "cd frappe-bench && python3 /tmp/check_sites.py"

Prints, per REAL site (symlink aliases are listed but not probed):
  - the database name and whether it exists
  - installed apps
  - record counts for the doctypes the CRM actually uses

Deliberately never prints db_password, encryption_key or any other secret:
site_config.json is read for non-secret keys only.
"""

import json
import os
import subprocess
import sys

SITES_DIR = "sites"

# Doctypes worth counting — these say "is this site a real CRM or a shell?".
COUNT_DOCTYPES = [
    "Lead",
    "Opportunity",
    "Customer",
    "Quotation",
    "ToDo",
    "Communication",
    "User",
    "Company Bidder",
    "EM Banks",
]

SAFE_CONFIG_KEYS = (
    "db_name",
    "host_name",
    "developer_mode",
    "installed_apps",
    "mute_emails",
)

# `developer_mode` (and mute_emails / maintenance_mode) are normally set on the
# BENCH in sites/common_site_config.json, not per site. Reading only the site
# file reports `None` even when the bench has it enabled — so both files are
# read and the site value wins when it is actually set.
COMMON_CONFIG_KEYS = (
    "developer_mode",
    "mute_emails",
    "maintenance_mode",
    "socketio_port",
)

# `User` always has rows (Administrator, Guest) on every site ever created, so it
# must never count towards "does this site hold business data" — otherwise a
# brand-new empty site is wrongly reported as non-empty.
NON_BUSINESS_DOCTYPES = {"User"}


def classify(entry: str):
    """Return ('symlink', target) | ('site', None) | (None, None)."""
    path = os.path.join(SITES_DIR, entry)
    if os.path.islink(path):
        return "symlink", os.readlink(path)
    cfg = os.path.join(path, "site_config.json")
    if os.path.isfile(cfg):
        return "site", None
    return None, None


def read_config(site: str) -> dict:
    """Read only non-secret keys from site_config.json."""
    cfg = os.path.join(SITES_DIR, site, "site_config.json")
    try:
        with open(cfg) as fh:
            raw = json.load(fh)
    except Exception as exc:  # noqa: BLE001 - report, never crash the report
        return {"_error": str(exc)}
    return {k: raw.get(k) for k in SAFE_CONFIG_KEYS if k in raw}


def read_common_config() -> dict:
    """Bench-wide settings from sites/common_site_config.json (safe keys only)."""
    path = os.path.join(SITES_DIR, "common_site_config.json")
    try:
        with open(path) as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return {}
    except Exception:  # noqa: BLE001 - a broken bench config must not stop the report
        return {"_error": "unreadable"}
    return {k: raw.get(k) for k in COMMON_CONFIG_KEYS if k in raw}


def bench(*args: str, timeout: int = 120) -> tuple[int, str]:
    """Run a bench command, returning (exit code, combined output)."""
    cmd = ["bench"] + list(args)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def count_rows(site: str, doctype: str) -> str:
    """Row count for one doctype on one site. Returns a string for the table."""
    code, out = bench(
        "--site",
        site,
        "mariadb",
        "--skip-column-names",
        "-e",
        f"select count(*) from `tab{doctype}`",
        timeout=90,
    )
    if code != 0:
        # Doctype may not exist on this site, or mariadb subcommand unsupported.
        return "?"
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            return line
    return "?"


def main() -> int:
    if not os.path.isdir(SITES_DIR):
        print(f"not inside a bench: {SITES_DIR}/ not found", file=sys.stderr)
        return 1

    entries = sorted(os.listdir(SITES_DIR))
    real, aliases = [], []

    print("=" * 72)
    print("SITES  (bench-local, read-only report)")
    print("=" * 72)

    common = read_common_config()
    print("\n-- bench-wide (sites/common_site_config.json) --")
    if not common:
        print("  (not found)")
    else:
        for key in COMMON_CONFIG_KEYS:
            if key in common:
                print(f"  {key:18s}: {common[key]}")

    for entry in entries:
        kind, target = classify(entry)
        if kind == "symlink":
            aliases.append((entry, target))
        elif kind == "site":
            real.append(entry)

    print("\n-- symlink ALIASES (not sites; dropping one would drop its target) --")
    for name, target in aliases:
        print(f"  {name:22s} -> {target}")
    if not aliases:
        print("  (none)")

    print(f"\n-- REAL sites: {len(real)} --")

    summary = []
    for site in real:
        cfg = read_config(site)
        print(f"\n{'=' * 72}")
        print(f"SITE: {site}")
        print(f"{'=' * 72}")
        if "_error" in cfg:
            print(f"  site_config.json unreadable: {cfg['_error']}")
            continue

        print(f"  db_name         : {cfg.get('db_name')}")
        print(f"  host_name       : {cfg.get('host_name')}")
        # Fall back to the bench-wide value: developer_mode is normally set on
        # the bench, so the site file alone would misleadingly print None.
        dev_site = cfg.get("developer_mode")
        dev_eff = dev_site if dev_site is not None else common.get("developer_mode")
        source = "site" if dev_site is not None else "bench"
        print(f"  developer_mode  : {dev_eff}  (from {source})")

        # Non-prod sites MUST mute email, otherwise a restored Notification can
        # reach real users. Worth surfacing loudly rather than quietly omitting.
        mute_site = cfg.get("mute_emails")
        mute_eff = mute_site if mute_site is not None else common.get("mute_emails")
        if mute_eff in (1, True, "1"):
            print("  mute_emails     : ON")
        else:
            print("  mute_emails     : OFF  <-- emails CAN be sent from this site")

        code, out = bench("--site", site, "list-apps", timeout=120)
        if code == 0:
            apps = [ln.split()[0] for ln in out.splitlines() if ln.strip()]
            print(f"  apps            : {', '.join(apps)}")
        else:
            apps = []
            print(f"  apps            : ERROR ({out.strip()[:120]})")

        print("\n  record counts:")
        counts = {}
        for dt in COUNT_DOCTYPES:
            n = count_rows(site, dt)
            counts[dt] = n
            print(f"    {dt:18s} {n:>8s}")

        summary.append((site, cfg.get("db_name"), apps, counts))

    print(f"\n{'=' * 72}")
    print("SUMMARY")
    print(f"{'=' * 72}")
    for site, db, apps, counts in summary:
        business = {
            k: int(v)
            for k, v in counts.items()
            if k not in NON_BUSINESS_DOCTYPES and v.isdigit()
        }
        total = sum(business.values())
        tag = f"HAS DATA ({total} rows)" if total > 0 else "empty / shell — safe to drop"
        print(f"  {site:22s} db={db}  apps={len(apps)}  [{tag}]")

    # Machine-readable block for programmatic use.
    print("\nJSON:", json.dumps(
        [{"site": s, "db": d, "apps": a, "counts": c} for s, d, a, c in summary]
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
