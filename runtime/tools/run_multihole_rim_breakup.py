#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from bubblelab.runtime.multihole_rim_breakup_runtime import run_multihole_rim_breakup_runtime

DEFAULT_SCENARIO = ROOT / 'bubblelab' / 'scenarios' / 'runtime' / 'multihole-rim-breakup.scenario.json'


def assert_payload(payload):
    events=payload['event_sequence']
    expected=['TWO_HOLE_RETRACTION','RIM_INTERACTION_ONSET','MULTIHOLE_LIGAMENT_ONSET','STATE_DERIVED_MULTIRIM_DETACHMENT']
    if [event['type'] for event in events] != expected:
        raise AssertionError('runtime did not preserve interacting multihole event sequence')
    if not events[0]['time_s'] < events[1]['time_s'] <= events[2]['time_s'] < events[3]['time_s']:
        raise AssertionError('multihole runtime event times are not ordered')
    if len(payload['holes']) != 2:
        raise AssertionError('runtime must expose two simultaneous hole/rim states')
    if float(payload['interaction']['detachment_time_relative_shift']) < 0.05:
        raise AssertionError('runtime interaction effect is below the 5% acceptance gate')
    if float(payload['interaction']['final_gap_m']) <= 0.0:
        raise AssertionError('runtime default evidence should precede hole coalescence')
    if payload['interaction']['independent_run_stitching'] != 'NOT_USED':
        raise AssertionError('runtime cannot use stitched independent runs')
    if float(payload['budgets']['liquid_volume_relative_error']) > 1e-12:
        raise AssertionError('runtime liquid conservation failed')
    if abs(float(payload['budgets']['pre_detachment_rim_volume_m3'])-float(payload['budgets']['detached_droplet_volume_m3'])) > 1e-12:
        raise AssertionError('runtime detached volume does not match pre-detachment rim volume')
    expected_droplets=sum(len(hole['evolved_neck_cells']) for hole in payload['holes'])
    if len(payload['droplets']) != expected_droplets:
        raise AssertionError('runtime fragment count is not derived from evolved necks')
    if not payload['continuation']['exact_evolved_velocity_seed']:
        raise AssertionError('continuation did not consume evolved velocity')
    ids=[drop['id'] for drop in payload['droplets']]
    if len(ids) != len(set(ids)):
        raise AssertionError('droplet identities are not unique')
    for drop in payload['droplets']:
        if int(drop['source_hole']) not in (0,1):
            raise AssertionError('invalid source hole')
        if float(drop['volume_m3']) <= 0.0 or not all(math.isfinite(float(v)) for v in drop['velocity_m_s']):
            raise AssertionError('invalid detached droplet state')


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument('scenario',nargs='?',default=str(DEFAULT_SCENARIO))
    parser.add_argument('--assert',dest='assert_result',action='store_true')
    args=parser.parse_args()
    scenario=json.loads(Path(args.scenario).read_text(encoding='utf-8'))
    payload=run_multihole_rim_breakup_runtime(scenario)
    if args.assert_result:
        assert_payload(payload)
    print(json.dumps(payload,sort_keys=True,indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
