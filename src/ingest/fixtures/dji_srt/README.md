# DJI SRT fixtures

Twenty real sidecar files from `github.com/JuanIrache/DJI_SRT_Parser` (MIT, licence text
alongside), 2017 to 2022, covering the five format families listed in
`research/04-dji-srt-formats.md`. Read by `src/ingest/test_srt.py`.

Four files were multi-megabyte flights and are cut to their first few thousand lines,
ending on a block boundary; the format is what the fixture is for, not the flight. Byte
content, BOMs and CRLF are preserved through git by `.gitattributes` (`-text`), because
those are among the things under test.
