# Performance study (October 2026)

Three LLM agents built prototypes and measured them on a laptop (4 cores, 7.7 GB RAM,
NVMe disk, shared with other programs). Test files were synthetic but realistic
(Bliss-like scans): up to 935 000 objects, one 8 GB dataset, a master file with
100 external links. Code and raw results are kept outside the repository; the numbers
below are medians.

## Approaches compared

| Name | Idea |
|---|---|
| Eager model | Read the whole file into memory, validate it with one generated pydantic model tree (what `nexusformat_pydantic` does today) |
| Lazy walk | Walk the file one object at a time; check each object against a lookup table from the schema; read only metadata and small values |
| Lazy walk + small models | As above, but each object is checked with a small per-member pydantic model |
| Per-object writer help | When a writer creates an object, look up its declaration and convert/check the value; on each append only compare dtype and shape |
| Generated views | Plain Python classes generated from the schema, giving typed access to a file without loading it |

## Results

### Validating existing files

| File | Eager model | Lazy walk | Lazy walk + small models |
|---|---|---|---|
| 935 000 small objects | 193 s, 449 MB | 170 s, 173 MB | 177 s, 174 MB |
| one 8 GB dataset | **fails** (out of memory) | 0.2 s, 130 MB | 0.3 s, 130 MB |
| master file, 100 external links, 1 GB of data | 5.5 s, 1074 MB | 3.7 s, 130 MB | 4.0 s, 130 MB |

- Cost is ~160–200 µs per object, linear in the number of objects, and does not depend
  on the size of the data. Most of it is h5py's Python overhead: the HDF5 C tool `h5ls`
  walks the same metadata at 26 µs per object, h5py's low-level API at 76 µs.
- Small pydantic models per object add only ~4 %.
- Reading every value of the 8 GB dataset (opt-in "full" checks) takes 6 s at constant
  memory (141 MB).

### Reading with schema help

| | Eager model | Generated views / lazy accessor |
|---|---|---|
| Time to the first value (100 000 objects) | 27 s | 0.3 s |
| 8 GB dataset | fails | 0.3 s, 123 MB |
| File with a few errors | no tree at all (validation error) | reads, reports findings |

- Generating models for every class in every context: 12 s and 620 MB per process.
  The NXDS bundle ships the same 1 292 specialisations as data: 0.14 s to load.

### Writing with schema help

| | Plain h5py | Per-object help | Whole-tree model, write at the end |
|---|---|---|---|
| 1 000 000 counter values (blocks of 1000) | 521 000/s | 535 000/s | 2 100 000/s but 2.8× the data in RAM |
| 300 frames 2048×2048 uint16 | baseline | same as plain | out of memory beyond ~1 GB of frames |
| Check of a file while it is written (partial mode) | — | 3–5 ms | not possible |

- Looking up a declaration costs 0.08 µs; checking a small value 1–3 µs; an h5py append
  costs ~85 µs. Per-object help is cheap enough to be always on.
- Never scan values of large frames while writing (as costly as writing the frame).

## Conclusions for NXDS

1. Validators, readers and writers must work **one object at a time** and read only
   metadata and small values by default. Memory then stays at 100–200 MB whatever the
   file size.
2. **One huge pydantic model of a whole file** is fine for small files (building a
   file in memory, tests, metadata-only files) but fails on real detector data, and a
   single error leaves a reader with nothing. Pydantic models **per class or per
   object** are cheap and useful.
3. The bundle must give **precomputed specialisations and lookup tables** (it does:
   1 292 specialisations load in 0.14 s), so tools never resolve inheritance.
4. The bundle must state which storage types are accepted, not one fixed width
   (a writer chose int64 instead of uint16 at first: 4× larger files).
5. The main remaining cost is h5py itself; a reference validator in C/Rust or using
   h5py's low-level API would be 2–6× faster for files with a million objects.
6. Issues found then: `nxds_tools validate` kept all findings in memory (fixed: it now streams
   them; whether it is still slow on one very large dataset is measured at the phase-1 checkpoint);
   `nexusformat_pydantic` rejected string-array attributes written by h5py (`@axes`) (to be fixed
   on its `design-nxds` branch).
