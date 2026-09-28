# Fragmentation research prototype

This directory is intentionally research-only. It does not add production fragmentation support to the accepted Bubble Lab solvers or contracts.

The prototype provides four pieces of executable evidence:

1. A deterministic geometric neck diagnostic based on cross-sectional area of the actual triangulated surface, oriented by the mesh principal axis. The diagnostic requires an interior area minimum with two-sided prominence and therefore rejects a merely elongated ellipsoid in the benchmark.
2. A deterministic separating-cut partition check on mesh faces. The cut is evidence that a candidate loop separates the closed surface into two sides; it is not a claim that direct mesh surgery resolves pinch-off dynamics.
3. Parent-to-children bookkeeping for target volume, gas amount, center of mass, momentum, lineage and stable IDs. Daughter restart geometry is explicitly marked as requiring physical relaxation, and surface energy across the singular event is left unresolved.
4. Three-resolution and rotated-mesh studies that gate the research trigger on convergence/stability rather than one coarse geometry snapshot.

The report renderer compares explicit front surgery, temporary level-set/VOF patches, local phase field, and hybrid front-tracking/Eulerian handoff. Based on the executable front-side evidence and the accepted solver architecture, it recommends a hybrid handoff: retain tracked fronts away from the singular event, refine the neck aggressively, hand a localized patch to a conservative Eulerian topology-capable method through pinch-off, then reconstruct deterministic child fronts and return to the tracked representation.

Commands used by Worker acceptance:

```sh
python3 -m unittest discover -s bubblelab/research/fragmentation/tests -v
python3 bubblelab/research/fragmentation/tools/run_benchmark.py neck-detection --assert
python3 bubblelab/research/fragmentation/tools/run_benchmark.py split-bookkeeping --assert
python3 bubblelab/research/fragmentation/tools/run_benchmark.py neck-resolution --assert
python3 bubblelab/research/fragmentation/tools/render_report.py --output /tmp/fragmentation-research.md
```
