import logging

logger = logging.getLogger("cv_module")

try:
    from PIL import Image, ImageOps
    import numpy as np
    import mss
    CV_AVAILABLE = True
except Exception as e:
    CV_AVAILABLE = False
    logger.warning(f"CV dependencies (PIL, numpy, mss) not available: {e}")


class BoardDetector:

    @staticmethod
    def capture_screenshot():
        if not CV_AVAILABLE:
            raise RuntimeError("Computer Vision libraries (PIL, numpy, mss) are not installed.")
        with mss.mss() as sct:
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            sct_img = sct.grab(monitor)
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            return img, monitor.get("left", 0), monitor.get("top", 0)

    @staticmethod
    def auto_detect_board(img):
        if not CV_AVAILABLE:
            return None

        gray = ImageOps.grayscale(img)
        arr = np.array(gray, dtype=np.float32)
        h, w = arr.shape

        best_board = None
        best_score = 0

        for size in range(320, min(h, w, 960), 64):
            spacing = size / 8.0
            for y_start in range(40, h - size, 80):
                for x_start in range(40, w - size, 80):
                    region = arr[y_start:y_start + size, x_start:x_start + size]

                    block_centers = []
                    for r in range(8):
                        for c in range(8):
                            cy = int((r + 0.5) * spacing)
                            cx = int((c + 0.5) * spacing)
                            block_centers.append(region[cy, cx])

                    block_mat = np.array(block_centers).reshape(8, 8)
                    parity = (np.arange(8)[:, None] + np.arange(8)) % 2
                    light_squares = block_mat[parity == 0]
                    dark_squares = block_mat[parity == 1]

                    light_std = np.std(light_squares)
                    dark_std = np.std(dark_squares)
                    diff = np.abs(np.mean(light_squares) - np.mean(dark_squares))

                    if light_std < 25 and dark_std < 25 and diff > 30:
                        score = diff / (light_std + dark_std + 1)
                        if score > best_score:
                            best_score = score
                            best_board = (x_start, y_start, size, size)

        if best_board:
            logger.info(f"Auto-detected board at: {best_board} with score {best_score:.2f}")
            return best_board

        logger.warning("Auto-detection failed to find a clear chessboard grid.")
        return None


class PieceClassifier:

    def __init__(self):
        self.templates = {}
        self.is_calibrated = False
        self.board_rect = None
        self.is_flipped = False
        self.monitor_offset = (0, 0)

    def calibrate(self, img, board_rect, monitor_offset=(0, 0)):
        if not CV_AVAILABLE:
            return False

        self.board_rect = board_rect
        self.monitor_offset = monitor_offset
        x, y, w, h = board_rect

        cropped = img.crop((x, y, x + w, y + h))
        gray = ImageOps.grayscale(cropped)
        board_arr = np.array(gray)

        sq_w = w / 8.0
        sq_h = h / 8.0

        def crop_square_center(row, col):
            sy = int(row * sq_h)
            sx = int(col * sq_w)
            cy_start = int(sy + 0.2 * sq_h)
            cy_end = int(sy + 0.8 * sq_h)
            cx_start = int(sx + 0.2 * sq_w)
            cx_end = int(sx + 0.8 * sq_w)
            return board_arr[cy_start:cy_end, cx_start:cx_end]

        p_row6 = crop_square_center(6, 0)
        p_row1 = crop_square_center(1, 0)

        if np.mean(p_row6) > np.mean(p_row1):
            self.is_flipped = False
            logger.info("Auto-calibrated: Unflipped board orientation detected (White on bottom).")
        else:
            self.is_flipped = True
            logger.info("Auto-calibrated: Flipped board orientation detected (Black on bottom).")

        self.templates = {}

        def add_template(piece_char, row, col):
            sq_img = crop_square_center(row, col)
            pil_sq = Image.fromarray(sq_img.astype(np.uint8))
            resized = pil_sq.resize((48, 48), Image.Resampling.BILINEAR)
            self.templates[piece_char] = np.array(resized, dtype=np.float32)

        if not self.is_flipped:
            add_template('R', 7, 0)
            add_template('N', 7, 1)
            add_template('B', 7, 2)
            add_template('Q', 7, 3)
            add_template('K', 7, 4)
            add_template('P', 6, 0)

            add_template('r', 0, 0)
            add_template('n', 0, 1)
            add_template('b', 0, 2)
            add_template('q', 0, 3)
            add_template('k', 0, 4)
            add_template('p', 1, 0)
        else:
            add_template('r', 7, 0)
            add_template('n', 7, 1)
            add_template('b', 7, 2)
            add_template('q', 7, 3)
            add_template('k', 7, 4)
            add_template('p', 6, 0)

            add_template('R', 0, 0)
            add_template('N', 0, 1)
            add_template('B', 0, 2)
            add_template('Q', 0, 3)
            add_template('K', 0, 4)
            add_template('P', 1, 0)

        # (3, 3) has (3 + 3) % 2 == 0 -> Light square
        # (3, 2) has (3 + 2) % 2 == 1 -> Dark square
        self.empty_light = crop_square_center(3, 3)
        self.empty_dark = crop_square_center(3, 2)

        self.empty_light_t = np.array(
            Image.fromarray(self.empty_light.astype(np.uint8)).resize((48, 48), Image.Resampling.BILINEAR),
            dtype=np.float32
        )
        self.empty_dark_t = np.array(
            Image.fromarray(self.empty_dark.astype(np.uint8)).resize((48, 48), Image.Resampling.BILINEAR),
            dtype=np.float32
        )

        self.is_calibrated = True
        logger.info(f"PieceClassifier calibration successful. Calibrated {len(self.templates)} pieces.")
        return True

    def get_board_fen(self, img, active_color='w'):
        if not CV_AVAILABLE or not self.is_calibrated or not self.board_rect:
            return None

        x, y, w, h = self.board_rect
        cropped = img.crop((x, y, x + w, y + h))
        gray = ImageOps.grayscale(cropped)
        board_arr = np.array(gray)

        sq_w = w / 8.0
        sq_h = h / 8.0

        logical_board = [[None for _ in range(8)] for _ in range(8)]

        for row in range(8):
            for col in range(8):
                sy = int(row * sq_h)
                sx = int(col * sq_w)
                cy_start = int(sy + 0.2 * sq_h)
                cy_end = int(sy + 0.8 * sq_h)
                cx_start = int(sx + 0.2 * sq_w)
                cx_end = int(sx + 0.8 * sq_w)

                sq_crop = board_arr[cy_start:cy_end, cx_start:cx_end]
                std_dev = np.std(sq_crop)

                if std_dev < 8.0:
                    logical_board[row][col] = None
                    continue

                pil_sq = Image.fromarray(sq_crop.astype(np.uint8))
                resized = np.array(pil_sq.resize((48, 48), Image.Resampling.BILINEAR), dtype=np.float32)

                best_piece = None
                best_diff = float('inf')

                is_square_light = (row + col) % 2 == 0
                empty_t = self.empty_light_t if is_square_light else self.empty_dark_t
                empty_diff = np.mean((resized - empty_t) ** 2)

                for piece_char, template in self.templates.items():
                    diff = np.mean((resized - template) ** 2)
                    if diff < best_diff:
                        best_diff = diff
                        best_piece = piece_char

                if empty_diff < best_diff * 0.85:
                    logical_board[row][col] = None
                else:
                    logical_board[row][col] = best_piece

        fen_ranks = []
        row_iter = range(8) if not self.is_flipped else range(7, -1, -1)
        col_iter = range(8) if not self.is_flipped else range(7, -1, -1)

        for r in row_iter:
            rank_str = ""
            empty = 0
            for c in col_iter:
                piece = logical_board[r][c]
                if piece is None:
                    empty += 1
                else:
                    if empty > 0:
                        rank_str += str(empty)
                        empty = 0
                    rank_str += piece
            if empty > 0:
                rank_str += str(empty)
            fen_ranks.append(rank_str)

        fen_pos = "/".join(fen_ranks)
        return f"{fen_pos} {active_color} KQkq - 0 1"
