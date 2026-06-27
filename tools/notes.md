# Unicode Fonts with the Adafruit GFX Library — Implementation Notes

This document covers what's needed to replace the stock 256-slot `glcdfont`
with a custom Unicode `GFXfont` that can render hundreds of glyphs across
Latin, Cyrillic, Greek, and extended punctuation.

It was adapted from a similar notes file in the ehRadio repository.

## Why Replace glcdfont?

The stock Adafruit GFX Library's `glcdfont.c` is a hardcoded 256-slot font
(5×7 pixels) covering only ASCII 0x00–0xFF, using compile-time codepage
tricks to swap character sets.

**Problems with glcdfont:**
- Requires compile-time codepage selection (Latin OR Cyrillic, never both)
- Cannot render accented Latin (é, ñ, ü), Greek, or mixed scripts
- No runtime font switching

**The Unicode GFXfont approach:**
- One font file can hold glyphs for thousands of codepoints
- Render any supported script at runtime — no codepage switching
- Accent folding fallback for missing glyphs (é→e, ñ→n, etc.)
- Same code path for all display drivers (OLED, TFT, LCD)

---

## Adafruit GFXfont Format Primer

A `GFXfont` is a C struct declared in PROGMEM:

```c
typedef struct {
  uint8_t  *bitmap;   // packed 1bpp bitmap data for all glyphs (MSB first per byte)
  GFXglyph *glyph;    // array of glyph descriptors, one per codepoint in the range
  uint16_t  first;    // first codepoint covered by the glyph array
  uint16_t  last;     // last codepoint covered by the glyph array
  uint8_t   yAdvance; // vertical line spacing (cursor_y step after newline)
} GFXfont;
```

Each `GFXglyph` descriptor:
```c
typedef struct {
  uint16_t bitmapOffset; // byte offset into font->bitmap
  uint8_t  width;        // bitmap width in pixels
  uint8_t  height;       // bitmap height in pixels
  uint8_t  xAdvance;     // cursor_x advance after rendering this glyph
  int8_t   xOffset;      // horizontal offset from cursor_x to first pixel column
  int8_t   yOffset;      // vertical offset from baseline (negative = above baseline)
} GFXglyph;
```

**Critical detail**: `xOffset + width` can exceed `xAdvance`. This is valid in
the GFXfont spec (glyphs can have overhang), but causes pixel bleed with
background-fill rendering. See [Glyph Bleed Clip](#glyph-bleed-clip).

---

## BDF → GFXfont Conversion

The font files used here are BDF (Glyph Bitmap Distribution Format). The
[`bdf2adafruit3.py`](bdf2adafruit3.py) script converts `.bdf` bitmap fonts to
Adafruit GFXfont `.h` headers.

### Usage

```bash
# Passthrough — no normalisation, variable-width OK
py bdf2adafruit3.py MyFont.bdf 0x0020 0x04FF -o MyFont.h

# Normalise to specific cell dimensions
py bdf2adafruit3.py MyFont.bdf 0x20 0x04FF --height 8 --width 6 --auto -o MyFont.h
```

### How normalisation works

If `--height`/`--width` targets are given and the font's native glyph size
differs from the target, the converter applies:
- **Height**: trim rows or pad with empty rows (±2 tolerance)
- **Width**: pad or cut columns (±1 tolerance, uniform-width font required)
- Interactive prompts let the user choose which rows/columns to trim

Without dimensions, the converter passes glyphs through unchanged (variable
widths and heights preserved).

---

## Overriding `write()` for Unicode

The stock `Adafruit_GFX::write(uint8_t c)` only handles single-byte ASCII.
To render Unicode (multi-byte UTF-8) you must override `write()` and provide
a custom glyph renderer.

The key pattern:

```cpp
// UTF-8 aware write() — decodes multi-byte sequences into a codepoint,
// then dispatches to a custom _writeGlyph(uint16_t cp).
size_t write(uint8_t c) {
    // ... UTF-8 decoder ...
    _writeGlyph(decoded_codepoint);
    return 1;
}
```

The custom glyph renderer looks up the codepoint in the `GFXfont`:

```cpp
void _writeGlyph(uint16_t cp) {
    const GFXfont *f = &DisplayFont;
    if (cp < f->first || cp > f->last) {
        // Not in font range — fallback handling
        return;
    }
    uint16_t idx = cp - f->first;
    GFXglyph *glyph = &(((GFXglyph *)pgm_read_ptr(&f->glyph))[idx]);
    uint8_t *bitmap = (uint8_t *)pgm_read_ptr(&f->bitmap);
    // ... render glyph at cursor position ...
}
```

---

## Critical Rendering Issues and Fixes

### Glyph Bleed Clip

**Problem**: Some GFXfont glyphs have `xOffset + width > xAdvance`.
When rendering with background fill, the extra pixel columns bleed into
the next character's cell, causing smearing.

**Fix**: Only render columns within the `xAdvance` boundary:

```cpp
for (uint8_t yy = 0; yy < h; yy++) {
    for (uint8_t xx = 0; xx < w; xx++) {
        if (bit == 0) { bits = pgm_read_byte(&bitmap[bo++]); bit = 0x80; }
        // Only render columns that fit within xAdvance
        if ((int16_t)(xo + xx) < (int16_t)pgm_read_byte(&glyph->xAdvance)) {
            if (bits & bit) {
                // foreground pixel
            } else if (textbgcolor != textcolor) {
                // background pixel
            }
        }
        bit >>= 1;
    }
}
```

**Important**: The bitmap MUST consume ALL bits (the `bits`/`bit` machinery
advances `bo` for every column). Only the rendering is clipped — skipping
columns would misalign the bit counter.

### Space Handling

If your GFXfont starts at codepoint 0x21 (exclamation mark), U+0020 (space)
falls outside the font range. Without special handling, the cursor never
advances and characters render on top of each other.

**Fix**: Handle space explicitly before any font lookup:

```cpp
if (cp == ' ') {
    uint8_t spaceAdv = pgm_read_byte(
        &((GFXglyph *)pgm_read_ptr(&f->glyph))->xAdvance
    );
    cursor_x += (int16_t)spaceAdv * textsize_x;
    return;
}
```

### Unrenderable Codepoints

If a codepoint is not in the font AND no fallback applies, still advance
the cursor by one `xAdvance` — otherwise subsequent characters pile up:

```cpp
// Unrenderable codepoint — advance cursor anyway
cursor_x += (int16_t)first_glyph_advance * textsize_x;
```

---

## UTF-8 Decoder

The `write(uint8_t c)` method decodes multi-byte UTF-8 sequences:

```cpp
size_t write(uint8_t c) {
    if (c < 0x80) {
        // Single byte (ASCII): decode and render immediately
        _utf8_cp = c;
        _utf8_remaining = 0;
        _writeGlyph(_utf8_cp);
    } else if (c < 0xC0) {
        // Continuation byte (10xxxxxx)
        if (_utf8_remaining > 0) {
            _utf8_cp = (_utf8_cp << 6) | (c & 0x3F);
            if (--_utf8_remaining == 0) _writeGlyph(_utf8_cp);
        }
    } else if (c < 0xE0) {
        // 2-byte sequence leader (110xxxxx) — Latin Supplement, Greek
        _utf8_cp = c & 0x1F;
        _utf8_remaining = 1;
    } else if (c < 0xF0) {
        // 3-byte sequence leader (1110xxxx) — Cyrillic, CJK
        _utf8_cp = c & 0x0F;
        _utf8_remaining = 2;
    } else {
        // 4-byte sequence leader (11110xxx)
        _utf8_cp = c & 0x07;
        _utf8_remaining = 3;
    }
    return 1;
}
```

### `resetUTF8()`

If you use `print()` in loops (scroll widgets, repeated rendering), a
UTF-8 sequence interrupted mid-character at the end of one frame will
carry over and corrupt the first glyph of the next frame. Provide a
reset function:

```cpp
void resetUTF8() { _utf8_remaining = 0; }
```

Call this **before every `print()`** in scroll/repeat rendering loops.

---

## PROGMEM and Flash Size

All font data is stored in flash via PROGMEM:

- Bitmap data: `const uint8_t FontNameBitmaps[] PROGMEM`
- Glyph descriptors: `const GFXglyph FontNameGlyphs[] PROGMEM`
- Font struct: `const GFXfont FontName PROGMEM`

At runtime, all access must go through `pgm_read_byte()`, `pgm_read_word()`,
and `pgm_read_ptr()` — never dereference PROGMEM pointers directly.

A font covering codepoints 0x0020–0x04FF (Latin + Cyrillic + Greek, ~400–500
glyphs) typically uses 4–6 KB of flash.
