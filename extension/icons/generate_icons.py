utf-8                       

import struct
import zlib
import os
import math

def create_png(width, height, pixels):

    def make_chunk(chunk_type, data):
                                          
        chunk = chunk_type + data
        crc = struct.pack('>I', zlib.crc32(chunk) & 0xFFFFFFFF)
        return struct.pack('>I', len(data)) + chunk + crc

    signature = b'\x89PNG\r\n\x1a\n'

    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
                                                                            
    ihdr = make_chunk(b'IHDR', ihdr_data)

    raw_data = b''
    for row in pixels:
        raw_data += b'\x00'                     
        for r, g, b, a in row:
            raw_data += struct.pack('BBBB', r, g, b, a)
    
    compressed = zlib.compress(raw_data, 9)
    idat = make_chunk(b'IDAT', compressed)

    iend = make_chunk(b'IEND', b'')
    
    return signature + ihdr + idat + iend

def lerp_color(c1, c2, t):
                                                       
    t = max(0.0, min(1.0, t))
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(4))

def distance(x1, y1, x2, y2):
                             
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

def rounded_rect_alpha(x, y, w, h, radius, size):

    nx = x / size
    ny = y / size
    nw = w / size
    nh = h / size
    nr = radius / size

    if nr <= nx <= nw - nr and 0 <= ny <= nh:
        return 255
    if 0 <= nx <= nw and nr <= ny <= nh - nr:
        return 255

    corners = [
        (nr, nr),                     
        (nw - nr, nr),                 
        (nr, nh - nr),                   
        (nw - nr, nh - nr),               
    ]
    
    for cx, cy in corners:
        dx = abs(nx - cx)
        dy = abs(ny - cy)
        if dx <= nr and dy <= nr:
            dist = math.sqrt(dx * dx + dy * dy)
            if dist <= nr - 0.5 / size:
                return 255
            elif dist <= nr + 0.5 / size:
                                 
                return int(255 * (1.0 - (dist - nr + 0.5 / size) * size))
            else:
                return 0

    if 0 <= nx <= nw and 0 <= ny <= nh:
        return 255
    
    return 0

def generate_knight_mask(size):
           
    mask = [[0.0] * size for _ in range(size)]

    def point_in_shape(px, py):

        pad = 0.2
                              
        x = (px - pad) / (1.0 - 2 * pad)
        y = (py - pad) / (1.0 - 2 * pad)
        
        if x < 0 or x > 1 or y < 0 or y > 1:
            return False

        if 0.15 <= x <= 0.85 and 0.82 <= y <= 0.95:
            return True
                  
        if 0.2 <= x <= 0.8 and 0.75 <= y <= 0.82:
            return True

        if 0.25 <= x <= 0.65 and 0.35 <= y <= 0.75:
            return True

        if 0.2 <= x <= 0.75 and 0.18 <= y <= 0.45:
            return True

        if 0.55 <= x <= 0.85 and 0.22 <= y <= 0.38:
            return True

        if 0.3 <= x <= 0.5 and 0.05 <= y <= 0.22:
            return True

        if 0.15 <= x <= 0.3 and 0.3 <= y <= 0.55:
            return True
        
        return False

    samples = 3 if size >= 48 else 2
    
    for y in range(size):
        for x in range(size):
            count = 0
            for sy in range(samples):
                for sx in range(samples):
                    px = (x + (sx + 0.5) / samples) / size
                    py = (y + (sy + 0.5) / samples) / size
                    if point_in_shape(px, py):
                        count += 1
            mask[y][x] = count / (samples * samples)
    
    return mask

def generate_icon(size):

    bg_color = (100, 200, 255, 255)                         
    bg_dark = (60, 150, 220, 255)                                       
    piece_color = (15, 15, 25, 255)                     
    piece_highlight = (25, 25, 40, 255)                     
    transparent = (0, 0, 0, 0)

    radius = max(2, size // 5)

    knight_mask = generate_knight_mask(size)

    pixels = []
    
    for y in range(size):
        row = []
        for x in range(size):
                                               
            rect_alpha = rounded_rect_alpha(x, y, size - 1, size - 1, radius, size)
            
            if rect_alpha <= 0:
                row.append(transparent)
                continue

            t = y / max(1, size - 1)
            bg = lerp_color(bg_color, bg_dark, t * 0.5)

            cx, cy = size * 0.35, size * 0.3
            dist_from_center = distance(x, y, cx, cy) / size
            if dist_from_center < 0.4:
                highlight_t = 1.0 - dist_from_center / 0.4
                bg = lerp_color(bg, (140, 220, 255, 255), highlight_t * 0.3)

            k = knight_mask[y][x]
            if k > 0:
                pixel = lerp_color(bg, piece_color, k)
            else:
                pixel = bg

            if rect_alpha < 255:
                pixel = (pixel[0], pixel[1], pixel[2], 
                        int(pixel[3] * rect_alpha / 255))
            
            row.append(pixel)
        pixels.append(row)
    
    return pixels

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    sizes = {
        'icon16.png': 16,
        'icon48.png': 48,
        'icon128.png': 128,
    }
    
    for filename, size in sizes.items():
        print(f'Generating {filename} ({size}x{size})...')
        pixels = generate_icon(size)
        png_data = create_png(size, size, pixels)
        
        filepath = os.path.join(script_dir, filename)
        with open(filepath, 'wb') as f:
            f.write(png_data)
        
        file_size = len(png_data)
        print(f'  Created {filepath} ({file_size} bytes)')
    
    print('\nAll icons generated successfully!')

if __name__ == '__main__':
    main()
