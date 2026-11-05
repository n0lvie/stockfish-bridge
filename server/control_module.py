import time
import random
import logging

logger = logging.getLogger("control_module")

_pyautogui = None


def _get_pyautogui():
    global _pyautogui
    if _pyautogui is None:
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0.05
        _pyautogui = pyautogui
    return _pyautogui


def square_to_file_rank(square):
    if not square or len(square) < 2:
        return -1, -1
    file = ord(square[0].lower()) - ord('a')
    try:
        rank = int(square[1]) - 1
    except ValueError:
        return -1, -1
    if not (0 <= file <= 7 and 0 <= rank <= 7):
        return -1, -1
    return file, rank


def get_square_coords(square, board_rect, is_flipped, monitor_offset=(0, 0)):
    x_board, y_board, w, h = board_rect
    offset_x, offset_y = monitor_offset
    sq_w = w / 8.0
    sq_h = h / 8.0

    file, rank = square_to_file_rank(square)
    if file < 0 or rank < 0:
        return None

    if is_flipped:
        col = 7 - file
        row = rank
    else:
        col = file
        row = 7 - rank

    cx = offset_x + x_board + col * sq_w + sq_w / 2.0
    cy = offset_y + y_board + row * sq_h + sq_h / 2.0
    return int(cx), int(cy)


def move_mouse_humanlike(to_x, to_y):
    gui = _get_pyautogui()
    from_x, from_y = gui.position()

    dist = ((to_x - from_x) ** 2 + (to_y - from_y) ** 2) ** 0.5
    if dist < 10:
        gui.moveTo(to_x, to_y)
        return

    steps = int(max(10, min(30, dist / 20)))
    dev_x = random.randint(-40, 40)
    dev_y = random.randint(-40, 40)

    for i in range(steps + 1):
        t = i / float(steps)
        lx = from_x + (to_x - from_x) * t
        ly = from_y + (to_y - from_y) * t

        curve = 4 * t * (1 - t)
        cx = lx + dev_x * curve
        cy = ly + dev_y * curve

        gui.moveTo(int(cx), int(cy))
        time.sleep(random.uniform(0.004, 0.012))

    overshoot_x = to_x + random.randint(-3, 3)
    overshoot_y = to_y + random.randint(-3, 3)
    gui.moveTo(overshoot_x, overshoot_y)
    time.sleep(random.uniform(0.03, 0.08))

    gui.moveTo(to_x, to_y)


def execute_move(uci_move, board_rect, is_flipped, drag_and_drop=True, monitor_offset=(0, 0)):
    if not board_rect or not uci_move or len(uci_move) < 4:
        return False

    gui = _get_pyautogui()
    from_square = uci_move[:2]
    to_square = uci_move[2:4]
    promotion = uci_move[4].lower() if len(uci_move) > 4 else None

    from_coords = get_square_coords(from_square, board_rect, is_flipped, monitor_offset)
    to_coords = get_square_coords(to_square, board_rect, is_flipped, monitor_offset)

    if not from_coords or not to_coords:
        logger.error(f"Could not calculate coordinates for move: {uci_move}")
        return False

    logger.info(f"Executing move: {uci_move} -> from {from_coords} to {to_coords}")

    move_mouse_humanlike(from_coords[0], from_coords[1])
    time.sleep(random.uniform(0.08, 0.15))

    if drag_and_drop:
        gui.mouseDown()
        time.sleep(random.uniform(0.05, 0.12))
        move_mouse_humanlike(to_coords[0], to_coords[1])
        time.sleep(random.uniform(0.05, 0.12))
        gui.mouseUp()
    else:
        gui.click()
        time.sleep(random.uniform(0.08, 0.18))
        move_mouse_humanlike(to_coords[0], to_coords[1])
        time.sleep(random.uniform(0.06, 0.14))
        gui.click()

    if promotion:
        time.sleep(random.uniform(0.25, 0.4))
        sq_h = board_rect[3] / 8.0
        _, to_rank = square_to_file_rank(to_square)
        # Promotion menu order from target square inward: q (0), n (1), r (2), b (3)
        promo_idx = {'q': 0, 'n': 1, 'r': 2, 'b': 3}.get(promotion, 0)
        at_top_edge = (to_rank == 7 and not is_flipped) or (to_rank == 0 and is_flipped)
        direction = 1 if at_top_edge else -1
        promo_x = to_coords[0]
        promo_y = int(to_coords[1] + direction * promo_idx * sq_h)
        move_mouse_humanlike(promo_x, promo_y)
        gui.click()
        logger.info(f"Selected promotion: {promotion} at ({promo_x}, {promo_y})")

    return True
