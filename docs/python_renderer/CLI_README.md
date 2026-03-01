# BDF Font Renderer - Command Line Tool

A standalone Python tool that produces **identical output** to the web-based renderer, with LED-style pixel effects for BDF bitmap fonts.

## Installation

Install the only dependency (pypng - pure Python PNG encoder):

```bash
pip install pypng
```

Or from requirements.txt:

```bash
pip install -r requirements.txt
```

## Usage

### Basic Usage

```bash
python bdf_font_renderer.py -f font.bdf -t "Hello World" -o output.png
```

### All Options

```bash
python bdf_font_renderer.py \
  -f 6-series/MatrixChunky6.bdf \
  -t "LED Text" \
  -o output.png \
  -s 10 \
  -c FF0000 \
  -b 000000 \
  -d 0.9 \
  -p 2 \
  -w 1200 \
  -a centered
```

### Render All Characters

```bash
python bdf_font_renderer.py -f font.bdf --all-chars -o all_chars.png
```

## Command-Line Options

### Required Arguments
- `-f, --font FILE` - BDF font file path
- `-o, --output FILE` - Output PNG file path

### Text Content
- `-t, --text TEXT` - Text to render (default: all characters if not specified)
- `--all-chars` - Explicitly render all characters in the font

### Rendering Options
- `-s, --pixel-size SIZE` - Pixel size 1-100 (default: 5)
- `-c, --color HEX` - Pixel color in hex (default: 000000)
- `-b, --background HEX` - Background color in hex (default: ffffff)
- `--transparent` - Use transparent background
- `-p, --spacing SIZE` - Pixel spacing 0-100 (default: 0)
- `-d, --diffusion FLOAT` - Diffusion strength 0.0-1.0 (default: 0.95)
- `-w, --max-width WIDTH` - Max rendered width for text wrapping (default: 1200, 0=unlimited)
- `--no-blank-lines` - Do not add blank lines between text lines

### Alignment
- `-a, --align MODE` - Text alignment: `normal`, `centered`, `justified`, `full` (default: normal)
  - `normal` - Left-aligned text
  - `centered` - Center each line
  - `justified` - Add space at word boundaries (spaces)
  - `full` - Distribute space evenly between all characters

**Note:** When using centered or justified alignment, the trailing whitespace from the last character in each line is automatically trimmed for perfect centering. BDF characters include advance width (spacing for the next character), which is removed from the final character to achieve precise alignment.

### Color Transitions (Animation Frames)
- `--color-to HEX` - End pixel color for color transition
- `--background-to HEX` - End background color for background transition
- `--steps NUMBER` - Number of transition steps/files to generate (requires at least one of the above)

When using `--steps`, multiple numbered files are created (e.g., `output1.png`, `output2.png`, ..., `output16.png`) with colors linearly interpolated between the start and end values.

## Escaping Special Characters

### Rendering Quote Characters

To include quote characters in your text, escape them according to your shell:

**Bash/Linux/macOS:**
```bash
# Use single quotes and include double quotes directly
python bdf_font_renderer.py -f font.bdf -t 'He said "Hello"' -o output.png

# Or escape double quotes inside double-quoted strings
python bdf_font_renderer.py -f font.bdf -t "He said \"Hello\"" -o output.png
```

**PowerShell/Windows:**
```powershell
# Escape double quotes with backtick
python bdf_font_renderer.py -f font.bdf -t "He said `"Hello`"" -o output.png

# Or use single quotes with double quotes inside
python bdf_font_renderer.py -f font.bdf -t 'He said "Hello"' -o output.png

# Or double the quotes
python bdf_font_renderer.py -f font.bdf -t "He said ""Hello""" -o output.png
```

### Other Special Characters

- **Newlines**: Use `\n` directly in the text string: `-t "Line 1\nLine 2"`
- **Single quotes**: Reverse the quote types or escape appropriately
- **Backslashes**: May need doubling in some shells: `\\`

## Examples

### Red LED text on black background, size 8
```bash
python bdf_font_renderer.py -f 8-series/MatrixLight8.bdf -t "MATRIX" -o matrix.png -s 8 -c FF0000 -b 000000 -d 0.9
```

### Green LEDs with spacing and centered text
```bash
python bdf_font_renderer.py -f 6-series/MatrixChunky6.bdf -t "Hello\nWorld" -o hello.png -s 12 -c 00FF00 -b 000000 -p 2 -a centered
```

### Large pixels with low diffusion (clear LED effect)
```bash
python bdf_font_renderer.py -f 8-series/MatrixChunky8.bdf -t "LED" -o led.png -s 20 -c 0080FF -b FFFFFF -d 0.5
```

### Transparent background PNGs
```bash
python bdf_font_renderer.py -f 6-series/MatrixLight6.bdf -t "PNG" -o transparent.png --transparent -c FF00FF -s 15
```

### All characters in the font
```bash
python bdf_font_renderer.py -f 8-series/MatrixLight8.bdf --all-chars -o charset.png -s 6 -w 800
```

### Color transitions (16 frames from yellow to red)
```bash
python bdf_font_renderer.py -f 6-series/MatrixChunky6.bdf -t "FADE" -o frame.png -s 12 -c FFFF00 --color-to FF0000 --steps 16
```

This creates `frame1.png` through `frame16.png` with pixel colors transitioning from yellow to red.

### Background color fade (black to white, 10 steps)
```bash
python bdf_font_renderer.py -f 8-series/MatrixLight8.bdf -t "GLOW" -o glow.png -s 10 -c 00FF00 -b 000000 --background-to FFFFFF --steps 10
```

### Full color cycle animation (both colors transitioning)
```bash
python bdf_font_renderer.py -f 6-series/MatrixLight6.bdf -t "LED" -o anim.png -s 15 -c FF0000 --color-to 0000FF -b 000000 --background-to 222222 --steps 30
```

Creates 30 frames transitioning pixel color from red to blue and background from black to dark gray.

## Features

- **Identical rendering** to the web-based version
- **Manual BDF parsing** - no Pillow dependency
- **Pure Python PNG writing** using pypng (no native libraries)
- **Circular LED patterns** with logarithmic ring spacing
- **Hybrid diffusion** - linear steps for inner rings, exponential for outer
- **Text wrapping** by rendered pixel width
- **Multiple alignment modes** - normal, centered, justified, full
- **Transparent background support**
- **Pixel spacing** for separation between LED pixels
- **Color transitions** - generate multiple frames with smooth color interpolation for animations

## Technical Details

### LED Pattern Algorithm
- Uses distance-from-center calculation for circular LEDs
- Logarithmic ring spacing: each ring occupies 1/3 of remaining radius
- Adaptive level count: ~3 levels at size 6, ~10 levels at size 100
- Hybrid intensity: linear fade for inner 1/3 of levels, exponential decay for outer rings

### BDF Parsing
- Full BDF format support with manual hex-to-bitmap conversion
- Handles character encodings, bounding boxes, and spacing
- Leftmost bit reading for proper bitmap interpretation

### PNG Output
- RGBA color space with alpha channel support
- Direct pixel-by-pixel writing
- No compression artifacts or quality loss

## Dependencies

- **Python 3.6+**
- **pypng** - Pure Python PNG encoder (no native dependencies)

## License
```
MIT License

Copyright (c) 2026 Trip5

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
