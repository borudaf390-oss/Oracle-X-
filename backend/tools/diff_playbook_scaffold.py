"""
Systematic scaffold diff: our translator's output vs. the authoritative
`npx @bitget-ai/getagent-skill` scaffold.

This does the MECHANICAL comparison (file presence, YAML top-level key
sets, key-value differences) across the five areas — it deliberately does
NOT auto-classify differences as A/confirmed-compatible, B/needs-adaptation,
or C/unsupported-assumption, because that judgment requires knowing WHY a
field differs (a renamed key vs. a genuinely unsupported field vs. our
exporter simply omitting an optional field), which needs a human looking
at both the diff and GetAgent's actual docs/examples. Per the explicit
instruction this tool exists to serve: don't "fix" something just because
it looks different — understand why first.

Usage:
    python tools/diff_playbook_scaffold.py <our_package_dir> <official_scaffold_dir>

Example:
    python tools/diff_playbook_scaffold.py \\
        ./playbook/oracle-x-nvdausdt-amdusdt-42 \\
        ./scaffold-from-getagent-skill
"""
import sys
import os
import yaml

AREAS = [
    ("Package layout", None),  # special-cased below (directory tree, not a single file)
    ("manifest.yaml", "manifest.yaml"),
    ("backtest.yaml", "backtest.yaml"),
    ("src/main.py", os.path.join("src", "main.py")),
    ("src/strategy.py", os.path.join("src", "strategy.py")),
]


def _list_files(root: str) -> set:
    out = set()
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fname), root)
            out.add(rel)
    return out


def _diff_layout(ours: str, official: str):
    ours_files = _list_files(ours)
    official_files = _list_files(official)
    only_ours = sorted(ours_files - official_files)
    only_official = sorted(official_files - ours_files)
    common = sorted(ours_files & official_files)

    print("  Files only in our exporter's output (candidate: unsupported/extra):")
    for f in only_ours or ["(none)"]:
        print(f"    - {f}")
    print("  Files only in the official scaffold (candidate: something we're missing):")
    for f in only_official or ["(none)"]:
        print(f"    - {f}")
    print(f"  Files in both: {len(common)}")


def _diff_yaml(ours_path: str, official_path: str):
    if not os.path.exists(ours_path):
        print("  (we did not generate this file)")
        return
    if not os.path.exists(official_path):
        print("  (official scaffold does not have this file — investigate why)")
        return

    with open(ours_path) as f:
        ours = yaml.safe_load(f) or {}
    with open(official_path) as f:
        official = yaml.safe_load(f) or {}

    ours_keys = set(ours.keys()) if isinstance(ours, dict) else set()
    official_keys = set(official.keys()) if isinstance(official, dict) else set()

    print(f"  Top-level keys only in ours:     {sorted(ours_keys - official_keys) or '(none)'}")
    print(f"  Top-level keys only in official: {sorted(official_keys - ours_keys) or '(none)'}")
    print(f"  Top-level keys in both:          {sorted(ours_keys & official_keys) or '(none)'}")

    for key in sorted(ours_keys & official_keys):
        if ours.get(key) != official.get(key):
            print(f"    [DIFFERS] {key}:")
            print(f"      ours:     {ours.get(key)!r}")
            print(f"      official: {official.get(key)!r}")


def _diff_python(ours_path: str, official_path: str):
    if not os.path.exists(ours_path):
        print("  (we did not generate this file)")
        return
    if not os.path.exists(official_path):
        print("  (official scaffold does not have this file — investigate why)")
        return
    ours_lines = open(ours_path).read().splitlines()
    official_lines = open(official_path).read().splitlines()
    print(f"  ours: {len(ours_lines)} lines, official: {len(official_lines)} lines")
    print("  (Python structure diff is a judgment call, not mechanical — read both "
          "side by side. Specifically check: class name GetAgent expects, base class "
          "import path, lifecycle method names (on_start/on_bar/etc.), and how "
          "orders are actually submitted.)")


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    ours_dir, official_dir = sys.argv[1], sys.argv[2]

    print("=" * 70)
    print("SCAFFOLD DIFF — fill in A/confirmed, B/needs-adaptation, or")
    print("C/unsupported-assumption for each difference after reading why it exists.")
    print("=" * 70)

    for label, relpath in AREAS:
        print(f"\n--- {label} ---")
        if relpath is None:
            _diff_layout(ours_dir, official_dir)
            continue
        ours_path = os.path.join(ours_dir, relpath)
        official_path = os.path.join(official_dir, relpath)
        if relpath.endswith(".yaml"):
            _diff_yaml(ours_path, official_path)
        else:
            _diff_python(ours_path, official_path)

    print("\n" + "=" * 70)
    print("Next: for every [DIFFERS] / only-in-one-side item above, classify it:")
    print("  A — confirmed compatible (cosmetic difference, both work)")
    print("  B — needs adaptation (update translator.py to match)")
    print("  C — unsupported assumption (translator.py invented something GetAgent doesn't have)")
    print("Then update app/playbook/translator.py's docstring + code accordingly.")


if __name__ == "__main__":
    main()
