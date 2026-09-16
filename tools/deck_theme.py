"""
One design system, shared by the slides and the figures drawn onto them.

It lives in its own module for a reason that showed up the hard way: the deck and the
charts had drifted into two different greys, two different blues and two different
typefaces, so every figure read as pasted in from another document. Anything that
appears on a slide and in a chart is defined here exactly once.

Two decisions are worth stating.

**The navy is not ours.** #1F497D is the official template's own theme colour `dk2`,
the one its "SMART INDIA HACKATHON 2026" title and every section heading are already
set in. Adopting it as our accent makes our content look native to the mandated
chrome instead of pasted onto it.

**Two hues, no more.** Navy is ours - our pipeline, our result, a target met. Rust is
the other thing - the feed-forward baseline, a target still open, the cost we have not
paid down. Because those two roles are genuinely the same axis, no third hue is needed
and none is used: no green ticks, no amber warnings. Everything else is grey.
"""
from __future__ import annotations

# --------------------------------------------------------------------------- colour
NAVY = "#1F497D"     # the template's own dk2. ours / measured / met
RUST = "#A8552F"     # the feed-forward baseline / open / the gap
INK = "#15181C"      # body text
MUTED = "#6B7480"    # secondary text and labels
FAINT = "#98A2AE"    # captions, tertiary detail
RULE = "#D5DBE3"     # hairlines
RULE_STRONG = "#A9B5C4"
WASH = "#F2F5F9"     # the only tint fill, cool, derived from the navy
PAPER = "#FFFFFF"

# --------------------------------------------------------------------------- type
SANS = "Segoe UI"            # body
SEMI = "Segoe UI Semibold"   # headings, statements, labels
MONO = "Consolas"            # every measured number, so digits align and read as output

# A real scale rather than "whatever fitted". Ratios, not arbitrary values.
T_HERO = 21.0    # a measured number that carries a slide
T_BIG = 15.5     # a number inside a row
T_STATE = 12.5   # the one-line statement under a slide title
T_HEAD = 10.5    # section heading within a slide
T_BODY = 9.2     # running text
T_SEC = 8.4      # secondary text
T_MICRO = 7.4    # captions and notes
T_EYEBROW = 7.0  # tracked-out uppercase label. used sparingly, not above every block

# --------------------------------------------------------------------------- grid
# The mandated chrome fixes the canvas: the footer bar starts at 6.95, the team badge
# occupies x < 1.73 and the SIH logo x > 10.70, both above y = 1.164.
SLIDE_W, SLIDE_H = 13.333, 7.5
L, R = 0.45, 12.88           # content margins
TOP, BOT = 1.18, 6.88        # content top and the last safe baseline above the footer
COLS, GUT = 12, 0.15
COLW = (R - L - (COLS - 1) * GUT) / COLS      # 0.8983 in


def X(n: float) -> float:
    """Left edge of column n."""
    return L + n * (COLW + GUT)


def SPAN(n: float) -> float:
    """Width of n columns including the gutters between them."""
    return n * COLW + (n - 1) * GUT


# Spacing tokens. Vertical rhythm comes from picking from this list, never from a
# freshly invented decimal.
XS, S, M, LG, XL = 0.07, 0.13, 0.22, 0.34, 0.52


# --------------------------------------------------------------------------- figures
# Authored size == placed size, so a point in a chart is the same physical size as a
# point on the slide. This is not a nicety: the old figures were drawn 9.2 in wide and
# placed at 5.9, so every label was silently scaled to 64% and the charts read as
# imported from another document. Both modules read these, so the two cannot drift.
FIG = {
    "beforeafter": (SPAN(6), 2.62),
    "accuracy": (SPAN(7), 2.00),
    "missions": (SPAN(6), 2.24),
    "timing": (SPAN(7), 1.30),
}
