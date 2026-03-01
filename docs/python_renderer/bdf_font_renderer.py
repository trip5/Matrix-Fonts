#!/usr/bin/env python3
"""
BDF Font Renderer - Command-line tool for rendering BDF fonts with LED-style pixels
Produces identical output to the web-based renderer at https://github.com/trip5/Matrix-Fonts
"""

import argparse
import math
import sys
from typing import List, Tuple, Dict, Optional

# PNG writing using pypng (pure Python, no dependencies)
try:
    import png
except ImportError:
    print("Error: pypng library not found. Install with: pip install pypng")
    sys.exit(1)


class BDFChar:
    """Represents a single character from a BDF font"""
    def __init__(self):
        self.name = ""
        self.encoding = -1
        self.dwidth = [0, 0]
        self.bbx = {'width': 0, 'height': 0, 'xoff': 0, 'yoff': 0}
        self.bitmap = []


class BDFParser:
    """Parser for BDF (Bitmap Distribution Format) font files"""
    
    def __init__(self, bdf_content: str):
        self.content = bdf_content
        self.chars: Dict[int, BDFChar] = {}
        self.properties = {}
        self.parse()
    
    def parse(self):
        """Parse the BDF file content"""
        lines = self.content.split('\n')
        i = 0
        
        # Parse header
        while i < len(lines) and not lines[i].startswith('CHARS '):
            line = lines[i].strip()
            if line.startswith('FONT '):
                self.properties['fontName'] = line[5:]
            elif line.startswith('SIZE '):
                parts = line.split()
                self.properties['size'] = int(parts[1])
            elif line.startswith('FONTBOUNDINGBOX '):
                parts = line.split()
                self.properties['bbx'] = {
                    'width': int(parts[1]),
                    'height': int(parts[2]),
                    'xoff': int(parts[3]),
                    'yoff': int(parts[4])
                }
            i += 1
        
        # Parse characters
        while i < len(lines):
            if lines[i].startswith('STARTCHAR '):
                char = self.parse_char(lines, i)
                if char and char.encoding >= 0:
                    self.chars[char.encoding] = char
                # Skip to next character
                while i < len(lines) and not lines[i].startswith('ENDCHAR'):
                    i += 1
            i += 1
    
    def parse_char(self, lines: List[str], start_index: int) -> Optional[BDFChar]:
        """Parse a single character definition"""
        i = start_index
        char = BDFChar()
        char.name = lines[i][10:].strip()
        
        i += 1
        while i < len(lines) and not lines[i].startswith('BITMAP'):
            line = lines[i].strip()
            if line.startswith('ENCODING '):
                char.encoding = int(line[9:])
            elif line.startswith('DWIDTH '):
                parts = line.split()
                char.dwidth = [int(parts[1]), int(parts[2])]
            elif line.startswith('BBX '):
                parts = line.split()
                char.bbx = {
                    'width': int(parts[1]),
                    'height': int(parts[2]),
                    'xoff': int(parts[3]),
                    'yoff': int(parts[4])
                }
            i += 1
        
        # Parse bitmap
        i += 1  # Skip BITMAP line
        while i < len(lines) and not lines[i].startswith('ENDCHAR'):
            line = lines[i].strip()
            if line:
                char.bitmap.append(line)
            i += 1
        
        return char if char.encoding >= 0 else None
    
    def get_char(self, code: int) -> Optional[BDFChar]:
        """Get character by encoding value"""
        return self.chars.get(code)
    
    def get_all_chars(self) -> List[BDFChar]:
        """Get all characters sorted by encoding"""
        return sorted(self.chars.values(), key=lambda c: c.encoding)
    
    def hex_to_bit_array(self, hex_string: str, width: int) -> List[int]:
        """Convert hex string to bit array (BDF format uses leftmost bits)"""
        value = int(hex_string, 16)
        bits = []
        hex_bits = len(hex_string) * 4
        for i in range(width):
            bit_pos = hex_bits - 1 - i
            bits.append(1 if (value & (1 << bit_pos)) else 0)
        return bits


class LEDRenderer:
    """Renders LED-style pixels with circular diffusion patterns"""
    
    def __init__(self, pixel_size: int, color: Tuple[int, int, int], 
                 diffusion: float, bg_color: Tuple[int, int, int], 
                 transparent_bg: bool):
        self.pixel_size = max(1, min(100, pixel_size))
        self.color = color
        self.bg_color = bg_color
        self.transparent_bg = transparent_bg
        self.diffusion = diffusion
        self.led_pattern = self.create_led_pattern()
    
    def create_led_pattern(self) -> List[List[float]]:
        """Create LED pattern with logarithmic ring spacing and hybrid intensity"""
        size = self.pixel_size
        pattern = []
        
        # Calculate center point
        center_x = (size - 1) / 2
        center_y = (size - 1) / 2
        
        # Calculate maximum distance (center to corner)
        max_distance = math.sqrt(center_x * center_x + center_y * center_y)
        
        # Determine max levels based on size (logarithmic scaling)
        if size == 1:
            max_levels = 1
        else:
            max_levels = min(10, max(2, math.ceil(math.log2(size) * 1.5)))
        
        for y in range(size):
            row = []
            for x in range(size):
                # Calculate Euclidean distance from center
                dx = x - center_x
                dy = y - center_y
                distance = math.sqrt(dx * dx + dy * dy)
                
                # Normalize distance (0 = center, 1 = corner)
                normalized_dist = distance / max_distance
                
                # Logarithmic level assignment (each ring is 1/3 of remaining radius)
                if normalized_dist >= 0.9999:
                    level = max_levels
                elif normalized_dist < 0.0001:
                    level = 1
                else:
                    # Formula: level = ln(1 - distance) / ln(2/3)
                    level = math.floor(math.log(1 - normalized_dist) / math.log(2/3)) + 1
                    level = max(1, min(max_levels, level))
                
                # Hybrid intensity calculation
                linear_levels = 1 if max_levels == 1 else max(2, math.floor(max_levels / 3))
                
                if level <= linear_levels:
                    # Linear interpolation for inner rings
                    if linear_levels == 1:
                        intensity = 1.0
                    else:
                        intensity = 1.0 - ((level - 1) * (1.0 - self.diffusion) / (linear_levels - 1))
                else:
                    # Exponential decay for outer rings
                    intensity = math.pow(self.diffusion, level - linear_levels + 1)
                
                row.append(intensity)
            pattern.append(row)
        
        return pattern
    
    def render_pixel(self, image_data: List[List[Tuple[int, int, int, int]]], 
                     canvas_x: int, canvas_y: int):
        """Render a single LED pixel into the image data"""
        for py in range(self.pixel_size):
            for px in range(self.pixel_size):
                x = canvas_x + px
                y = canvas_y + py
                intensity = self.led_pattern[py][px]
                
                if intensity > 0:
                    if self.transparent_bg:
                        # Transparent background: use alpha for diffusion
                        r = int(self.color[0] * intensity)
                        g = int(self.color[1] * intensity)
                        b = int(self.color[2] * intensity)
                        a = int(255 * intensity)
                    else:
                        # Solid background: blend with background color
                        r = int(self.color[0] * intensity + self.bg_color[0] * (1 - intensity))
                        g = int(self.color[1] * intensity + self.bg_color[1] * (1 - intensity))
                        b = int(self.color[2] * intensity + self.bg_color[2] * (1 - intensity))
                        a = 255
                    
                    if y < len(image_data) and x < len(image_data[y]):
                        image_data[y][x] = (r, g, b, a)


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Convert hex color string to RGB tuple"""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) != 6:
        return (0, 0, 0)
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def interpolate_color(color1: Tuple[int, int, int], color2: Tuple[int, int, int], 
                      step: int, total_steps: int) -> Tuple[int, int, int]:
    """Interpolate linearly between two RGB colors"""
    if total_steps <= 1:
        return color1
    
    # Calculate interpolation factor (0.0 to 1.0)
    factor = step / (total_steps - 1)
    
    # Linear interpolation for each channel
    r = int(color1[0] * (1 - factor) + color2[0] * factor)
    g = int(color1[1] * (1 - factor) + color2[1] * factor)
    b = int(color1[2] * (1 - factor) + color2[2] * factor)
    
    return (r, g, b)


def split_filename(filename: str) -> Tuple[str, str]:
    """Split filename into base and extension for numbering"""
    import os
    base, ext = os.path.splitext(filename)
    if not ext:
        ext = '.png'
    return base, ext


def render_text(bdf_font: BDFParser, text: str, renderer: LEDRenderer,
                pixel_spacing: int, max_width: int, blank_between_lines: bool,
                alignment: str, bg_color: Tuple[int, int, int], 
                transparent_bg: bool) -> List[List[Tuple[int, int, int, int]]]:
    """Main rendering function"""
    
    rendered_pixel_width = renderer.pixel_size + pixel_spacing
    font_height = bdf_font.properties['bbx']['height']
    
    # Determine what to render
    if not text.strip():
        # Render all characters
        all_chars = bdf_font.get_all_chars()
        render_text_str = ''.join(chr(c.encoding) for c in all_chars)
    else:
        render_text_str = text
    
    # Wrap text if needed
    lines = []
    if max_width > 0 and max_width >= 100:
        max_bdf_pixels = math.floor((max_width - 2 - pixel_spacing) / rendered_pixel_width)
        current_line = ''
        current_width = 0
        
        for char in render_text_str:
            if char == '\n':
                lines.append(current_line)
                current_line = ''
                current_width = 0
                continue
            
            char_data = bdf_font.get_char(ord(char))
            if char_data:
                char_width = char_data.dwidth[0]
                if current_width + char_width > max_bdf_pixels and current_line:
                    lines.append(current_line)
                    current_line = char
                    current_width = char_width
                else:
                    current_line += char
                    current_width += char_width
            else:
                current_line += char
        
        if current_line:
            lines.append(current_line)
    elif '\n' in render_text_str:
        lines = render_text_str.split('\n')
    else:
        lines = [render_text_str]
    
    # Calculate dimensions
    max_line_width = 0
    line_widths = []
    
    # For centered/justified text, trim trailing space from last character
    trim_last_char = alignment in ['centered', 'justified', 'full']
    
    for line in lines:
        line_width = 0
        last_char_data = None
        
        for i, char in enumerate(line):
            char_data = bdf_font.get_char(ord(char))
            if char_data:
                line_width += char_data.dwidth[0]
                last_char_data = char_data
        
        # Trim trailing space from last character if using centered/justified alignment
        if trim_last_char and last_char_data:
            # Replace dwidth with actual glyph width for last character
            line_width -= last_char_data.dwidth[0]
            line_width += last_char_data.bbx['width'] + last_char_data.bbx['xoff']
        
        line_widths.append(line_width)
        max_line_width = max(max_line_width, line_width)
    
    total_height = len(lines) * font_height
    if blank_between_lines and len(lines) > 1:
        total_height += len(lines) - 1
    
    # Calculate canvas size
    if pixel_spacing > 0:
        canvas_width = (max_line_width * (renderer.pixel_size + pixel_spacing) + pixel_spacing) + 2
        canvas_height = (total_height * (renderer.pixel_size + pixel_spacing) + pixel_spacing) + 2
    else:
        canvas_width = (max_line_width * renderer.pixel_size) + 2
        canvas_height = (total_height * renderer.pixel_size) + 2
    
    # Initialize image data
    if transparent_bg:
        image_data = [[(0, 0, 0, 0) for _ in range(canvas_width)] for _ in range(canvas_height)]
    else:
        bg_pixel = bg_color + (255,)
        image_data = [[bg_pixel for _ in range(canvas_width)] for _ in range(canvas_height)]
    
    # Render each line
    current_y = 1
    
    for line_idx, line in enumerate(lines):
        line_width = line_widths[line_idx]
        
        # Calculate starting X position based on alignment
        current_x = 1
        
        if alignment == 'centered' and line_width < max_line_width:
            offset = math.floor((max_line_width - line_width) / 2)
            if pixel_spacing > 0:
                current_x += offset * (renderer.pixel_size + pixel_spacing)
            else:
                current_x += offset * renderer.pixel_size
        
        # Calculate justification
        extra_spacing = 0
        accumulated_spacing = 0
        space_indices = []
        
        if alignment == 'justified' and line_width < max_line_width and len(line) > 1:
            # Word-based justification
            for i, char in enumerate(line):
                if char == ' ':
                    space_indices.append(i)
            if space_indices:
                extra_spacing = (max_line_width - line_width) / len(space_indices)
        elif alignment == 'full' and line_width < max_line_width and len(line) > 1:
            # Full justification
            extra_spacing = (max_line_width - line_width) / (len(line) - 1)
        
        # Render each character
        for i, char in enumerate(line):
            char_data = bdf_font.get_char(ord(char))
            if not char_data:
                continue
            
            bbx = char_data.bbx
            
            # Calculate position with justification
            char_x = current_x
            if (alignment in ['justified', 'full']) and extra_spacing > 0:
                char_x += math.floor(accumulated_spacing) * (
                    (renderer.pixel_size + pixel_spacing) if pixel_spacing > 0 else renderer.pixel_size
                )
            
            # Render character bitmap
            for row_idx, hex_line in enumerate(char_data.bitmap):
                bits = bdf_font.hex_to_bit_array(hex_line, bbx['width'])
                
                for col_idx, bit in enumerate(bits):
                    if bit:
                        bdf_pixel_x = col_idx + bbx['xoff']
                        bdf_pixel_y = font_height - bbx['height'] - bbx['yoff'] + row_idx
                        
                        if pixel_spacing > 0:
                            pixel_x = char_x + bdf_pixel_x * (renderer.pixel_size + pixel_spacing) + pixel_spacing
                            pixel_y = current_y + bdf_pixel_y * (renderer.pixel_size + pixel_spacing) + pixel_spacing
                        else:
                            pixel_x = char_x + bdf_pixel_x * renderer.pixel_size
                            pixel_y = current_y + bdf_pixel_y * renderer.pixel_size
                        
                        renderer.render_pixel(image_data, pixel_x, pixel_y)
            
            # Advance X position
            if pixel_spacing > 0:
                current_x += char_data.dwidth[0] * (renderer.pixel_size + pixel_spacing)
            else:
                current_x += char_data.dwidth[0] * renderer.pixel_size
            
            # Accumulate justification spacing
            if alignment == 'justified' and extra_spacing > 0 and char == ' ':
                accumulated_spacing += extra_spacing
            elif alignment == 'full' and extra_spacing > 0 and i < len(line) - 1:
                accumulated_spacing += extra_spacing
        
        # Move to next line
        if pixel_spacing > 0:
            current_y += font_height * (renderer.pixel_size + pixel_spacing)
        else:
            current_y += font_height * renderer.pixel_size
        
        # Add blank line
        if blank_between_lines and line_idx < len(lines) - 1:
            if pixel_spacing > 0:
                current_y += (renderer.pixel_size + pixel_spacing)
            else:
                current_y += renderer.pixel_size
    
    return image_data


def write_png(image_data: List[List[Tuple[int, int, int, int]]], output_path: str):
    """Write image data to PNG file using pypng"""
    height = len(image_data)
    width = len(image_data[0]) if height > 0 else 0
    
    # Convert to flat RGBA array
    pixels = []
    for row in image_data:
        for pixel in row:
            pixels.extend(pixel)
    
    # Write PNG
    with open(output_path, 'wb') as f:
        writer = png.Writer(width=width, height=height, greyscale=False, alpha=True)
        # Reshape to rows
        png_rows = []
        for y in range(height):
            png_rows.append(pixels[y * width * 4:(y + 1) * width * 4])
        writer.write(f, png_rows)


def main():
    parser = argparse.ArgumentParser(
        description='BDF Font Renderer - Render BDF fonts with LED-style pixels',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -f font.bdf -t "Hello" -o output.png
  %(prog)s -f font.bdf -t "Test" -s 10 -c FF0000 -b 000000 -d 0.9
  %(prog)s -f font.bdf --all-chars -o all.png
  %(prog)s -f font.bdf -t "FADE" -o frame.png -c FFFF00 --color-to FF0000 --steps 16
        """
    )
    
    # Required arguments
    parser.add_argument('-f', '--font', required=True, help='BDF font file path')
    parser.add_argument('-o', '--output', required=True, help='Output PNG file path')
    
    # Text content
    parser.add_argument('-t', '--text', default='', help='Text to render (default: all characters)')
    parser.add_argument('--all-chars', action='store_true', help='Render all characters in font')
    
    # Rendering options
    parser.add_argument('-s', '--pixel-size', type=int, default=5, help='Pixel size 1-100 (default: 5)')
    parser.add_argument('-c', '--color', default='000000', help='Pixel color in hex (default: 000000)')
    parser.add_argument('-b', '--background', default='ffffff', help='Background color in hex (default: ffffff)')
    parser.add_argument('--transparent', action='store_true', help='Use transparent background')
    parser.add_argument('-p', '--spacing', type=int, default=0, help='Pixel spacing 0-100 (default: 0)')
    parser.add_argument('-d', '--diffusion', type=float, default=0.95, help='Diffusion strength 0.0-1.0 (default: 0.95)')
    parser.add_argument('-w', '--max-width', type=int, default=1200, help='Max rendered width for wrapping (default: 1200, 0=unlimited)')
    parser.add_argument('--no-blank-lines', action='store_true', help='Do not add blank lines between text lines')
    
    # Alignment
    parser.add_argument('-a', '--align', choices=['normal', 'centered', 'justified', 'full'], 
                        default='normal', help='Text alignment (default: normal)')
    
    # Color transitions
    parser.add_argument('--color-to', default=None, help='End pixel color for transition (hex)')
    parser.add_argument('--background-to', default=None, help='End background color for transition (hex)')
    parser.add_argument('--steps', type=int, default=1, help='Number of transition steps/files (default: 1)')
    
    args = parser.parse_args()
    
    # Validate transition arguments
    if args.steps > 1 and not args.color_to and not args.background_to:
        parser.error('--steps requires at least one of --color-to or --background-to')
    if args.steps < 1:
        parser.error('--steps must be at least 1')
    
    # Read BDF font
    try:
        with open(args.font, 'r', encoding='utf-8') as f:
            bdf_content = f.read()
    except Exception as e:
        print(f"Error reading font file: {e}")
        sys.exit(1)
    
    # Parse font
    bdf_font = BDFParser(bdf_content)
    print(f"Loaded font: {bdf_font.properties.get('fontName', 'Unknown')} ({len(bdf_font.chars)} characters)")
    
    # Determine text to render
    text = '' if args.all_chars else args.text
    
    # Parse start colors
    start_pixel_color = hex_to_rgb(args.color)
    start_bg_color = hex_to_rgb(args.background)
    
    # Parse end colors (if transitioning)
    end_pixel_color = hex_to_rgb(args.color_to) if args.color_to else start_pixel_color
    end_bg_color = hex_to_rgb(args.background_to) if args.background_to else start_bg_color
    
    # Split output filename for numbering
    base_name, extension = split_filename(args.output)
    
    # Render multiple steps if transitioning
    if args.steps > 1:
        print(f"Generating {args.steps} transition frames...")
        if args.color_to:
            print(f"  Pixel color: #{args.color} → #{args.color_to}")
        if args.background_to:
            print(f"  Background: #{args.background} → #{args.background_to}")
    
    for step in range(args.steps):
        # Interpolate colors for this step
        pixel_color = interpolate_color(start_pixel_color, end_pixel_color, step, args.steps)
        bg_color = interpolate_color(start_bg_color, end_bg_color, step, args.steps)
        
        # Create renderer with interpolated colors
        renderer = LEDRenderer(
            args.pixel_size,
            pixel_color,
            args.diffusion,
            bg_color,
            args.transparent
        )
        
        # Render
        if args.steps == 1:
            print(f"Rendering with pixel_size={args.pixel_size}, diffusion={args.diffusion}, alignment={args.align}...")
        
        image_data = render_text(
            bdf_font,
            text,
            renderer,
            args.spacing,
            args.max_width,
            not args.no_blank_lines,
            args.align,
            bg_color,
            args.transparent
        )
        
        # Determine output filename
        if args.steps > 1:
            output_file = f"{base_name}{step + 1}{extension}"
        else:
            output_file = args.output
        
        # Write PNG
        try:
            write_png(image_data, output_file)
            height = len(image_data)
            width = len(image_data[0]) if height > 0 else 0
            if args.steps > 1:
                print(f"  [{step + 1}/{args.steps}] Saved {width}x{height}px to: {output_file}")
            else:
                print(f"✓ Saved {width}x{height}px PNG to: {output_file}")
        except Exception as e:
            print(f"Error writing PNG: {e}")
            sys.exit(1)
    
    if args.steps > 1:
        print(f"✓ Successfully generated {args.steps} frames")


if __name__ == '__main__':
    main()
