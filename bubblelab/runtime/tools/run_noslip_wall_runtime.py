from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bubblelab.runtime.bundle import validate_replay_bundle
from bubblelab.runtime.runner import run_scenario


SCENARIO = ROOT / "bubblelab" / "scenarios" / "runtime" / "transient-noslip-moving-floor.scenario.json"


def run_probe() -> dict[str, object]:
    scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as out:
        replay = run_scenario(scenario, "transient", out, frames=3)
        validate_replay_bundle(out)
        root = Path(out)
        frames = [json.loads((root / ref["path"]).read_text(encoding="utf-8")) for ref in replay["frames"]]
        initial = frames[0]["diagnostics"]["bulk_solid_wall_cfd"]
        final = frames[-1]["diagnostics"]["bulk_solid_wall_cfd"]
        disclosures = frames[-1]["manifest"]["feature_disclosures"]
        provenance = replay["provenance"]["bulk_solid_wall_cfd"]

        checks = {
            "explicit_request_recorded": replay["run_settings"].get("bulk_solid_wall_no_slip_requested") is True,
            "wall_field_installed": initial.get("wall_field") == "ResolvedNoSlipWallField" and bool(initial.get("installed_on_all_levels")),
            "resolved_cells_present": int(initial.get("solid_cell_count", 0)) > 0 and int(initial.get("cut_face_count", 0)) > 0,
            "normal_velocity_imposed": float(final.get("max_wall_normal_velocity_error_m_s", 1.0)) <= 1.0e-12,
            "solid_storage_imposed": float(final.get("max_solid_storage_velocity_error_m_s", 1.0)) <= 1.0e-12,
            "tangential_measurement_present": int(initial.get("tangential_reconstruction_sample_count", 0)) > 0,
            "moving_wall_slip_is_measured": float(initial.get("max_wall_tangential_reconstruction_error_m_s", 0.0)) > 0.05,
            "feature_disclosed": disclosures.get("bulk_solid_wall_no_slip") == "RESOLVED" and disclosures.get("bulk_solid_fluid_wall_coupling") == "RESOLVED",
            "authoritative_provenance": provenance.get("measurement_source") == "authoritative Eulerian velocity state",
            "backend_matches_final_measurement": replay["backend"].get("bulk_wall_cfd") == final,
        }
        return {
            "scenario_id": scenario["scenario_id"],
            "checks": checks,
            "initial_wall_diagnostics": initial,
            "final_wall_diagnostics": final,
            "pass": all(checks.values()),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assert", dest="assert_pass", action="store_true")
    args = parser.parse_args()
    report = run_probe()
    print(json.dumps(report, sort_keys=True))
    if args.assert_pass and not report["pass"]:
        raise SystemExit("no-slip wall runtime integration probe failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
