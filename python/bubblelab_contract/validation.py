"""Dependency-free semantic validation for Bubble Lab contract documents."""
from __future__ import annotations
from collections.abc import Mapping, Sequence
from typing import Any
from .models import CONTRACT_VERSION, FEATURE_STATES, FIDELITY_TIERS

BUBBLE_STATUSES={"ALIVE","RUPTURED","MERGED","SPLIT","REMOVED"}
EVENT_TYPES={"CONTACT_BEGIN","FILM_FORMED","COALESCENCE","RUPTURE","SPLIT","CONTACT_END","BUBBLE_REMOVED"}

class ContractValidationError(ValueError):
    pass

def _require(obj: Mapping[str,Any], keys: Sequence[str], path: str, errors: list[str]) -> None:
    for key in keys:
        if key not in obj: errors.append(f"{path}.{key}: missing required field")

def _number(value: Any, path: str, errors: list[str], positive=False, nonnegative=False) -> None:
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        errors.append(f"{path}: expected number"); return
    if positive and value<=0: errors.append(f"{path}: must be > 0")
    if nonnegative and value<0: errors.append(f"{path}: must be >= 0")

def _vec3(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value,list) or len(value)!=3:
        errors.append(f"{path}: expected 3-number array"); return
    for i,v in enumerate(value): _number(v,f"{path}[{i}]",errors)

def validate_manifest(data: Mapping[str,Any]) -> list[str]:
    errors=[]
    _require(data,["contract_version","units","solver","fidelity_tier","feature_disclosures","random_seed","provenance"],"$",errors)
    if data.get("contract_version")!=CONTRACT_VERSION: errors.append(f"$.contract_version: expected {CONTRACT_VERSION}")
    if not isinstance(data.get("units"),Mapping) or data["units"].get("system")!="SI": errors.append("$.units.system: expected SI")
    solver=data.get("solver")
    if not isinstance(solver,Mapping) or not solver.get("backend") or not solver.get("version"): errors.append("$.solver: backend and version are required")
    if data.get("fidelity_tier") not in FIDELITY_TIERS: errors.append("$.fidelity_tier: unsupported value")
    disclosures=data.get("feature_disclosures")
    if not isinstance(disclosures,Mapping): errors.append("$.feature_disclosures: expected object")
    else:
        for k,v in disclosures.items():
            if v not in FEATURE_STATES: errors.append(f"$.feature_disclosures.{k}: unsupported value {v!r}")
    seed=data.get("random_seed")
    if not isinstance(seed,int) or isinstance(seed,bool) or seed<0: errors.append("$.random_seed: expected non-negative integer")
    if not isinstance(data.get("provenance"),Mapping) or not data["provenance"].get("producer"): errors.append("$.provenance.producer: required")
    return errors

def _environment(data: Any, path: str, errors: list[str]) -> None:
    if not isinstance(data,Mapping): errors.append(f"{path}: expected object"); return
    _require(data,["gravity_m_s2","ambient_density_kg_m3","ambient_dynamic_viscosity_pa_s"],path,errors)
    if "gravity_m_s2" in data: _vec3(data["gravity_m_s2"],f"{path}.gravity_m_s2",errors)
    if "ambient_density_kg_m3" in data: _number(data["ambient_density_kg_m3"],f"{path}.ambient_density_kg_m3",errors,nonnegative=True)
    if "ambient_dynamic_viscosity_pa_s" in data: _number(data["ambient_dynamic_viscosity_pa_s"],f"{path}.ambient_dynamic_viscosity_pa_s",errors,nonnegative=True)

def _bubble(data: Any, path: str, errors: list[str]) -> None:
    if not isinstance(data,Mapping): errors.append(f"{path}: expected object"); return
    _require(data,["id","volume_m3","equivalent_radius_m","centroid_m","velocity_m_s","status"],path,errors)
    if not data.get("id"): errors.append(f"{path}.id: non-empty string required")
    if "volume_m3" in data: _number(data["volume_m3"],f"{path}.volume_m3",errors,positive=True)
    if "equivalent_radius_m" in data: _number(data["equivalent_radius_m"],f"{path}.equivalent_radius_m",errors,positive=True)
    if "centroid_m" in data: _vec3(data["centroid_m"],f"{path}.centroid_m",errors)
    if "velocity_m_s" in data: _vec3(data["velocity_m_s"],f"{path}.velocity_m_s",errors)
    if data.get("status") not in BUBBLE_STATUSES: errors.append(f"{path}.status: unsupported value")
    for key in ("pressure_pa","temperature_k","gas_amount_mol"):
        if key in data and data[key] is not None: _number(data[key],f"{path}.{key}",errors,nonnegative=(key!="pressure_pa"))

def _array_ref(data: Any, path: str, errors: list[str]) -> None:
    if not isinstance(data,Mapping): errors.append(f"{path}: expected array reference object"); return
    _require(data,["storage","dtype","shape"],path,errors)
    storage=data.get("storage")
    if storage=="INLINE":
        if "values" not in data: errors.append(f"{path}.values: required for INLINE")
        if "uri" in data: errors.append(f"{path}.uri: forbidden for INLINE")
    elif storage=="SIDECAR":
        if not data.get("uri"): errors.append(f"{path}.uri: required for SIDECAR")
        if "values" in data: errors.append(f"{path}.values: forbidden for SIDECAR")
    else: errors.append(f"{path}.storage: expected INLINE or SIDECAR")

def validate_frame(data: Mapping[str,Any]) -> list[str]:
    errors=[]
    _require(data,["contract_version","kind","frame_id","simulation_time_s","manifest","environment","bubbles","surface_meshes","film_regions","junctions","topology"],"$",errors)
    if data.get("contract_version")!=CONTRACT_VERSION: errors.append(f"$.contract_version: expected {CONTRACT_VERSION}")
    if data.get("kind") not in {"FRAME","CHECKPOINT"}: errors.append("$.kind: expected FRAME or CHECKPOINT")
    if data.get("kind")=="CHECKPOINT" and "checkpoint_state" not in data: errors.append("$.checkpoint_state: required for CHECKPOINT")
    _number(data.get("simulation_time_s"),"$.simulation_time_s",errors,nonnegative=True)
    if isinstance(data.get("manifest"),Mapping): errors.extend("$.manifest"+e[1:] if e.startswith("$") else e for e in validate_manifest(data["manifest"]))
    else: errors.append("$.manifest: expected object")
    _environment(data.get("environment"),"$.environment",errors)
    bubble_ids=set()
    bubbles=data.get("bubbles")
    if not isinstance(bubbles,list): errors.append("$.bubbles: expected array")
    else:
        for i,b in enumerate(bubbles):
            _bubble(b,f"$.bubbles[{i}]",errors)
            if isinstance(b,Mapping) and isinstance(b.get("id"),str):
                if b["id"] in bubble_ids: errors.append(f"$.bubbles[{i}].id: duplicate {b['id']!r}")
                bubble_ids.add(b["id"])
    meshes=data.get("surface_meshes")
    if not isinstance(meshes,list): errors.append("$.surface_meshes: expected array")
    else:
        for i,m in enumerate(meshes):
            p=f"$.surface_meshes[{i}]"
            if not isinstance(m,Mapping): errors.append(f"{p}: expected object"); continue
            _require(m,["id","geometry_role","vertex_count","face_count","vertices","faces"],p,errors)
            if "vertices" in m: _array_ref(m["vertices"],p+".vertices",errors)
            if "faces" in m: _array_ref(m["faces"],p+".faces",errors)
            for name,ref in m.get("fields",{}).items(): _array_ref(ref,p+".fields."+name,errors)
    film_ids=set()
    films=data.get("film_regions")
    if not isinstance(films,list): errors.append("$.film_regions: expected array")
    else:
        for i,f in enumerate(films):
            p=f"$.film_regions[{i}]"
            if not isinstance(f,Mapping): errors.append(f"{p}: expected object"); continue
            _require(f,["id","kind","adjacent","surface_tension_n_m"],p,errors)
            if isinstance(f.get("id"),str): film_ids.add(f["id"])
            adjacent=f.get("adjacent")
            if not isinstance(adjacent,list) or len(adjacent)!=2: errors.append(p+".adjacent: expected two entries")
            else:
                for value in adjacent:
                    if value!="EXTERIOR" and value not in bubble_ids: errors.append(p+f".adjacent: unknown bubble {value!r}")
    junctions=data.get("junctions")
    if not isinstance(junctions,list): errors.append("$.junctions: expected array")
    else:
        for i,j in enumerate(junctions):
            p=f"$.junctions[{i}]"
            if not isinstance(j,Mapping): errors.append(f"{p}: expected object"); continue
            _require(j,["id","incident_film_ids"],p,errors)
            incident=j.get("incident_film_ids")
            if not isinstance(incident,list) or len(incident)<3: errors.append(p+".incident_film_ids: expected at least three films")
            elif any(fid not in film_ids for fid in incident): errors.append(p+".incident_film_ids: references unknown film")
    topology=data.get("topology")
    if not isinstance(topology,Mapping): errors.append("$.topology: expected object")
    else:
        _require(topology,["adjacency","events"],"$.topology",errors)
        for i,event in enumerate(topology.get("events",[])):
            p=f"$.topology.events[{i}]"
            if not isinstance(event,Mapping): errors.append(f"{p}: expected object"); continue
            _require(event,["id","type","time_s","provenance"],p,errors)
            if event.get("type") not in EVENT_TYPES: errors.append(p+".type: unsupported value")
            if "time_s" in event: _number(event["time_s"],p+".time_s",errors,nonnegative=True)
            if isinstance(event.get("time_s"),(int,float)) and isinstance(data.get("simulation_time_s"),(int,float)) and event["time_s"]>data["simulation_time_s"]:
                errors.append(p+".time_s: event occurs after frame time")
    return errors

def validate_scenario(data: Mapping[str,Any]) -> list[str]:
    errors=[]
    _require(data,["contract_version","kind","scenario_id","random_seed","requested_fidelity_tier","environment","initial_bubbles","user_editable"],"$",errors)
    if data.get("contract_version")!=CONTRACT_VERSION: errors.append(f"$.contract_version: expected {CONTRACT_VERSION}")
    if data.get("kind")!="SCENARIO": errors.append("$.kind: expected SCENARIO")
    if data.get("requested_fidelity_tier") not in FIDELITY_TIERS: errors.append("$.requested_fidelity_tier: unsupported value")
    seed=data.get("random_seed")
    if not isinstance(seed,int) or isinstance(seed,bool) or seed<0: errors.append("$.random_seed: expected non-negative integer")
    _environment(data.get("environment"),"$.environment",errors)
    bubbles=data.get("initial_bubbles")
    seen=set()
    if not isinstance(bubbles,list): errors.append("$.initial_bubbles: expected array")
    else:
        for i,b in enumerate(bubbles):
            _bubble(b,f"$.initial_bubbles[{i}]",errors)
            if isinstance(b,Mapping) and isinstance(b.get("id"),str):
                if b["id"] in seen: errors.append(f"$.initial_bubbles[{i}].id: duplicate {b['id']!r}")
                seen.add(b["id"])
    if not isinstance(data.get("user_editable"),Mapping): errors.append("$.user_editable: expected object")
    return errors

def assert_valid(data: Mapping[str,Any]) -> None:
    kind=data.get("kind")
    errors=validate_frame(data) if kind in {"FRAME","CHECKPOINT"} else validate_scenario(data) if kind=="SCENARIO" else ["$.kind: unsupported or missing"]
    if errors: raise ContractValidationError("\n".join(errors))
