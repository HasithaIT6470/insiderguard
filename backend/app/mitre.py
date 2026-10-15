"""Offline ATT&CK context. Mapping is heuristic and never changes a risk score."""
import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from . import config

log = logging.getLogger("insiderguard.mitre")
ATTRIBUTION = (
    "© 2026 The MITRE Corporation. This work is reproduced and distributed with the permission of The MITRE Corporation. "
    "MITRE ATT&CK and ATT&CK are registered trademarks of The MITRE Corporation."
)


def _removable(detail):
    return bool(re.match(config.REMOVABLE_DEVICE_PATTERN, str(detail.get("observed") or "")))


def _collected(detail):
    return detail.get("resource_event") in {"file_access", "download", "honeytoken"} and detail.get("result") != "denied"


def _rule(technique, confidence, rationale, when=None):
    return {"technique": technique, "confidence": confidence, "rationale": rationale,
            **({"when": when} if when else {})}


MAPPINGS = {
    "failed_logon_burst": [_rule("T1110", "high", "Burst of failed logons against one account inside the burst window")],
    "repeated_denied_access": [_rule("T1083", "medium", "Repeated denied requests suggest probing for reachable resources")],
    "restricted_resource_access": [_rule("T1039", "medium", "Access to restricted shared data")],
    "bulk_download": [
        _rule("T1039", "medium", "Large pull of shared data to the endpoint, a possible staging step"),
        _rule("T1074.001", "low", "Large pull of shared data to the endpoint, a possible staging step")],
    "download_volume_anomaly": [
        _rule("T1039", "medium", "Large pull of shared data to the endpoint, a possible staging step, measured against the user's own baseline"),
        _rule("T1074.001", "low", "Large pull of shared data to the endpoint, a possible staging step, measured against the user's own baseline")],
    "access_volume_anomaly": [
        _rule("T1039", "medium", "Unusually many file reads (hoarding or enumeration)"),
        _rule("T1083", "low", "Unusually many file reads (hoarding or enumeration)")],
    "novel_resource_category": [_rule("T1083", "low", "Touching resource types outside the user's baseline")],
    "off_hours_activity": [_rule("T1078", "low", 'Valid credentials used outside working hours (ATT&CK has no "off-hours" technique)')],
    "anomalous_login_time": [_rule("T1078", "medium", "Login far from the user's baseline login hour")],
    "unknown_device": [
        _rule("T1052.001", "medium", "A new removable device is a possible exfiltration channel", _removable),
        _rule("T1078", "low", "The account was used from an unfamiliar device", lambda d: not _removable(d))],
    "honeytoken_interaction": [
        _rule("T1083", "medium", "A decoy was found (discovery)"),
        _rule("T1039", "high", "A decoy was opened or copied (collection)", _collected)],
    "correlated_indicators": [],
}
_warned_names = set()


def techniques_for(name: str, detail: dict) -> list[str]:
    if name not in MAPPINGS and name not in _warned_names:
        log.warning("No ATT&CK mapping for indicator %s", name)
        _warned_names.add(name)
    return list(dict.fromkeys(rule["technique"] for rule in MAPPINGS.get(name, [])
                              if "when" not in rule or rule["when"](detail or {})))


@lru_cache(maxsize=1)
def load_catalog():
    return json.loads((Path(__file__).parent / "data/mitre_attack_enterprise.json").read_text(encoding="utf-8"))


def resolve(ids, indicator_name, detail) -> list[dict]:
    """Resolve stored IDs, preserving unknown IDs without failing an alert response."""
    try:
        catalog = load_catalog()
    except (OSError, ValueError):
        log.exception("Unable to load ATT&CK catalog")
        catalog = {"techniques": {}, "tactics": []}
    result = []
    for tid in dict.fromkeys(ids or []):
        technique = catalog["techniques"].get(tid)
        rule = next((r for r in MAPPINGS.get(indicator_name, []) if r["technique"] == tid), {})
        result.append({
            "id": tid, "name": technique["name"] if technique else "Unknown technique",
            "tactics": [{"id": t["id"], "name": t["name"]} for t in catalog["tactics"]
                        if technique and t["shortname"] in technique["tactics"]],
            "url": technique["url"].rstrip("/") + "/" if technique else None,
            "confidence": rule.get("confidence"), "rationale": rule.get("rationale"),
        })
    return result


def enrich_breakdown(breakdown) -> list[dict]:
    result = []
    for item in breakdown or []:
        name, detail = item.get("name", ""), item.get("detail") or {}
        ids = item["attack_techniques"] if "attack_techniques" in item else techniques_for(name, detail)
        result.append({**item, "attack": resolve(ids, name, detail)})
    return result


def attack_summary(breakdown) -> dict:
    techniques = {}
    rank = {None: -1, "low": 0, "medium": 1, "high": 2}
    for item in enrich_breakdown(breakdown):
        for technique in item["attack"]:
            tid = technique["id"]
            if tid not in techniques:
                techniques[tid] = {**technique, "indicators": []}
            elif rank[technique["confidence"]] > rank[techniques[tid]["confidence"]]:
                techniques[tid].update(technique)
            if item["name"] not in techniques[tid]["indicators"]:
                techniques[tid]["indicators"].append(item["name"])
    catalog = load_catalog()
    tactics = []
    for tactic in catalog["tactics"]:
        ids = [tid for tid, t in techniques.items() if any(x["id"] == tactic["id"] for x in t["tactics"])]
        if ids:
            tactics.append({"id": tactic["id"], "name": tactic["name"], "techniques": ids})
    return {"attack_version": catalog["attack_version"], "techniques": list(techniques.values()),
            "tactics": tactics, "attribution": ATTRIBUTION}


def mapping_table():
    """All mapping rules, including both conditional branches, for analyst audits."""
    return {"attack_version": load_catalog()["attack_version"], "attribution": ATTRIBUTION,
            "mappings": {name: [{**resolve([r["technique"]], name, {})[0],
                                   "condition": ("removable device" if r["technique"] == "T1052.001"
                                                 else "non-removable device" if name == "unknown_device"
                                                 else "resource_event in file_access, download, honeytoken and result != denied")
                                   if "when" in r else None} for r in rules]
                         for name, rules in MAPPINGS.items()}}
