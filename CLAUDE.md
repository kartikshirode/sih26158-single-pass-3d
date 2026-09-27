## Codemap

`.claude/codemap.md` is the file-level index of this repo. Rules:

- Read it before exploring: the Overview always, entries as needed. Once per session, run the staleness check: `git log -1 --format=%H -- .claude/codemap.md .claude/codemap/`, then `git diff --name-status -M <hash>..HEAD`, then `git status --porcelain`. Trust fresh entries instead of re-reading files; open only files the map does not cover or the check flags.
- When spawning subagents, put in their prompt: read `.claude/codemap.md` first, open only files it does not cover, never edit the map, report back which files you changed. Subagents do not inherit this CLAUDE.md, so this forwarding is mandatory.
- At end of turn, update map entries for every file changed this turn, whether you or a subagent changed it. Re-derive each entry from the file itself, never from memory of the edit, and fold the update into the same commit as the change.
- If an edit added or removed an import, also update the `Used by:` line of the file being imported (cap 8 names, then "and N more").
- Entry format: heading is the forward-slash path; then purpose, `Exports:`, `Used by:`, `Gotcha:`, four to five lines total. Trivial files get one line. The map is purely technical: no author names, no AI attribution.
- The map routes you to files; for destructive or security-sensitive work the file is the authority, not the entry.
