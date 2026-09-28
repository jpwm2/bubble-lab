import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { adaptFrame } from "../.build/src/adapter.js";
import { loadReplayBundle } from "../.build/src/runtimeBundle.js";

const viewerDir=fileURLToPath(new URL("../",import.meta.url));
const repoRoot=resolve(viewerDir,"../..");
async function json(path){return JSON.parse(await readFile(path,"utf8"));}

test("viewer loads an actual generated transient replay bundle with exact frames", async()=>{
  const out=await mkdtemp(join(tmpdir(),"bubble-runtime-viewer-"));
  try{
    const run=spawnSync("python3",[
      "bubblelab/runtime/tools/run_scenario.py",
      "bubblelab/scenarios/runtime/transient-wind.scenario.json",
      "--backend","transient","--frames","3","--output",out
    ],{cwd:repoRoot,encoding:"utf8"});
    assert.equal(run.status,0,run.stderr||run.stdout);
    const index=await json(join(out,"replay.json"));
    const loaded=await loadReplayBundle(index,(rel)=>json(join(out,rel)));
    assert.equal(loaded.frames.length,3);
    assert.equal(loaded.replay.frames.length,3);
    assert.deepEqual(loaded.frames.map(f=>f.simulation_time_s),loaded.replay.frames.map(f=>f.simulation_time_s));
    const data=adaptFrame(loaded.frames[1],{provenanceSource:"SOLVER",provenanceLabel:"Generated runtime bundle"});
    assert.equal(data.provenanceSource,"SOLVER");
    assert.equal(data.frame.manifest.solver.backend,index.backend.identity);
    assert.equal(data.surfaceMeshes[0].renderable,true);
    assert.ok(data.surfaceMeshes[0].vertices.length>0);
  }finally{await rm(out,{recursive:true,force:true});}
});

test("bundle loader surfaces missing and corrupt frame errors", async()=>{
  const index={
    bundle_version:"1.0.0",contract_version:"1.0.0",
    scenario:{id:"s",sha256:"x"},backend:{identity:"b",version:"1"},random_seed:1,
    frames:[{frame_id:"f",path:"frames/000000.json",simulation_time_s:0}],checkpoints:[],
    provenance:{producer:"test",source_scenario:"s"},
    fidelity:{requested:"HIGH_FIDELITY",produced:"HIGH_FIDELITY",feature_disclosures:{}}
  };
  await assert.rejects(()=>loadReplayBundle(index,async()=>{throw new Error("missing")}),/missing/);
  await assert.rejects(()=>loadReplayBundle({...index,frames:[{...index.frames[0],path:"../escape.json"}]},async()=>({})),/Unsafe/);
});
