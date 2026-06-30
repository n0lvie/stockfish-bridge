import pytest
import control_module

def test_control_execute_move_coordinates_and_calls(mock_pyautogui):
    board_rect = (100, 100, 800, 800)
    
    # Execute e2e4 drag-and-drop move
    success = control_module.execute_move("e2e4", board_rect, is_flipped=False, drag_and_drop=True)
    assert success is True
    
    # Filter calls to check correct sequence
    calls = mock_pyautogui.calls
    assert len(calls) > 0
    
    mouse_down_calls = [c for c in calls if c[0] == "mouseDown"]
    mouse_up_calls = [c for c in calls if c[0] == "mouseUp"]
    
    assert len(mouse_down_calls) == 1
    assert len(mouse_up_calls) == 1
    
    # e2 coordinates: (100 + 4*100 + 50, 100 + 6*100 + 50) = (550, 750)
    # e4 coordinates: (100 + 4*100 + 50, 100 + 4*100 + 50) = (550, 550)
    assert mouse_down_calls[0][1] == (550, 750)
    assert mouse_up_calls[0][1] == (550, 550)
