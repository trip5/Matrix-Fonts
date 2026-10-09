#!/usr/bin/env python3
"""
baseline_transform.py - Re-baseline a BDF bitmap font.

These fonts are typically drawn with the baseline at the very bottom edge of
every glyph (i.e. all rows sit ABOVE the baseline and there is no descender
space). "Normal" fonts usually reserve one row BELOW the baseline for
descenders (e.g. 7 rows above + 1 row below for an 8-row font).

This tool moves the baseline WITHOUT moving any pixels. It only rewrites the
vertical METRICS in the BDF file - the actual BITMAP hex data is never
touched or re-ordered.

For every glyph, the vertical offset of its bounding box (`BBX ... yoff`) is
shifted, and the font-level metrics (`FONT_ASCENT`, `FONT_DESCENT`,
`FONTBOUNDINGBOX`, `X_HEIGHT`, `CAP_HEIGHT`) are adjusted to match.

Usage
-----
    py baseline_transform.py MatrixChunky6.bdf
        -> writes MatrixChunky6_.bdf (baseline shifted up by 1 row)

    py baseline_transform.py MatrixChunky6.bdf -o MatrixChunky6_fixed.bdf
        -> writes to an explicit file

    py baseline_transform.py MatrixChunky6.bdf -s -2
        -> shift the baseline up by 2 rows (reserve 2 descender rows)

    py baseline_transform.py MatrixChunky6.bdf -s 1
        -> shift the baseline down by 1 row

Shift sign
----------
`-s` is the signed number of pixel rows added to each glyph's Y offset:

    negative -> baseline moves UP   (fewer rows above, adds descender space)
    positive -> baseline moves DOWN (more rows above)
    default  -> -1

Note: `-s -2` may confuse some shells; `--shift=-2` always works.
"""

import argparse
import os
import re
import sys


# ---------------------------------------------------------------------------
# Line patterns (we only ever rewrite the final integer on a matching line,
# preserving the original spacing and anything before it verbatim).
# ---------------------------------------------------------------------------

# Font-level single-value metrics: shift measured from the baseline.
_RE_FONT_ASCENT = re.compile(r'^(\s*FONT_ASCENT\s+)(-?\d+)(\s*)$')
_RE_FONT_DESCENT = re.compile(r'^(\s*FONT_DESCENT\s+)(-?\d+)(\s*)$')
_RE_X_HEIGHT = re.compile(r'^(\s*X_HEIGHT\s+)(-?\d+)(\s*)$')
_RE_CAP_HEIGHT = re.compile(r'^(\s*CAP_HEIGHT\s+)(-?\d+)(\s*)$')

# FONTBOUNDINGBOX width height xoff yoff  ->  shift yoff
_RE_FONT_BBOX = re.compile(
    r'^(\s*FONTBOUNDINGBOX\s+-?\d+\s+-?\d+\s+-?\d+\s+)(-?\d+)(\s*)$'
)

# Per-glyph: BBX width height xoff yoff  ->  shift yoff
_RE_GLYPH_BBX = re.compile(
    r'^(\s*BBX\s+-?\d+\s+-?\d+\s+-?\d+\s+)(-?\d+)(\s*)$'
)


def _shift_last_int(match, shift):
    """Return the line with the captured trailing integer shifted by *shift*."""
    prefix, value, suffix = match.group(1), int(match.group(2)), match.group(3)
    return f'{prefix}{value + shift}{suffix}'


def transform(content, shift):
    """
    Apply the baseline shift to *content* and return (new_content, stats).

    *content* is the whole BDF file as a string. Line endings are preserved.
    Only vertical metrics change; BITMAP data and every other line are copied
    through unchanged.
    """
    out_lines = []
    stats = {
        'ascent_before': None,
        'ascent_after': None,
        'descent_before': None,
        'descent_after': None,
        'bbox_before': None,
        'bbox_after': None,
        'glyphs': 0,
    }

    for line in content.splitlines(keepends=True):
        # Separate the body from its line ending so our regexes (anchored with
        # $) match cleanly, then re-append the ending untouched.
        if line.endswith('\r\n'):
            body, ending = line[:-2], '\r\n'
        elif line.endswith('\n') or line.endswith('\r'):
            body, ending = line[:-1], line[-1]
        else:
            body, ending = line, ''

        new_body = body

        m = _RE_FONT_ASCENT.match(body)
        if m:
            stats['ascent_before'] = int(m.group(2))
            stats['ascent_after'] = int(m.group(2)) + shift
            new_body = _shift_last_int(m, shift)
        else:
            m = _RE_FONT_DESCENT.match(body)
            if m:
                stats['descent_before'] = int(m.group(2))
                stats['descent_after'] = int(m.group(2)) - shift
                new_body = _shift_last_int(m, -shift)
            else:
                m = _RE_X_HEIGHT.match(body)
                if m:
                    new_body = _shift_last_int(m, shift)
                else:
                    m = _RE_CAP_HEIGHT.match(body)
                    if m:
                        new_body = _shift_last_int(m, shift)
                    else:
                        m = _RE_FONT_BBOX.match(body)
                        if m:
                            stats['bbox_before'] = int(m.group(2))
                            stats['bbox_after'] = int(m.group(2)) + shift
                            new_body = _shift_last_int(m, shift)
                        else:
                            m = _RE_GLYPH_BBX.match(body)
                            if m:
                                stats['glyphs'] += 1
                                new_body = _shift_last_int(m, shift)

        out_lines.append(new_body + ending)

    return ''.join(out_lines), stats


def default_output_path(input_path):
    """input.bdf -> input_.bdf  (same directory)."""
    root, ext = os.path.splitext(input_path)
    return f'{root}_{ext}'


def _is_same_file(path_a, path_b):
    """
    True if the two paths refer to the same file on disk.

    The input file is NEVER allowed to be overwritten, so this is used to
    hard-block any combination (including case-insensitive or symlinked
    paths) where the output would clobber the input.
    """
    try:
        # Robust when both paths already exist (handles hard links and
        # case-insensitive file systems, e.g. Windows).
        return os.path.samefile(path_a, path_b)
    except OSError:
        # Output doesn't exist yet - compare normalised absolute paths.
        return (os.path.normcase(os.path.realpath(path_a))
                == os.path.normcase(os.path.realpath(path_b)))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='baseline_transform.py',
        description='Re-baseline a BDF bitmap font by shifting the baseline '
                    'without moving any pixels.',
        epilog='Example: py baseline_transform.py MatrixChunky6.bdf -s -1',
    )
    parser.add_argument('input', help='input BDF font file')
    parser.add_argument('-o', '--output', default=None,
                        help='output BDF path (default: add "_" to the input '
                             'file name, e.g. MatrixChunky6_.bdf). Must '
                             'differ from the input - the input is never '
                             'overwritten.')
    parser.add_argument('-s', '--shift', type=int, default=-1,
                        help='signed rows to shift the baseline: negative = '
                             'up, positive = down (default: -1)')

    args = parser.parse_args(argv)

    input_path = args.input
    shift = args.shift

    if not os.path.isfile(input_path):
        print(f'Error: input file not found: {input_path}', file=sys.stderr)
        return 1

    output_path = args.output or default_output_path(input_path)

    # Hard rule: the input file is never overwritten. There is no option to
    # force it - if the output resolves to the input, we refuse and stop.
    if _is_same_file(output_path, input_path):
        print('Error: output path resolves to the input file; the input is '
              'never overwritten. Choose a different output path.',
              file=sys.stderr)
        return 1

    with open(input_path, 'r', encoding='utf-8', errors='replace',
              newline='') as f:
        content = f.read()

    if 'STARTFONT' not in content:
        print(f'Error: {input_path} does not look like a BDF font '
              '(no STARTFONT line).', file=sys.stderr)
        return 1

    if shift == 0:
        print('Note: shift is 0 - the output will be an identical copy.')

    new_content, stats = transform(content, shift)

    # Warn (but still write) if the shift pushed the ascent to zero or below.
    if stats['ascent_after'] is not None and stats['ascent_after'] <= 0:
        print(f'Warning: FONT_ASCENT would become '
              f'{stats["ascent_after"]} (<= 0). The font may be unusable.',
              file=sys.stderr)

    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        f.write(new_content)

    # --- Summary (ASCII only) ---
    if stats['ascent_before'] is not None:
        print(f'FONT_ASCENT : {stats["ascent_before"]} -> '
              f'{stats["ascent_after"]}')
    else:
        print('FONT_ASCENT : (not found in header)')
    if stats['descent_before'] is not None:
        print(f'FONT_DESCENT: {stats["descent_before"]} -> '
              f'{stats["descent_after"]}')
    else:
        print('FONT_DESCENT: (not found in header)')
    if stats['bbox_before'] is not None:
        print(f'FONTBOUNDINGBOX y-off: {stats["bbox_before"]} -> '
              f'{stats["bbox_after"]}')
    print(f'Glyphs shifted   : {stats["glyphs"]}')
    print(f'Baseline shift   : {shift:+d}')
    print(f'Written          : {output_path}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
