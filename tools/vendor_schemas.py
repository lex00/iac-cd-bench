#!/usr/bin/env python3
"""Refresh `schemas/` — the CRD JSON schemas the lint and static gates use.

Why this exists at all: kubeconform ships schemas for core Kubernetes kinds
only. The stacks under test are mostly CRDs — ACK for AWS resources, Cluster
API for clusters — so without a mirror every one of those resources is either
skipped (scoring an invented kind as fine) or failed (scoring a correct answer
as wrong). Both happened; see #81 and #83.

Two deliberate choices:

**Vendored, not fetched at validation time.** A gate that reaches the network
mid-run is a gate whose verdict depends on what upstream held that day, and on
whether the machine was online. The mirror is committed so a run is
reproducible from the checkout alone.

**`additionalProperties` is relaxed.** CRD field sets drift between releases,
and a schema pinned to one release will reject fields that a later one added.
That is not a model error, it is skew — the bare golden was failed for
`Bucket.spec.replication.roleRef`, which the current ACK S3 controller does
define, purely because the catalog's snapshot predates it. Removing the
constraint keeps everything that matters (an unresolvable *kind* still fails,
and so does a field of the wrong *type*) and drops only "no unknown fields",
which is precisely the version-sensitive part.

That makes `schemas/` a derived artifact rather than a verbatim mirror, which
is why refreshing it goes through this script instead of a bare curl.

usage: python3 tools/vendor_schemas.py [--pin <sha>] [--check]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schemas"
CATALOG = "https://raw.githubusercontent.com/datreeio/CRDs-catalog"

# Pinned so a refresh is reproducible. Bump deliberately, not incidentally.
DEFAULT_PIN = "7b1e26ef9deea49293714d204c1a2270aab1178f"

# Group -> schema files. Versions are not a choice made here: they are the
# ones tasks/ and golden-base/ already use (ACK v1alpha1, Cluster API
# v1beta1). If a fixture starts using a new kind, add it here.
WANTED: dict[str, list[str]] = {
    "s3.services.k8s.aws": ["bucket_v1alpha1.json"],
    "iam.services.k8s.aws": [
        "policy_v1alpha1.json", "role_v1alpha1.json", "user_v1alpha1.json",
        "group_v1alpha1.json", "instanceprofile_v1alpha1.json",
        "openidconnectprovider_v1alpha1.json",
    ],
    "rds.services.k8s.aws": [
        "dbinstance_v1alpha1.json", "dbsubnetgroup_v1alpha1.json",
        "dbcluster_v1alpha1.json", "dbparametergroup_v1alpha1.json",
    ],
    "cluster.x-k8s.io": [
        "cluster_v1beta1.json", "machinedeployment_v1beta1.json",
        "machine_v1beta1.json", "machineset_v1beta1.json",
    ],
    "controlplane.cluster.x-k8s.io": ["kubeadmcontrolplane_v1beta1.json"],
    "infrastructure.cluster.x-k8s.io": [
        "awscluster_v1beta1.json", "awsmachinetemplate_v1beta1.json",
        "awsmachine_v1beta1.json",
    ],
    "bootstrap.cluster.x-k8s.io": [
        "kubeadmconfig_v1beta1.json", "kubeadmconfigtemplate_v1beta1.json",
    ],
}


def relax(node):
    """Drop `additionalProperties: false` everywhere, recursively."""
    if isinstance(node, dict):
        if node.get("additionalProperties") is False:
            node.pop("additionalProperties")
        for value in node.values():
            relax(value)
    elif isinstance(node, list):
        for item in node:
            relax(item)
    return node


def fetch(pin: str, group: str, name: str) -> dict:
    url = f"{CATALOG}/{pin}/{group}/{name}"
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", default=DEFAULT_PIN)
    ap.add_argument("--check", action="store_true",
                    help="verify the vendored files exist and are relaxed; "
                         "no network access")
    args = ap.parse_args()

    if args.check:
        missing, strict = [], []
        for group, names in WANTED.items():
            for name in names:
                path = SCHEMA_DIR / group / name
                if not path.is_file():
                    missing.append(f"{group}/{name}")
                    continue
                if '"additionalProperties": false' in path.read_text():
                    strict.append(f"{group}/{name}")
        for m in missing:
            print(f"MISSING {m}")
        for s in strict:
            print(f"NOT RELAXED {s}")
        total = sum(len(v) for v in WANTED.values())
        print(f"{total - len(missing)}/{total} present, {len(strict)} not relaxed")
        return 1 if (missing or strict) else 0

    written = 0
    for group, names in WANTED.items():
        (SCHEMA_DIR / group).mkdir(parents=True, exist_ok=True)
        for name in names:
            try:
                schema = fetch(args.pin, group, name)
            except (urllib.error.URLError, urllib.error.HTTPError) as exc:
                print(f"FAILED {group}/{name}: {exc}", file=sys.stderr)
                return 1
            (SCHEMA_DIR / group / name).write_text(
                json.dumps(relax(schema), indent=2) + "\n")
            written += 1
    print(f"vendored {written} schemas from catalog {args.pin[:10]}, "
          "additionalProperties relaxed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
