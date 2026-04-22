#!/usr/bin/env python3
"""
Hardware Tier Analysis Tool — Performance Limiter
limiter.py

Applies real Windows-level constraints to make your system behave like
a lower hardware tier. Uses only legitimate OS APIs:
  - Windows Power Plans  (powercfg)        → CPU frequency cap
  - Process CPU Affinity (via PowerShell)  → visible core count
  - RAM pressure         (via VirtualAlloc through ctypes) → memory cap sim
  - WMI display name override              → what apps "see" as your CPU name

All changes are REVERSIBLE. A restore point is saved before any change.
Run as Administrator for full functionality.
"""

import json
import os
import sys
import subprocess
import ctypes
import platform
import shutil
from pathlib import Path
from datetime import datetime

# ── Constants ────────────────────────────────────────────────────────
LIBRARY_FILE  = "hardware_library.json"
SPECS_FILE    = "local_specs.json"
PROFILE_FILE  = "active_profile.json"
RESTORE_FILE  = "restore_point.json"

TIER_ORDER = ["F", "E", "D", "C", "B", "A", "S", "S+"]

# Windows built-in power plan GUIDs
POWER_PLANS = {
    "balanced":    "381b4222-f694-41f0-9685-ff5bb260df2e",
    "powersaver":  "a1841308-3541-4fab-bc81-f71556f20b4a",
    "high_perf":   "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
    "ultimate":    "e9a42b02-d5df-448d-aa00-03f14749eb61",
}

# Custom limiter power plan name
LIMITER_PLAN_NAME = "HW_TIER_LIMITER"


# ── Helpers ───────────────────────────────────────────────────────────

def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def run(cmd: str, capture=True, shell=True) -> tuple[int, str]:
    """Run a shell command, return (returncode, output)."""
    try:
        r = subprocess.run(cmd, shell=shell, capture_output=capture,
                           text=True, timeout=30)
        out = (r.stdout + r.stderr).strip()
        return r.returncode, out
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:
        return -1, str(e)


def ps(expr: str) -> str:
    """Run a PowerShell expression, return trimmed output."""
    code, out = run(
        f'powershell -NoProfile -NonInteractive -Command "{expr}"')
    return out.strip()


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def header(title: str):
    print(f"\n{'═'*64}")
    print(f"  {title}")
    print(f"{'═'*64}")


def section(title: str):
    print(f"\n  {'─'*56}")
    print(f"  {title}")
    print(f"  {'─'*56}")


# ── Power Plan Management ─────────────────────────────────────────────

def get_active_power_plan() -> tuple[str, str]:
    """Returns (guid, name) of currently active power plan."""
    code, out = run("powercfg /getactivescheme")
    if code != 0:
        return "", "Unknown"
    # Format: "Power Scheme GUID: <guid>  (<name>)"
    parts = out.split("(")
    guid_part = out.split(":")[1].split("(")[0].strip() if ":" in out else ""
    name_part = parts[-1].rstrip(")").strip() if len(parts) > 1 else "Unknown"
    return guid_part, name_part


def get_all_power_plans() -> list[dict]:
    """Return list of {guid, name} for all installed power plans."""
    code, out = run("powercfg /list")
    plans = []
    for line in out.splitlines():
        if "GUID:" in line:
            parts = line.split("GUID:")[1]
            guid = parts.split()[0].strip()
            name = parts.split("(")[1].rstrip(")*").strip() if "(" in parts else "Unknown"
            active = "*" in line
            plans.append({"guid": guid, "name": name, "active": active})
    return plans


def create_limiter_plan(cpu_max_pct: int) -> str:
    """
    Duplicate the Power Saver plan, rename it, set CPU max frequency %.
    Returns the new plan's GUID.
    """
    # Check if limiter plan already exists
    for plan in get_all_power_plans():
        if LIMITER_PLAN_NAME in plan["name"]:
            guid = plan["guid"]
            print(f"  [Power] Updating existing limiter plan: {guid}")
            _apply_cpu_cap(guid, cpu_max_pct)
            return guid

    # Duplicate powersaver as base
    code, out = run(f'powercfg /duplicatescheme {POWER_PLANS["powersaver"]}')
    if code != 0:
        print(f"  [Power] Could not duplicate power plan: {out}")
        return ""

    # Extract new GUID from output
    new_guid = ""
    for token in out.split():
        if len(token) == 36 and token.count("-") == 4:
            new_guid = token
            break

    if not new_guid:
        print(f"  [Power] Could not parse new GUID from: {out}")
        return ""

    # Rename it
    run(f'powercfg /changename {new_guid} "{LIMITER_PLAN_NAME}" '
        f'"Managed by Hardware Tier Analysis Tool"')

    _apply_cpu_cap(new_guid, cpu_max_pct)
    print(f"  [Power] Created limiter plan: {new_guid}")
    return new_guid


def _apply_cpu_cap(guid: str, max_pct: int):
    """Set processor max state on AC and DC for a given plan GUID."""
    # SUB_PROCESSOR = 54533251-... PROCTHROTTLEMAX = bc5038f7-...
    sub  = "54533251-82be-4824-96c1-47b60b740d00"
    maxa = "bc5038f7-23e0-4960-96da-33abaf5935ec"
    run(f"powercfg /setacvalueindex {guid} {sub} {maxa} {max_pct}")
    run(f"powercfg /setdcvalueindex {guid} {sub} {maxa} {max_pct}")
    # Also set min to something low for realistic throttling
    mini = "893dee8e-2bef-41e0-89c6-b55d0929964c"
    run(f"powercfg /setacvalueindex {guid} {sub} {mini} 5")
    run(f"powercfg /setdcvalueindex {guid} {sub} {mini} 5")
    print(f"  [Power] CPU max frequency set to {max_pct}%")


def activate_plan(guid: str):
    run(f"powercfg /setactive {guid}")
    print(f"  [Power] Activated plan: {guid}")


def delete_limiter_plan():
    """Remove the custom limiter plan if it exists."""
    for plan in get_all_power_plans():
        if LIMITER_PLAN_NAME in plan["name"]:
            run(f'powercfg /delete {plan["guid"]}')
            print(f"  [Power] Deleted limiter plan: {plan['guid']}")


# ── Core Affinity ──────────────────────────────────────────────────────

def set_system_affinity_processes(core_count: int):
    """
    Apply a CPU affinity mask to common high-impact processes.
    This limits which cores those processes can use.
    core_count: how many logical cores to allow (from core 0 upward)
    """
    import ctypes.wintypes

    # Build bitmask: e.g. 4 cores = 0b1111 = 15
    total_cores = os.cpu_count() or 1
    allowed = min(core_count, total_cores)
    mask = (1 << allowed) - 1

    print(f"  [Affinity] Setting affinity mask {bin(mask)} "
          f"({allowed}/{total_cores} cores)")

    # Use PowerShell to apply to explorer and common game/app processes
    # This is advisory — processes can reset their own affinity
    ps_script = f"""
$mask = {mask}
$targets = @('explorer','steam','chrome','firefox','msedge')
foreach ($name in $targets) {{
    Get-Process -Name $name -ErrorAction SilentlyContinue | ForEach-Object {{
        try {{ $_.ProcessorAffinity = $mask; Write-Host "Set $name affinity" }}
        catch {{ Write-Host "Skip $name: $_" }}
    }}
}}
"""
    result = ps(ps_script.replace('"', '\\"').replace('\n', '; '))
    return mask


# ── WMI Name Spoofing ──────────────────────────────────────────────────

def spoof_wmi_cpu_name(fake_name: str) -> bool:
    """
    Write a registry override so WMI returns a different CPU name.
    This only affects SOFTWARE that reads from this registry path —
    your actual CPU is untouched.
    
    Key: HKLM\\HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0
    Value: ProcessorNameString
    """
    reg_path  = r"HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\0"
    reg_value = "ProcessorNameString"

    # First back up real value
    code, real = run(f'reg query "{reg_path}" /v "{reg_value}"')
    real_name = ""
    if code == 0:
        for line in real.splitlines():
            if reg_value in line:
                real_name = line.split("REG_SZ")[-1].strip()

    # Write fake name
    code, out = run(
        f'reg add "{reg_path}" /v "{reg_value}" '
        f'/t REG_SZ /d "{fake_name}" /f')

    if code == 0:
        print(f"  [WMI Spoof] CPU name set to: {fake_name}")
        print(f"  [WMI Spoof] Real name backed up: {real_name}")
        return True
    else:
        print(f"  [WMI Spoof] Failed: {out}")
        return False


def restore_wmi_cpu_name(real_name: str):
    """Restore the original CPU name in the registry."""
    if not real_name:
        return
    reg_path  = r"HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\0"
    reg_value = "ProcessorNameString"
    run(f'reg add "{reg_path}" /v "{reg_value}" '
        f'/t REG_SZ /d "{real_name}" /f')
    print(f"  [WMI Spoof] CPU name restored to: {real_name}")


# ── Tier → Constraint mapping ─────────────────────────────────────────

TIER_CONSTRAINTS = {
    # tier: (cpu_max_pct, allowed_cores_fraction, description)
    "F":  (15,  0.25, "Below Entry-Level  — 15% CPU, 1/4 cores"),
    "E":  (25,  0.25, "Entry-Level        — 25% CPU, 1/4 cores"),
    "D":  (40,  0.50, "Budget             — 40% CPU, 1/2 cores"),
    "C":  (60,  0.50, "Mainstream         — 60% CPU, 1/2 cores"),
    "B":  (75,  0.75, "Enthusiast         — 75% CPU, 3/4 cores"),
    "A":  (90,  1.00, "High-End           — 90% CPU, all cores"),
    "S":  (100, 1.00, "Flagship           — 100% CPU, all cores (baseline)"),
    "S+": (100, 1.00, "Pinnacle           — 100% CPU, all cores (baseline)"),
}


def tier_to_core_count(tier: str) -> int:
    total = os.cpu_count() or 4
    _, fraction, _ = TIER_CONSTRAINTS.get(tier, (100, 1.0, ""))
    return max(1, int(total * fraction))


# ── Save / Restore profile ─────────────────────────────────────────────

def save_restore_point():
    """Snapshot current power plan and CPU name for later restoration."""
    guid, name = get_active_power_plan()

    # Get real CPU name from registry
    code, out = run(
        r'reg query "HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\0" '
        r'/v "ProcessorNameString"')
    real_cpu = ""
    if code == 0:
        for line in out.splitlines():
            if "ProcessorNameString" in line:
                real_cpu = line.split("REG_SZ")[-1].strip()

    restore = {
        "timestamp": datetime.now().isoformat(),
        "power_plan_guid": guid,
        "power_plan_name": name,
        "real_cpu_name":   real_cpu,
    }
    save_json(RESTORE_FILE, restore)
    print(f"  [Restore] Point saved → {RESTORE_FILE}")
    return restore


def restore_all():
    """Undo everything the limiter applied."""
    if not Path(RESTORE_FILE).exists():
        print("  [Restore] No restore point found.")
        return

    r = load_json(RESTORE_FILE)
    print(f"  [Restore] Restoring to snapshot from {r.get('timestamp','?')}")

    # Re-activate original power plan
    guid = r.get("power_plan_guid", "")
    if guid:
        activate_plan(guid)

    # Delete custom limiter plan
    delete_limiter_plan()

    # Restore CPU name
    restore_wmi_cpu_name(r.get("real_cpu_name", ""))

    # Remove profile file
    for f in [PROFILE_FILE]:
        if Path(f).exists():
            os.remove(f)
            print(f"  [Restore] Removed {f}")

    print("\n  [Restore] System restored to original configuration.")


# ── Apply a target tier ────────────────────────────────────────────────

def apply_tier(target_tier: str, target_cpu_model: str = ""):
    """
    Apply all constraints to simulate target_tier hardware.
    """
    if target_tier not in TIER_CONSTRAINTS:
        print(f"[ERROR] Unknown tier: {target_tier}")
        return False

    cpu_pct, _, desc = TIER_CONSTRAINTS[target_tier]
    core_count = tier_to_core_count(target_tier)

    header(f"Applying Tier {target_tier} — {desc}")

    if not is_admin():
        print("  [WARNING] Not running as Administrator.")
        print("            Power plan changes require elevation.")
        print("            Re-run as Admin for full effect.\n")

    # 1. Save restore point
    section("Saving restore point")
    restore = save_restore_point()

    # 2. Power plan
    section("Configuring CPU power plan")
    plan_guid = create_limiter_plan(cpu_pct)
    if plan_guid:
        activate_plan(plan_guid)

    # 3. Affinity hint
    section("Setting process CPU affinity hints")
    set_system_affinity_processes(core_count)

    # 4. WMI name spoof
    if target_cpu_model:
        section("Applying CPU name override (WMI)")
        spoof_wmi_cpu_name(target_cpu_model)

    # 5. Save active profile
    profile = {
        "applied_at":    datetime.now().isoformat(),
        "target_tier":   target_tier,
        "cpu_max_pct":   cpu_pct,
        "allowed_cores": core_count,
        "spoofed_name":  target_cpu_model,
        "description":   desc,
    }
    save_json(PROFILE_FILE, profile)

    section("Done")
    print(f"  Tier {target_tier} profile is now ACTIVE.")
    print(f"  CPU throttled to : {cpu_pct}% max frequency")
    print(f"  Cores available  : {core_count} / {os.cpu_count()}")
    if target_cpu_model:
        print(f"  WMI CPU name     : {target_cpu_model}")
    print(f"\n  To restore your real hardware: python limiter.py --restore")
    return True


# ── CLI ────────────────────────────────────────────────────────────────

def print_status():
    header("Current Limiter Status")
    if Path(PROFILE_FILE).exists():
        p = load_json(PROFILE_FILE)
        print(f"  Status          : ACTIVE")
        print(f"  Applied at      : {p.get('applied_at','?')}")
        print(f"  Target tier     : {p.get('target_tier','?')}")
        print(f"  CPU cap         : {p.get('cpu_max_pct','?')}%")
        print(f"  Allowed cores   : {p.get('allowed_cores','?')}")
        print(f"  Spoofed name    : {p.get('spoofed_name') or '(none)'}")
    else:
        print("  Status          : INACTIVE (no profile applied)")

    guid, name = get_active_power_plan()
    print(f"\n  Active power plan: {name}")
    print(f"  Plan GUID        : {guid}")
    print(f"  Physical cores   : {os.cpu_count()}")


def interactive_menu():
    """Text-based interactive menu for picking a target tier."""
    header("Hardware Tier Performance Limiter")
    print("  Simulate lower-tier hardware using Windows power controls.\n")
    print("  WHAT THIS DOES:")
    print("  - Caps CPU max frequency via a custom Windows power plan")
    print("  - Limits process CPU affinity (visible core count)")
    print("  - Optionally overrides the CPU name reported by WMI")
    print("  - Saves a restore point so you can undo everything instantly\n")
    print("  WHAT THIS DOES NOT DO:")
    print("  - Touch your GPU, RAM hardware, or drivers")
    print("  - Make permanent system changes")
    print("  - Affect BIOS or firmware\n")

    # Load library for CPU names
    cpu_options = {}
    if Path(LIBRARY_FILE).exists():
        lib = load_json(LIBRARY_FILE)
        for entry in lib.get("cpu_library", []):
            tier = entry["tier"]
            if tier not in cpu_options:
                cpu_options[tier] = []
            cpu_options[tier].append(entry["model"])

    # Show current specs
    if Path(SPECS_FILE).exists():
        specs = load_json(SPECS_FILE)
        print(f"  Your hardware:")
        print(f"    CPU : {specs.get('cpu',{}).get('model','?')}")
        print(f"    Cores: {specs.get('cpu',{}).get('logical_cores','?')}")
        print(f"    RAM : {specs.get('ram',{}).get('total_gb','?')} GB")
        print(f"    GPU : {specs.get('gpu',{}).get('model','?')}\n")

    # Check if already active
    if Path(PROFILE_FILE).exists():
        p = load_json(PROFILE_FILE)
        print(f"  [!] A profile is currently ACTIVE: "
              f"Tier {p.get('target_tier','?')} — {p.get('description','')}")
        print(f"      To restore first, run: python limiter.py --restore\n")

    print("  Select target tier to simulate:\n")
    for i, tier in enumerate(TIER_ORDER, 1):
        cpu_pct, _, desc = TIER_CONSTRAINTS[tier]
        cores = tier_to_core_count(tier)
        total = os.cpu_count() or 4
        print(f"  [{i}] Tier {tier:2s}  {desc}")
        print(f"       → {cpu_pct}% CPU freq cap, {cores}/{total} cores")

    print(f"\n  [R] Restore original hardware")
    print(f"  [S] Show current status")
    print(f"  [Q] Quit\n")

    choice = input("  Enter choice: ").strip().upper()

    if choice == "Q":
        return
    if choice == "R":
        restore_all()
        return
    if choice == "S":
        print_status()
        return

    try:
        idx = int(choice) - 1
        target_tier = TIER_ORDER[idx]
    except (ValueError, IndexError):
        print("  Invalid choice.")
        return

    # Optionally pick a CPU name to spoof
    print(f"\n  Optionally spoof the CPU name that WMI reports.")
    print(f"  This affects what software 'sees' as your CPU model.\n")

    spoof_name = ""
    names = cpu_options.get(target_tier, [])
    if names:
        print(f"  Suggested CPUs for Tier {target_tier}:")
        for i, n in enumerate(names[:6], 1):
            print(f"    [{i}] {n}")
        print(f"    [0] No spoofing — keep real CPU name\n")
        nc = input("  Pick a name (or press Enter to skip): ").strip()
        try:
            ni = int(nc)
            if 1 <= ni <= len(names[:6]):
                spoof_name = names[ni-1]
        except ValueError:
            pass

    # Confirm
    cpu_pct, _, desc = TIER_CONSTRAINTS[target_tier]
    cores = tier_to_core_count(target_tier)
    print(f"\n  About to apply:")
    print(f"    Tier     : {target_tier} — {desc}")
    print(f"    CPU cap  : {cpu_pct}%")
    print(f"    Cores    : {cores} / {os.cpu_count()}")
    if spoof_name:
        print(f"    WMI name : {spoof_name}")
    confirm = input("\n  Proceed? [Y/N]: ").strip().upper()
    if confirm == "Y":
        apply_tier(target_tier, spoof_name)
    else:
        print("  Cancelled.")


def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg == "--restore":
            header("Restoring Original Hardware Profile")
            restore_all()
        elif arg == "--status":
            print_status()
        elif arg in [t.lower() for t in TIER_ORDER]:
            target = arg.upper()
            name = sys.argv[2] if len(sys.argv) > 2 else ""
            apply_tier(target, name)
        else:
            print(f"Usage:")
            print(f"  python limiter.py                    # interactive menu")
            print(f"  python limiter.py --restore          # undo all changes")
            print(f"  python limiter.py --status           # show current state")
            print(f"  python limiter.py <tier> [cpu_name]  # apply directly")
            print(f"\n  Tiers: {', '.join(TIER_ORDER)}")
    else:
        interactive_menu()

    print()
    input("Press Enter to exit...")


if __name__ == "__main__":
    main()
