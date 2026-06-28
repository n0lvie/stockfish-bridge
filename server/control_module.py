utf-8import time
import random
import logging
import pyautogui

logger = logging.getLogger("control_module")

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05                                            

def square_to_file_rank(square):
    if len(square) < 2:
        return -1, -1
    file = ord(square[0].lower()) - ord('a')         
    rank = int(square[1]) - 1         
    return file, rank

def get_square_coords(square, board_rect, is_flipped):
                                                                            
    x_board, y_board, w, h = board_rect
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
        
    cx = x_board + col * sq_w + sq_w / 2.0
    cy = y_board + row * sq_h + sq_h / 2.0
    return int(cx), int(cy)

def move_mouse_humanlike(to_x, to_y):
                                                                                                    
    from_x, from_y = pyautogui.position()

    dist = ((to_x - from_x)**2 + (to_y - from_y)**2)**0.5
    if dist < 10:
        pyautogui.moveTo(to_x, to_y)
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
        
        pyautogui.moveTo(int(cx), int(cy))
                                                    
        time.sleep(random.uniform(0.004, 0.012))

    overshoot_x = to_x + random.randint(-3, 3)
    overshoot_y = to_y + random.randint(-3, 3)
    pyautogui.moveTo(overshoot_x, overshoot_y)
    time.sleep(random.uniform(0.03, 0.08))
    
    pyautogui.moveTo(to_x, to_y)

def execute_move(uci_move, board_rect, is_flipped, drag_and_drop=True):
           
    from_square = uci_move[:2]
    to_square = uci_move[2:4]
    promotion = uci_move[4] if len(uci_move) > 4 else None
    
    from_coords = get_square_coords(from_square, board_rect, is_flipped)
    to_coords = get_square_coords(to_square, board_rect, is_flipped)
    
    if not from_coords or not to_coords:
        logger.error(f"Could not calculate coordinates for move: {uci_move}")
        return False
        
    logger.info(f"Executing move: {uci_move} -> from {from_coords} to {to_coords}")

    move_mouse_humanlike(from_coords[0], from_coords[1])
    time.sleep(random.uniform(0.1, 0.2))                          
    
    if drag_and_drop:
                    
        pyautogui.mouseDown()
        time.sleep(random.uniform(0.05, 0.15))
        move_mouse_humanlike(to_coords[0], to_coords[1])
        time.sleep(random.uniform(0.05, 0.15))
        pyautogui.mouseUp()
    else:
                     
        pyautogui.click()
        time.sleep(random.uniform(0.1, 0.25))
        move_mouse_humanlike(to_coords[0], to_coords[1])
        time.sleep(random.uniform(0.08, 0.18))
        pyautogui.click()

    if promotion:
        time.sleep(random.uniform(0.3, 0.5))                                      

        promo_x, promo_y = to_coords
        move_mouse_humanlike(promo_x, promo_y)
        pyautogui.click()
        logger.info(f"Selected promotion: {promotion}")
        
    return True
