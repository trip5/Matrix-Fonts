#!/usr/bin/env python3
"""
bdf2adafruit3.py — Convert BDF bitmap font to Adafruit GFXfont header (Python 3)

Three operating modes:
  1. Passthrough    — no --height/--width given; no normalisation, variable-width OK
  2. Height only    — --height H given; height normalised (±2 tolerance), width free
  3. Full target    — --height H --width W; both dimensions normalised (±2H, ±1W)

When normalising, the converter detects the font's bounding-box size and applies
smart padding/cutting rules. Interactive prompts let the user choose which rows
or columns to trim when cutting is required.

Usage:
    py bdf2adafruit3.py MatrixChunky8.bdf 0x0020 0x04FF -o MatrixChunky8.h
    py bdf2adafruit3.py MatrixLight8.bdf 0x20 0x04FF --auto -o MatrixLight8.h
    py bdf2adafruit3.py MatrixChunky8x6.bdf --height 6 -o MatrixChunky8x6.h
    py bdf2adafruit3.py SomeMonoFont.bdf --height 8 --width 6 -o out.h

Options:
    --height H   Target cell height in rows (optional, ±2 tolerance for trimming)
    --width W    Target cell width in columns (requires --height, ±1 tolerance)
    --auto       Use default choices for padding/cutting (non-interactive).
    --yes        Same as --auto.

Copyright (c) 2026 Trip5
SPDX-License-Identifier: GPL-3.0-only

This script is untested.  It is an adaptation of the one used by ehRadio.

"""

import sys
import re
import os


# ---------------------------------------------------------------------------
# BDF parser
# ---------------------------------------------------------------------------

class Glyph:
    __slots__ = ('encoding', 'name', 'advance', 'width', 'height',
                 'xoffs', 'yoffs', 'rows')
    def __init__(self):
        self.encoding = -1
        self.name = ''
        self.advance = 0
        self.width = 0
        self.height = 0
        self.xoffs = 0
        self.yoffs = 0
        self.rows = []


def parse_bdf(filepath: str):
    """Parse a BDF file and return (glyphs dict, ascent, descent)."""
    glyphs = {}
    ascent = 8
    descent = 0
    current = None
    bitmap_mode = False

    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.rstrip('\n\r')
            if not line:
                continue

            if line.startswith('FONT_ASCENT'):
                ascent = int(line.split()[1])
            elif line.startswith('FONT_DESCENT'):
                descent = int(line.split()[1])

            if line.startswith('STARTCHAR'):
                current = Glyph()
                current.name = line.split(None, 1)[1]
                bitmap_mode = False
                continue

            if current is None:
                continue

            if line.startswith('ENDCHAR'):
                if current.encoding >= 0:
                    glyphs[current.encoding] = current
                current = None
                bitmap_mode = False
                continue

            if line.startswith('ENCODING'):
                current.encoding = int(line.split()[1])
            elif line.startswith('DWIDTH'):
                current.advance = int(line.split()[1])
            elif line.startswith('BBX'):
                parts = line.split()
                current.width = int(parts[1])
                current.height = int(parts[2])
                current.xoffs = int(parts[3])
                current.yoffs = int(parts[4])
            elif line.startswith('BITMAP'):
                bitmap_mode = True
            elif bitmap_mode:
                current.rows.append(int(line.strip(), 16))

    return glyphs, ascent, descent


def is_empty_glyph(g: Glyph) -> bool:
    """Check if glyph has no visible pixels."""
    return all(r == 0 for r in g.rows) or len(g.rows) == 0


# ---------------------------------------------------------------------------
# Font validation
# ---------------------------------------------------------------------------

def detect_variable_width(glyphs: dict):
    """Return True if different glyphs have different DWIDTH (advance) values."""
    advances = set()
    for g in glyphs.values():
        if not is_empty_glyph(g):
            advances.add(g.advance)
    return len(advances) > 1


def get_uniform_dwidth(glyphs: dict):
    """Return the DWIDTH if all non-empty glyphs share the same one, else 0."""
    advances = set()
    for g in glyphs.values():
        if not is_empty_glyph(g):
            advances.add(g.advance)
    if len(advances) == 1:
        return advances.pop()
    return 0


def detect_max_width(glyphs: dict):
    """Return max BBX width across all non-empty glyphs."""
    max_w = 0
    for g in glyphs.values():
        if not is_empty_glyph(g):
            if g.width > max_w:
                max_w = g.width
    return max_w


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------

AUTO_MODE = False


def ask_choice(question: str, options: list, default: int = 0):
    """Ask user to pick from a numbered list. Returns chosen index (0-based)."""
    print(f"\n  {question}", file=sys.stderr)
    for i, opt in enumerate(options):
        marker = " (default)" if i == default else ""
        print(f"    [{i+1}] {opt}{marker}", file=sys.stderr)

    if AUTO_MODE:
        print(f"  --auto: choosing [{default+1}] {options[default]}", file=sys.stderr)
        return default

    while True:
        try:
            resp = input(f"  Choose [1-{len(options)}] (default {default+1}): ").strip()
            if resp == '':
                return default
            choice = int(resp) - 1
            if 0 <= choice < len(options):
                return choice
        except (ValueError, EOFError, KeyboardInterrupt):
            pass
        print(f"  Please enter 1-{len(options)}.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Glyph normalisation
# ---------------------------------------------------------------------------

def normalise_height(rows: list, strategy: str, yoffs: int, target_h: int) -> list:
    """
    Normalise glyph rows to *target_h* using the font-level strategy
    and the glyph's BBX yoffs for correct vertical positioning.

    BBX yoffs = distance from baseline (Y=0) to the bottom of the bitmap.
    In a *target_h*-row cell: baseline = just below row (target_h-1), so:
      - bottom padding = yoffs rows
      - glyph rows in the middle
      - top padding = remainder
    """
    result = list(rows)

    # 1. Apply font-level cutting strategy (uniform across all glyphs)
    if strategy == 'top':
        result = result[1:]
    elif strategy == 'bottom':
        result = result[:-1]
    elif strategy == '1+1':
        result = result[1:-1]
    elif strategy == '2top':
        result = result[2:]
    elif strategy == '2bottom':
        result = result[:-2]
    # 'none', 'pad-bottom', 'pad-both' — no cutting

    # 2. Position using yoffs
    bottom_pad = max(0, yoffs)
    top_pad = target_h - len(result) - bottom_pad
    if top_pad < 0:
        result = result[:target_h - bottom_pad]
        top_pad = 0

    result = [0] * top_pad + result + [0] * bottom_pad
    result = result[:target_h]
    while len(result) < target_h:
        result.append(0)

    return result


def normalise_width_columns(rows: list, w: int, strategy: str, target_w: int) -> list:
    """
    Normalise glyph rows from width *w* to *target_w* columns.
    Each row is an int with MSB = leftmost pixel.
    Returns list of ints (*target_w* bits significant, left-aligned).
    """
    if w == target_w or strategy == 'none':
        return list(rows)

    if strategy == 'simple':
        if w <= target_w:
            return list(rows)
        else:
            mask = ((1 << target_w) - 1) << (8 - target_w)
            return [r & mask for r in rows]

    # Padding case: w < target_w — keep bits left-aligned, packer handles rest
    if w < target_w:
        return list(rows)

    # Cutting case: w > target_w — need to remove (w - target_w) columns
    cut_total = w - target_w
    mask = ((1 << target_w) - 1) << (8 - target_w)

    # Map strategy → how many columns to shift off the left side
    shift_map = {
        'left':     cut_total,
        'right':    0,
        '1+1':      1,
        '2left':    2,
        '2right':   0,
        '3left':    3,
        '3right':   0,
        'balanced': 2,
    }
    shift = shift_map.get(strategy, 0)

    return [(r << shift) & mask for r in rows]


# ---------------------------------------------------------------------------
# Determine strategies (interactive or auto)
# ---------------------------------------------------------------------------

def determine_height_strategy(h: int, target_h: int) -> str:
    """Determine height normalisation strategy. Returns strategy string."""
    if h == target_h:
        return 'none'
    elif h == target_h - 1:
        print(f"  Height = {h}: adding 1 padding row at bottom → {target_h}",
              file=sys.stderr)
        return 'pad-bottom'
    elif h == target_h - 2:
        print(f"  Height = {h}: adding 1 padding row at top + 1 at bottom → {target_h}",
              file=sys.stderr)
        return 'pad-both'
    elif h == target_h + 1:
        print(f"  Height = {h}: need to cut 1 row to reach {target_h}.",
              file=sys.stderr)
        choice = ask_choice(
            "Which row should be removed?",
            ["Cut top row (discard uppermost pixels)",
             "Cut bottom row (discard lowermost pixels)"],
            default=0
        )
        strategy = 'top' if choice == 0 else 'bottom'
        print(f"  → Cutting {strategy} row.", file=sys.stderr)
        return strategy
    elif h == target_h + 2:
        print(f"  Height = {h}: need to cut 2 rows to reach {target_h}.",
              file=sys.stderr)
        choice = ask_choice(
            "How should the 2 rows be removed?",
            ["Cut 1 from top + 1 from bottom (balanced)",
             "Cut 2 from top (discard 2 uppermost rows)",
             "Cut 2 from bottom (discard 2 lowermost rows)"],
            default=0
        )
        strategies = {0: '1+1', 1: '2top', 2: '2bottom'}
        strategy = strategies[choice]
        print(f"  → Strategy: {strategy}.", file=sys.stderr)
        return strategy
    else:
        return 'reject'


def determine_width_strategy(w: int, target_w: int) -> str:
    """Determine width normalisation strategy. Returns strategy string."""
    if w == target_w:
        return 'none'
    elif w == target_w - 1:
        print(f"  Width = {w}: adding 1 padding column on right → {target_w}",
              file=sys.stderr)
        return 'pad-right'
    elif w == target_w + 1:
        print(f"  Width = {w}: need to cut 1 column to reach {target_w}.",
              file=sys.stderr)
        choice = ask_choice(
            "Which column should be removed?",
            ["Cut leftmost column (remove first pixel of each row)",
             "Cut rightmost column (remove last pixel of each row)"],
            default=0
        )
        strategy = 'left' if choice == 0 else 'right'
        print(f"  → Cutting {strategy}most column.", file=sys.stderr)
        return strategy
    elif w == target_w + 2:
        print(f"  Width = {w}: need to cut 2 columns to reach {target_w}.",
              file=sys.stderr)
        choice = ask_choice(
            "How should the 2 columns be removed?",
            ["Cut 2 from left (remove 2 leftmost pixels)",
             "Cut 2 from right (remove 2 rightmost pixels)",
             "Cut 1 from left + 1 from right (balanced)"],
            default=2
        )
        strategies = {0: '2left', 1: '2right', 2: '1+1'}
        strategy = strategies[choice]
        print(f"  → Strategy: {strategy}.", file=sys.stderr)
        return strategy
    elif w == target_w + 3:
        print(f"  Width = {w}: need to cut 3 columns to reach {target_w}.",
              file=sys.stderr)
        choice = ask_choice(
            "How should the 3 columns be removed?",
            ["Cut 3 from left",
             "Cut 3 from right",
             "Cut 2 from left + 1 from right (balanced)"],
            default=2
        )
        strategies = {0: '3left', 1: '3right', 2: 'balanced'}
        strategy = strategies[choice]
        print(f"  → Strategy: {strategy}.", file=sys.stderr)
        return strategy
    else:
        return 'reject'


# ---------------------------------------------------------------------------
# Bitmap packing
# ---------------------------------------------------------------------------

def pack_bitmap_rows(rows: list, width: int) -> list:
    """
    Pack a list of row ints (MSB=left pixel, *width* columns) into a byte array.
    Standard GFXfont 1bpp format: scan left-to-right, top-to-bottom, MSB-first.
    """
    packed = []
    bit_acc = 0
    bit_count = 0

    for row_val in rows:
        for col in range(width):
            mask = 0x80 >> col
            bit = 1 if (row_val & mask) else 0
            bit_acc = (bit_acc << 1) | bit
            bit_count += 1
            if bit_count == 8:
                packed.append(bit_acc)
                bit_acc = 0
                bit_count = 0

    if bit_count > 0:
        bit_acc <<= (8 - bit_count)
        packed.append(bit_acc)

    return packed


# ---------------------------------------------------------------------------
# Output generation
# ---------------------------------------------------------------------------

NULL_GLYPH_DESC = (0, 0, 0, 0, 0, 0)


def generate_header(glyphs_dict, first_cp, last_cp, font_name: str,
                    h_strategy: str, w_strategy: str,
                    orig_w: int, orig_h: int,
                    target_w, target_h, y_advance, mode: str):
    """
    Generate the complete GFXfont .h file.

    *mode* is 'passthrough', 'height-only', or 'full' and controls
    whether glyph descriptors use uniform or per-glyph dimensions.
    """
    prefix = re.sub(r'[^a-zA-Z0-9]', '_', font_name)
    if not prefix[0].isalpha():
        prefix = 'F_' + prefix

    range_size = last_cp - first_cp + 1

    lines = []
    lines.append('#pragma once')
    lines.append('#include <Adafruit_GFX.h>')
    lines.append('')
    lines.append(f'// Font: {font_name}')
    if mode == 'passthrough':
        lines.append(f'// Original BBX: {orig_w}×{orig_h}  —  passthrough (no normalisation)')
    elif mode == 'height-only':
        lines.append(f'// Original BBX: {orig_w}×{orig_h}  →  normalised height to {target_h} (width per-glyph)')
    else:
        lines.append(f'// Original BBX: {orig_w}×{orig_h}  →  normalised to {target_w}×{target_h}')
    lines.append(f'// Height strategy: {h_strategy},  Width strategy: {w_strategy}')
    lines.append(f'// Range: 0x{first_cp:04X}-0x{last_cp:04X}  ({range_size} slots)')
    if mode == 'passthrough':
        lines.append(f'// yAdvance: {y_advance}')
    else:
        lines.append(f'// yAdvance: {y_advance},  yOffset: -{target_h} (glcdfont-style)')
    lines.append('')

    # Build glyph array
    all_bitmaps = []
    glyph_descriptors = []

    for cp in range(first_cp, last_cp + 1):
        g = glyphs_dict.get(cp)
        if g is None:
            glyph_descriptors.append(NULL_GLYPH_DESC)
        elif is_empty_glyph(g):
            glyph_descriptors.append((0, 0, 0, g.advance, 0, 0))
        else:
            if mode == 'passthrough':
                # No normalisation — use glyph as-is
                norm_rows = g.rows
                gw = g.width
                gh = g.height
            elif mode == 'height-only':
                # Normalise height only; width stays per-glyph
                norm_rows = normalise_height(g.rows, h_strategy, g.yoffs,
                                              target_h)
                gw = g.width
                gh = target_h
            else:  # 'full'
                norm_rows = normalise_height(g.rows, h_strategy, g.yoffs,
                                              target_h)
                norm_rows = normalise_width_columns(norm_rows, g.width,
                                                     w_strategy, target_w)
                gw = target_w
                gh = target_h

            offset = len(all_bitmaps)
            packed = pack_bitmap_rows(norm_rows, gw)
            all_bitmaps.extend(packed)

            if mode == 'passthrough':
                yoffs_out = -gh
            else:
                yoffs_out = -target_h

            glyph_descriptors.append(
                (offset, gw, gh, g.advance, g.xoffs, yoffs_out)
            )

    # Write bitmap data
    lines.append(f'const uint8_t {prefix}Bitmaps[] PROGMEM = {{')
    for i in range(0, len(all_bitmaps), 12):
        chunk = all_bitmaps[i:i + 12]
        hex_vals = ', '.join(f'0x{b:02X}' for b in chunk)
        lines.append(f'    {hex_vals},')
    lines.append('};')
    lines.append('')

    # Write glyph descriptors
    lines.append(f'const GFXglyph {prefix}Glyphs[] PROGMEM = {{')
    for desc, cp in zip(glyph_descriptors, range(first_cp, last_cp + 1)):
        offset, w, h, adv, xo, yo = desc
        g = glyphs_dict.get(cp)
        name = g.name if g and not is_empty_glyph(g) else '(empty)'
        lines.append(
            f'    {{ {offset}, {w}, {h}, {adv}, {xo}, {yo} }},'
            f' /* 0x{cp:04X} {name} */'
        )
    lines.append('};')
    lines.append('')

    # GFXfont struct
    lines.append(f'const GFXfont {prefix} PROGMEM = {{')
    lines.append(f'    (uint8_t *){prefix}Bitmaps,')
    lines.append(f'    (GFXglyph *){prefix}Glyphs,')
    lines.append(f'    0x{first_cp:04X},  /* first */')
    lines.append(f'    0x{last_cp:04X},   /* last */')
    lines.append(f'    {y_advance}         /* yAdvance */')
    lines.append('};')
    lines.append('')

    # Stats
    non_empty = sum(1 for d in glyph_descriptors if d != NULL_GLYPH_DESC)
    lines.append(
        f'// {non_empty} glyphs in range ({range_size} slots),'
        f' {len(all_bitmaps)} bytes bitmap data,'
        f' {range_size * 6} bytes glyph table'
    )

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global AUTO_MODE

    if len(sys.argv) < 2:
        print(f'Usage: {sys.argv[0]} <font.bdf> [first_cp last_cp] '
              f'[-o output.h] [--auto|--yes] [--height H] [--width W]',
              file=sys.stderr)
        sys.exit(1)

    bdf_path = sys.argv[1]

    # ------------------------------------------------------------------
    # Parse optional arguments
    # ------------------------------------------------------------------
    output_path = None
    AUTO_MODE = False
    target_h = None
    target_w = None

    # Check for --auto / --yes
    if '--auto' in sys.argv:
        AUTO_MODE = True
        sys.argv.remove('--auto')
    if '--yes' in sys.argv:
        AUTO_MODE = True
        sys.argv.remove('--yes')

    # Check for -o output file
    if '-o' in sys.argv:
        idx = sys.argv.index('-o')
        if idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]
            sys.argv = sys.argv[:idx] + sys.argv[idx + 2:]

    # Check for --height H
    if '--height' in sys.argv:
        idx = sys.argv.index('--height')
        if idx + 1 < len(sys.argv):
            try:
                target_h = int(sys.argv[idx + 1])
            except ValueError:
                print(f'ERROR: --height requires an integer, got "{sys.argv[idx+1]}"',
                      file=sys.stderr)
                sys.exit(1)
            if target_h < 1:
                print(f'ERROR: --height must be ≥ 1, got {target_h}',
                      file=sys.stderr)
                sys.exit(1)
            sys.argv = sys.argv[:idx] + sys.argv[idx + 2:]
        else:
            print('ERROR: --height requires a value', file=sys.stderr)
            sys.exit(1)

    # Check for --width W
    if '--width' in sys.argv:
        idx = sys.argv.index('--width')
        if target_h is None:
            print('ERROR: --width requires --height to also be specified.',
                  file=sys.stderr)
            sys.exit(1)
        if idx + 1 < len(sys.argv):
            try:
                target_w = int(sys.argv[idx + 1])
            except ValueError:
                print(f'ERROR: --width requires an integer, got "{sys.argv[idx+1]}"',
                      file=sys.stderr)
                sys.exit(1)
            if target_w < 1:
                print(f'ERROR: --width must be ≥ 1, got {target_w}',
                      file=sys.stderr)
                sys.exit(1)
            sys.argv = sys.argv[:idx] + sys.argv[idx + 2:]
        else:
            print('ERROR: --width requires a value', file=sys.stderr)
            sys.exit(1)

    # Determine mode
    mode = 'passthrough'
    if target_h is not None:
        mode = 'height-only' if target_w is None else 'full'

    # ------------------------------------------------------------------
    # Parse BDF
    # ------------------------------------------------------------------
    glyphs_dict, ascent, descent = parse_bdf(bdf_path)
    print(f'Parsed {len(glyphs_dict)} glyphs.  Ascent={ascent}, Descent={descent}',
          file=sys.stderr)

    if not glyphs_dict:
        print('ERROR: No glyphs found in BDF file!', file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Validate font
    # ------------------------------------------------------------------
    non_empty = sorted(cp for cp, g in glyphs_dict.items()
                       if not is_empty_glyph(g))
    if not non_empty:
        print('ERROR: All glyphs are empty!', file=sys.stderr)
        sys.exit(1)

    print(f'{len(non_empty)} non-empty glyphs.', file=sys.stderr)

    # Detect max BBX width and font height
    max_w = detect_max_width(glyphs_dict)
    font_height = ascent + descent
    print(f'Glyph BBX width: {max_w} columns  |  '
          f'Font height: {font_height} rows (ascent={ascent}+descent={descent})',
          file=sys.stderr)

    # ------------------------------------------------------------------
    # Variable-width check (only reject in full mode)
    # ------------------------------------------------------------------
    is_variable = detect_variable_width(glyphs_dict)
    if is_variable and mode == 'full':
        print('ERROR: Variable-width font detected!', file=sys.stderr)
        print('  Different glyphs have different DWIDTH (advance) values.',
              file=sys.stderr)
        print('  Width normalisation (--width) requires a fixed-width '
              '(monospace) font.', file=sys.stderr)
        advances_seen = {}
        for cp in sorted(glyphs_dict.keys()):
            g = glyphs_dict[cp]
            if not is_empty_glyph(g):
                a = g.advance
                if a not in advances_seen:
                    advances_seen[a] = cp
        for a, cp in sorted(advances_seen.items()):
            print(f'    DWIDTH={a}: example 0x{cp:04X}', file=sys.stderr)
        sys.exit(1)
    elif is_variable:
        print('  Variable-width font detected — accepted in '
              f'{mode} mode.', file=sys.stderr)

    # ------------------------------------------------------------------
    # Determine font name
    # ------------------------------------------------------------------
    font_name = 'CustomFont'
    with open(bdf_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.startswith('FAMILY_NAME'):
                font_name = line.split('"')[1] if '"' in line else \
                            line.split(None, 1)[1].strip()
                break

    # ------------------------------------------------------------------
    # Determine codepoint range
    # ------------------------------------------------------------------
    if len(sys.argv) >= 4:
        first_cp = int(sys.argv[2], 16) if sys.argv[2].startswith('0x') \
                   else int(sys.argv[2])
        last_cp = int(sys.argv[3], 16) if sys.argv[3].startswith('0x') \
                  else int(sys.argv[3])
        first_cp = max(first_cp, min(non_empty))
        last_cp = min(last_cp, max(non_empty))
    else:
        first_cp = min(non_empty)
        last_cp = max(non_empty)

    range_size = last_cp - first_cp + 1
    est_flash = range_size * 6

    print(f'Font name: {font_name}', file=sys.stderr)
    print(f'Range: 0x{first_cp:04X} — 0x{last_cp:04X} '
          f'({range_size} slots)', file=sys.stderr)
    print(f'Estimated glyph table: {est_flash} bytes '
          f'({est_flash / 1024:.1f} KB)', file=sys.stderr)

    if est_flash > 80000:
        print('WARNING: Glyph table is very large! Consider specifying a '
              'tighter range, e.g.:', file=sys.stderr)
        print('  py bdf2adafruit3.py font.bdf 0x0020 0x04FF',
              file=sys.stderr)

    # ------------------------------------------------------------------
    # Determine normalisation strategies
    # ------------------------------------------------------------------
    h_strategy = 'none'
    w_strategy = 'none'
    y_advance = font_height

    if mode == 'passthrough':
        print(f'\n--- Passthrough mode (no --height/--width) ---',
              file=sys.stderr)
        print(f'  yAdvance = font height = {font_height}', file=sys.stderr)

    elif mode == 'height-only':
        print(f'\n--- Normalising height to {target_h} ---',
              file=sys.stderr)
        min_h = target_h - 2
        max_h = target_h + 2

        if font_height < min_h or font_height > max_h:
            print(f'ERROR: Font height {font_height} is outside accepted '
                  f'range {min_h}-{max_h}.', file=sys.stderr)
            print(f'  The font must be within ±2 rows of the target height '
                  f'({target_h}).', file=sys.stderr)
            sys.exit(1)

        h_strategy = determine_height_strategy(font_height, target_h)
        if h_strategy == 'reject':
            print(f'ERROR: Cannot handle height {font_height}.',
                  file=sys.stderr)
            sys.exit(1)

        print(f'  Width: variable-width OK (per-glyph BBX width preserved).',
              file=sys.stderr)
        y_advance = target_h

    else:  # mode == 'full'
        print(f'\n--- Normalising to {target_w}×{target_h} ---',
              file=sys.stderr)
        min_h = target_h - 2
        max_h = target_h + 2
        min_w = target_w - 1
        max_w = target_w + 1

        # Height
        if font_height < min_h or font_height > max_h:
            print(f'ERROR: Font height {font_height} is outside accepted '
                  f'range {min_h}-{max_h}.', file=sys.stderr)
            print(f'  The font must be within ±2 rows of the target height '
                  f'({target_h}).', file=sys.stderr)
            sys.exit(1)

        h_strategy = determine_height_strategy(font_height, target_h)
        if h_strategy == 'reject':
            print(f'ERROR: Cannot handle height {font_height}.',
                  file=sys.stderr)
            sys.exit(1)

        # Width
        uniform_dw = get_uniform_dwidth(glyphs_dict)
        if uniform_dw == target_w:
            print(f'  DWIDTH is uniform = {target_w}: using per-glyph '
                  f'clip/pad.', file=sys.stderr)
            if max_w > target_w:
                print(f'  Wide glyphs (>{target_w} cols) will be '
                      f'right-clipped.', file=sys.stderr)
            w_strategy = 'simple'
        elif max_w < min_w or max_w > max_w:
            print(f'ERROR: Font width {max_w} is outside accepted '
                  f'range {min_w}-{max_w}.', file=sys.stderr)
            print(f'  The font must be within ±1 column of the target width '
                  f'({target_w}).', file=sys.stderr)
            sys.exit(1)
        else:
            w_strategy = determine_width_strategy(max_w, target_w)
            if w_strategy == 'reject':
                print(f'ERROR: Cannot handle width {max_w}.',
                      file=sys.stderr)
                sys.exit(1)

        y_advance = target_h

    # ------------------------------------------------------------------
    # Generate output
    # ------------------------------------------------------------------
    output = generate_header(glyphs_dict, first_cp, last_cp, font_name,
                             h_strategy, w_strategy,
                             max_w, font_height,
                             target_w, target_h, y_advance, mode)

    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f'\nWrote to {output_path}', file=sys.stderr)
    else:
        print(output)


if __name__ == '__main__':
    main()
