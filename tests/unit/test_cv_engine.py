import pytest
from PIL import Image
from cv_module import BoardDetector, PieceClassifier
from helpers import generate_synthetic_board

def test_cv_board_detection_and_calibration():
    # 1. Test auto detection on empty checkerboard board
    empty_board_img = generate_synthetic_board("8/8/8/8/8/8/8/8 w - - 0 1", empty=True, uniform_bg=False)
    rect = BoardDetector.auto_detect_board(empty_board_img)
    assert rect is not None
    assert rect == (100, 100, 800, 800)
    
    # 2. Test calibration on starting position board with uniform background
    starting_board_img = generate_synthetic_board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", uniform_bg=True)
    classifier = PieceClassifier()
    success = classifier.calibrate(starting_board_img, rect)
    assert success is True
    assert classifier.is_calibrated is True
    assert classifier.is_flipped is False
    
    # 3. Test FEN recognition on a modified board state with uniform background
    modified_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    modified_board_img = generate_synthetic_board(modified_fen, uniform_bg=True)
    
    recognized_fen = classifier.get_board_fen(modified_board_img, active_color='b')
    assert recognized_fen is not None
    assert recognized_fen.split()[0] == modified_fen.split()[0]
