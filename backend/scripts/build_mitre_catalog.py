"""Build the offline Enterprise ATT&CK catalog from an official versioned STIX bundle.

Usage: python scripts/build_mitre_catalog.py <path-or-url> [--output path]
Only this build-time script uses the network; the application never downloads ATT&CK.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen


def build_catalog(bundle, source):
    objects = bundle["objects"]
    active = [o for o in objects if not o.get("revoked") and not o.get("x_mitre_deprecated")]
    collection = next(o for o in active if o["type"] == "x-mitre-collection"
                      and o["name"] == "Enterprise ATT&CK")
    matrix = next(o for o in active if o["type"] == "x-mitre-matrix"
                  and "enterprise-attack" in o.get("x_mitre_domains", []))
    order = {ref: i + 1 for i, ref in enumerate(matrix["tactic_refs"])}

    def reference(obj):
        return next(r for r in obj["external_references"] if r["source_name"] == "mitre-attack")

    tactics = sorted([
        {"id": reference(o)["external_id"], "shortname": o["x_mitre_shortname"],
         "name": o["name"], "order": order[o["id"]]}
        for o in active if o["type"] == "x-mitre-tactic" and o["id"] in order
    ], key=lambda t: t["order"])
    techniques = {}
    for obj in active:
        if obj["type"] != "attack-pattern":
            continue
        ref = reference(obj)
        tid = ref["external_id"]
        techniques[tid] = {
            "name": obj["name"],
            "tactics": sorted({p["phase_name"] for p in obj.get("kill_chain_phases", [])
                               if p["kill_chain_name"] == "mitre-attack"}),
            "url": ref["url"], "is_subtechnique": obj.get("x_mitre_is_subtechnique", False),
            "parent": tid.split(".")[0] if obj.get("x_mitre_is_subtechnique") else None,
        }
    return {"attack_version": collection["x_mitre_version"], "domain": "enterprise-attack",
            "source": source, "generated_at": datetime.now(timezone.utc).isoformat(),
            "tactics": tactics, "techniques": techniques}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parents[1] / "app/data/mitre_attack_enterprise.json")
    args = parser.parse_args()
    if args.source.startswith(("https://", "http://")):
        with urlopen(args.source, timeout=120) as response:
            bundle = json.load(response)
    else:
        bundle = json.loads(Path(args.source).read_text(encoding="utf-8"))
    catalog = build_catalog(bundle, args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"ATT&CK {catalog['attack_version']}: {len(catalog['techniques'])} techniques -> {args.output}")


if __name__ == "__main__":
    main()
