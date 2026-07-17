# overture2gmns benchmark & debugging environment

Self-comparison harness: build the same region with **osm2gmns** (reference)
and **overture2gmns** (candidate), validate both with **gmns-ready**, and
smoke-test both with **taplite4mpo** (dtalite_qa QA gate + TAPLite kernel).

## Pipeline

```
dev/osmmap/<region>.pbf ──step1──► bench/out/<region>/osm2gmns/{node,link}.csv
                                          │ (node extent → bbox)
Overture S3 ─────────────step2──► bench/out/<region>/overture2gmns/{node,link}.csv
                                          │
              step3: comparison_report.{md,json}   (counts, class lengths,
                                          │         speeds, connectivity,
                                          │         grid length correlation)
              step4: gmns_ready_report.txt per network
                                          │
              step5: tap_<tool>/ scenarios → dtalite_qa prepare → TAPLite
                     → taplite_report.json (VMT / VHT / max v/c diff)
```

Run everything for one region:

```bash
python bench/run_all.py tempe            # full pipeline
python bench/run_all.py tempe --skip-kernel   # skip the TAPLite solve
```

Or run steps individually (`step2` caches the Overture download in
`overture_raw/`; add `--no-cache` to re-download).

## Region ladder

| region   | source                     | size    | status |
|----------|----------------------------|---------|--------|
| tempe    | dev/osmmap/tempe.osm.pbf   | 4 MB    | ready  |
| chicago  | dev/osmmap/chicago.osm.pbf | 100 MB  | ready (BBBike metro extract) |
| mag_mpo  | dev/osmmap/mag_mpo_bbbike.pbf | 126 MB | ready (large) |
| arizona  | dev/osmmap/arizona.pbf     | 272 MB  | ready (xlarge) |

Work small→large: fix conversion discrepancies on Tempe, re-verify on Chicago
metro, then scale to MAG/Arizona (where streaming and runtime matter).

## Comparison methodology

- **Scope:** `auto` mode, drivable classes only (see `LINK_TYPES` in
  `config.py`). Footway/cycleway coverage differs too much between OSM-derived
  and Overture-derived networks to be a useful v1 signal.
- **Unit normalization:** osm2gmns emits meters & km/h; overture2gmns emits
  miles & mph. `step3`/`step5` normalize everything to miles/mph.
- **Same coverage:** the Overture bbox is derived from the osm2gmns node
  extent. Note the OSM extract may be polygon-clipped (BBBike) while Overture
  is rectangle-clipped, so expect the Overture network to be a superset near
  bbox corners — interpret count diffs together with the grid correlation.
- **Structural metrics:** node/link counts, directed length by road class,
  length-weighted mean speed/lanes per class, mean out-degree, weak-component
  count, largest-component share.
- **Spatial metric:** directed link length aggregated on a ~500 m grid;
  Pearson correlation between networks (near 1.0 = same streets present).
- **Behavioral metric (step5):** identical synthetic demand (all pairs among
  ~25 grid-sampled zone centroids inside the largest strongly connected
  component) assigned by TAPLite on both networks → VMT/VHT/max v/c diff.
  Two networks can look similar structurally and still route differently;
  this catches connectivity and speed/capacity attribution bugs.

## What "pass" means (alpha targets)

- gmns-ready `quick_check` / `validate_network` run clean on the
  overture2gmns output (no missing-column or dangling-reference errors).
- dtalite_qa `prepare()` returns ok with 0 access problems.
- TAPLite completes; |ΔVMT| and |ΔVHT| vs the osm2gmns network within ~15%
  on Tempe (expect real differences from map coverage, not just bugs).
- Grid length correlation ≥ 0.9.

## MPO reference networks (steps 7-8)

- `step7_mpo_qaqc.py {arc_atlanta,trm_triangle}` — QA an agency GMNS network
  (units/CRS registry in `mpo_config.py`): structure summary incl. centroid
  connector share, lon/lat normalized copy, gmns-ready + dtalite_qa reports.
- `pull_overture_for_mpo.py` — streamed Overture pull for the MPO urban core.
- `step8_mapmatch.py --probe A --base B` — cross-network QA by map matching
  (mapmatcher4gmns): link geometries of A become 50 m-spaced probe traces
  with headings, HMM-matched onto B. Trace/point match rates per facility
  class localize disagreement. The same machinery conflates INRIX/RITIS probe
  data, so the match rate doubles as probe-data readiness.

## Debugging loop

1. `comparison_report.md` shows *which class* diverges (e.g., missing
   residential links → check `link_types` mapping or Overture class filter).
2. `diagnostics.json` in the overture2gmns output counts skipped records and
   unresolved conditional rules — first place to look for dropped data.
3. `gmns_ready_report.txt` catches GMNS-format issues (columns, IDs, geometry).
4. `taplite_report.json` + `tap_*/kernel_log.txt` catch behavioral issues
   (unroutable zones, absurd speeds, zero capacities).
5. Fix in `src/overture2gmns/`, `pytest -q`, rerun `run_all.py tempe`.
