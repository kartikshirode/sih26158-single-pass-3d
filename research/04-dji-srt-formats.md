# DJI SRT sidecar formats, from twenty real files (EXP-23)

Date: 2026-09-22. Status: done. Test: `python src/ingest/test_srt.py` (65 checks).

## Why this was worth a day

`docs/12` EXP-23 had topped the queue for weeks because it needs no data, and the finale
hands over unseen footage for 36 hours. A sidecar that parses to nothing is a run with no
georeference and no way to say why. Two such failures were already in the code and no
synthetic test had caught them, because the synthetic SRT was written by the same author
as the parser.

## Sources

| | |
|---|---|
| Fixtures | 20 files from `JuanIrache/DJI_SRT_Parser` (MIT), vendored under `src/ingest/fixtures/dji_srt/` with its LICENSE. 6 KB to 12 MB, 2017 to 2022, Mavic Pro through Mavic 3, Matrice 300, Phantom 4 RTK. |
| Reference interpretation | that parser's `index.js` (`interpretItem`): the tuple order, the `M` suffix rule, the `FNUM > 50` scaling, the `H` / `BAROMETER` / `REL_ALT` aliases |
| Newer models | `callmarcus.github.io/dji-drone-metadata-embedder/SRT_FORMATS/`: Mini 3/4 Pro, Air 3/3S, Mini 5 Pro, Mavic 4 Pro, Avata 2/360, Neo 2 |
| Enterprise | DJI support note "What information does Zenmuse H20N video subtitles contain?" (customId `en-us03400006657`): field list, no sample |

## The families

| Family | Models (from the fixtures and the format page) | Position | Height above take-off | Time |
|---|---|---|---|---|
| Bracket, modern | Mavic 3, Mini 3/4/5 Pro, Air 3/3S, Mavic 4 Pro, Avata 2 | `[latitude: 3.41531] [longitude: -3.37440]` | `[rel_alt: -2.400 abs_alt: 0.401]` | `FrameCnt: 1, DiffTime: 20ms` + `-->` line per frame; `2021-12-25 12:27:52.373` |
| Bracket, Mavic 2 era | Mavic 2 Pro/Zoom, Air 2/2S, Zenmuse H20 | `[latitude : 31.45] [longtitude : 74.40]` (misspelt) | `[altitude: 213.98]` on Air 2/2S; **absent** on Mavic 2 Pro | `FrameCnt`/`SrtCnt`; `2020-04-02 15:19:58,720,764` |
| Bracket, no timing | Mavic 2, early firmware | as above | absent | no `-->` line at all; `2017.08.05 14:11:51,393,525` per block, 1 Hz |
| Tuple, legacy | Mavic Pro, Phantom 4 Pro, Mavic Mini, P4 RTK, Matrice 300 | `GPS(149.0251,-20.2533,16)` or `GPS (-58.85, -34.24, 15)` | `BAROMETER:1.9`, `Hb:1.9`, `H 85.80m` | one block per second |
| None | Mavic Air (2018) | exposure fields only | | |

Encodings inside the bracket family: `fnum : 280` means f/2.8 and `focal_len : 240` means
24 mm up to the Air 2S; the Mavic 3 generation writes `fnum: 3.2` and `focal_len: 24.00`
literally. The parser divides `focal_len` by ten above 100 and flags it `focal_len_x10`.
That heuristic is wrong for a Zenmuse H20 at long zoom, whose *equivalent* focal length
legitimately exceeds 100 mm; the H20N note lists `dzoom` next to `focal_len`, and a zoomed
enterprise clip needs `dzoom` read before the division is trusted. Not done; no fixture.

## Three things the files say that the documentation does not

**1. The legacy tuple is `(longitude, latitude, satellites)`.** Every non-M300 fixture
puts longitude first: `GPS(149.0251,-20.2533,16)` is Queensland, `GPS (-121.7458, 48.0771,
17)` is Washington state, `GPS (8.2090, 47.4692, 18)` is Zurich. The third number is the
fix count, not an altitude; heights come from `BAROMETER`, `Hb` or `H`. Two web write-ups
paraphrase this as `GPS(lat,lon,alt)`, which is wrong on both counts. The Matrice 300 form
`GPS(36.6146,-6.1120,0.0M)` is the one exception, `(lat, lon, precision)`, and the `M`
suffix is the discriminator the reference parser uses. For India this matters more than
elsewhere: latitude 28 and longitude 77 are both under 90, so no range check can recover
a swapped pair.

**2. `longitude` never matched.** The pattern was `long?titude`, which is "lontitude" or
"longtitude". Every Mavic 3 / Mini 3 / Air 3 file, and the project's own synthetic SRT,
parsed to zero records, and the run reported `srt_records 0` exactly as it does for a
clip with no sidecar. Nothing distinguished the two. Now `longt?itude`.

**3. Positional keyframe lookup was wrong by a factor of thirty on half the families.**
`tel_all[frame_index]` assumed one record per video frame. The legacy families write one
record per second, so frame 300 of a 30 fps clip was handed the record from five minutes
in. The modern families do write one per frame, but the parser drops blocks without a
fix, which shifts every later index. `telemetry_for_frames` now keys on `FrameCnt` when
every record has it, else on the timing line, else returns nothing (`docs/09` S1
GAP C-3, now corrected). The time side uses each keyframe's presentation timestamp
from PyAV. It used index / average frame rate until 2026-09-25, which drifts on a
variable-frame-rate clip: a frame shown at 3.0 s got the 1 s fix (audit F-13).

## What the record carries now

`latitude`, `longitude`, `height` (metres above take-off or `None`, never a silent 0.0),
`t_us` (from the `-->` line, or from the wall clock when there is no timing line, flagged
`t_from_wall_clock`), `wall_us`, `frame_cnt`, `satellites`, `focal_len` in mm, `gb_yaw`,
`gb_pitch`, `abs_alt`, and `flags`. `abs_alt` stays barometric (`abs_alt - rel_alt` is
constant to the millimetre across a real flight) and is never used as a GNSS height.
`rel_alt` is still not an ellipsoidal height, which is `docs/13` item 4 in the plan and
untouched here.

## Fuzz results

21 deformations, zero exceptions: CRLF, BOM, UTF-16, 10 KB of binary, empty, index-only,
truncated mid-block, no `-->` line, no `rel_alt`, `longtitude`, both unit encodings,
`GPS(0,0)` before a fix (dropped), latitude 95.5 (dropped), `nan`/`inf` (dropped), a
400-digit number, a 1 MB line, both families in one file, and five date spellings of which
two are impossible. The invariant checked over all 20 fixtures: every record is on the
planet and under 10 km.

## Not covered

Autel's `GPS(W:6.1,N:36.6,10.0m)` form (the reference parser handles it; no fixture here).
Files in radians (the reference parser detects them by bounding box; none among the
fixtures). Embedded `djmd` / `mov_text` streams, CSV and flight-log exports (`docs/09` S1
lists them; only the sidecar path exists, and `docs/17` §4.2's "which parser matched?"
step still cannot run). Any file from a 2024 or later aircraft: the format page describes
them, the fixtures stop at the Mavic 3.
