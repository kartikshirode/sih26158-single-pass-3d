# -*- coding: utf-8 -*-
"""
Who shot each clip, under what licence, and the credit line that has to travel with
anything published from it. `docs/16` section 4.1 is the prose version; this is the
copy the builders read.

One record, two surfaces. The gallery publishes the clip and a model beside it; the
console publishes runs and, for some of them, a mesh. Both are derived work and both
carry the source's terms, so neither may build a page for a clip that is not in here.
That is `refuse` below, and it exists because the failure it guards against is silent:
an unattributed clip renders perfectly and looks correct (`docs/16` T11, finding F-4).

Keyed by the clip's filename, which is what `run_manifest.json` records in `source`
and what `build_console.WITHHELD` already keys on, so there is one spelling of a clip
across the repo rather than a short name here and a filename there.
"""
from __future__ import annotations

# CC0 waives attribution; everything else requires the author by name, the licence,
# and a link back. CC 4.0 3(a)(1)(B) additionally requires saying the work was
# modified, which is true of every clip here: all are trimmed and re-encoded.
FOOTAGE = {
    "kolu.webm": {
        "title": "Kolu overpass", "author": None, "licence": "CC0",
        "licence_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "source_url": None,
    },
    "toolse.webm": {
        "title": "Toolse castle in Estonia (Fall 2021)", "author": "Sillerkiil",
        "licence": "CC BY-SA 4.0",
        "licence_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "source_url": "https://commons.wikimedia.org/wiki/File:Toolse_castle_in_Estonia_(Fall_2021).webm",
    },
    "bahai.webm": {
        "title": "Baha'i Temple -- Wilmette, IL -- Drone Video (DJI Spark)",
        "author": "Kurt Elster", "licence": "CC BY 3.0",
        "licence_url": "https://creativecommons.org/licenses/by/3.0/",
        "source_url": "https://commons.wikimedia.org/wiki/File:Baha%27i_Temple_--_Wilmette_,_IL_--_Drone_Video_(DJI_Spark).webm",
    },
}


def is_synthetic(source: str) -> bool:
    """A generated scene has no footage rights. `source` is the manifest's field."""
    return not str(source).startswith("video:")


def clip_of(source: str) -> str:
    """The clip filename a manifest's `source` refers to."""
    return str(source).split(":", 1)[-1]


def known(clip: str) -> bool:
    return clip in FOOTAGE


def share_alike(clip: str) -> bool:
    return "SA" in FOOTAGE[clip]["licence"]


def credit(clip: str, subject: str = "The 3D model", refuse=None,
           clip_published: bool = False) -> str:
    """The attribution line for one clip, as HTML.

    `subject` names where the derived model sits on the calling page, so the sentence
    reads correctly on a two-column gallery and on a console tab alike. Pass None when
    the page publishes no geometry from the clip, only facts about a run: there is then
    no adaptation to describe, and claiming one would be its own small inaccuracy.

    `refuse` is called with a message when the clip has no record. Callers pass
    `sys.exit`: a page that cannot attribute a clip must not be built at all, because
    shipping it unattributed is the failure and a missing line is invisible.
    """
    if clip not in FOOTAGE:
        msg = (f"no footage rights recorded for '{clip}' - add it to tools/footage.py "
               f"(docs/16 section 4.1) before it goes on a public page")
        if refuse is None:
            raise KeyError(msg)
        refuse(msg)
    f = FOOTAGE[clip]
    lic = (f'<a href="{f["licence_url"]}" rel="license noopener" '
           f'target="_blank">{f["licence"]}</a>')
    if f["author"] is None:
        return f'Source clip: {f["title"]}, {lic}. No attribution required.'
    src = f["title"]
    if f["source_url"]:
        src = f'<a href="{f["source_url"]}" rel="noopener" target="_blank">{src}</a>'
    out = f'Source clip: {src} by {f["author"]}, {lic}.'
    if subject is None:
        return out
    # CC 4.0 3(a)(1)(B) wants modification indicated. Where the clip itself is served
    # that means saying it was cut and re-encoded; where only the model is served, the
    # sentence below already says it is derived, and claiming the clip is "on this
    # page" would be false.
    if clip_published:
        out += " Trimmed and re-encoded for this page."
    if share_alike(clip):
        # A reconstruction is an adaptation, so share-alike reaches it. Saying nothing
        # would leave a viewer unable to tell what they may do with the model.
        out += f' {subject} is derived from it and is shared under the same licence, {lic}.'
    else:
        out += f' {subject} is derived from it.'
    return out
