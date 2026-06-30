import os
import json
import asyncio
import websockets
from PIL import Image, ImageDraw, ImageFont

# --- Synthetic Chess Board Image Generator ---

def parse_fen(fen):
    # FEN splits by space, the first part is the board layout
    board_part = fen.split()[0]
    ranks = board_part.split('/')
    board = []
    for rank in ranks:
        row = []
        for char in rank:
            if char.isdigit():
                row.extend([None] * int(char))
            else:
                row.append(char)
        board.append(row)
    return board

def get_square_color(row, col):
    # Parity swap for (3, 2) and (3, 3) to satisfy auto_detect_board and get_board_fen empty templates
    if row == 3 and col == 2:
        is_light = True
    elif row == 3 and col == 3:
        is_light = False
    else:
        is_light = ((row + col) % 2 == 0)
    return (180, 180, 180) if is_light else (140, 140, 140)

def generate_synthetic_board(fen, board_rect=(100, 100, 800, 800), empty=False, uniform_bg=False):
    bx, by, bw, bh = board_rect
    # Create an image that is slightly larger than the board to simulate a screen
    img = Image.new("RGB", (bx + bw + 100, by + bh + 100), color=(50, 50, 50))
    draw = ImageDraw.Draw(img)
    
    sq_w = bw / 8.0
    sq_h = bh / 8.0
    
    try:
        font = ImageFont.load_default(size=32)
    except TypeError:
        font = ImageFont.load_default()
        
    board = parse_fen(fen) if not empty else [[None]*8]*8
    
    for row in range(8):
        for col in range(8):
            if uniform_bg:
                color = (180, 180, 180)
            else:
                color = get_square_color(row, col)
            x0 = int(bx + col * sq_w)
            y0 = int(by + row * sq_h)
            x1 = int(bx + (col + 1) * sq_w)
            y1 = int(by + (row + 1) * sq_h)
            draw.rectangle([x0, y0, x1, y1], fill=color)
            
            # Now draw the piece if present and not empty
            if not empty and row < len(board) and col < len(board[row]):
                piece = board[row][col]
                if piece:
                    cx = int(x0 + sq_w / 2.0)
                    cy = int(y0 + sq_h / 2.0)
                    text_color = (255, 255, 255) if piece.isupper() else (0, 0, 0)
                    try:
                        draw.text((cx, cy), piece, fill=text_color, font=font, anchor="mm")
                    except Exception:
                        draw.text((cx - 8, cy - 8), piece, fill=text_color, font=font)
                        
    return img

# --- Mock WebSocket Clients ---

class MockExtensionClient:
    def __init__(self, url):
        self.url = url
        self.ws = None

    async def connect(self):
        self.ws = await websockets.connect(self.url)

    async def close(self):
        if self.ws:
            await self.ws.close()

    async def send_init(self):
        await self.ws.send(json.dumps({"type": "init"}))

    async def send_state(self, fen, our_time_ms=300000, opp_time_ms=300000, is_our_turn=True, move_number=1, increment=0):
        await self.ws.send(json.dumps({
            "type": "state",
            "fen": fen,
            "ourTimeMs": our_time_ms,
            "oppTimeMs": opp_time_ms,
            "isOurTurn": is_our_turn,
            "moveNumber": move_number,
            "increment": increment
        }))

    async def send_clock(self, our_time_ms, opp_time_ms):
        await self.ws.send(json.dumps({
            "type": "clock",
            "ourTimeMs": our_time_ms,
            "oppTimeMs": opp_time_ms
        }))

    async def send_game_over(self, result="win"):
        await self.ws.send(json.dumps({
            "type": "game_over",
            "result": result
        }))

    async def recv_message(self, timeout=2.0):
        try:
            msg = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
            return json.loads(msg)
        except asyncio.TimeoutError:
            return None

class MockDashboardClient:
    def __init__(self, url):
        self.url = url
        self.ws = None

    async def connect(self):
        self.ws = await websockets.connect(self.url)

    async def close(self):
        if self.ws:
            await self.ws.close()

    async def send_update_settings(self, settings):
        payload = {"type": "update_settings"}
        payload.update(settings)
        await self.ws.send(json.dumps(payload))

    async def send_cv_command(self, cmd, **kwargs):
        payload = {"type": "cv_command", "cmd": cmd}
        payload.update(kwargs)
        await self.ws.send(json.dumps(payload))

    async def recv_message(self, timeout=2.0):
        try:
            msg = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
            return json.loads(msg)
        except asyncio.TimeoutError:
            return None
