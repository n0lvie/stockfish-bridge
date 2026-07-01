import pytest
import time

@pytest.mark.parametrize("resolution", [
    (1920, 1080, 1.0),
    (1366, 768, 1.0),
    (1920, 1080, 1.5),  # zoom level 150% (simulated via viewport scale or CSS transform)
    (390, 844, 1.0)     # mobile resolution
])
def test_chess_com_robust_move_execution(page, live_chess_page, resolution):
    """
    Test move execution under various resolutions and zoom levels.
    """
    width, height, scale = resolution
    
    # Set viewport
    page.set_viewport_size({"width": width, "height": height})
    
    if scale != 1.0:
        # Simulate browser zoom
        page.evaluate(f"document.body.style.zoom = '{scale}';")
        
    page.wait_for_timeout(3000)
    
    # Trigger move from mock server
    page.evaluate("window.sendMockServerMessage({type: 'move', uci: 'g1f3', autoPlay: true});")
    
    page.wait_for_timeout(2000)
    
    # Verify piece moved to f3
    f3_piece = page.evaluate("document.querySelector('.piece.square-f3') !== null")
    assert f3_piece == True, f"Move failed on resolution {width}x{height} with scale {scale}"


@pytest.mark.parametrize("resolution", [
    (1920, 1080, 1.0),
    (1366, 768, 1.0),
    (1920, 1080, 1.5),  # zoom level 150%
    (390, 844, 1.0)     # mobile resolution
])
def test_lichess_robust_move_execution(page, live_lichess_page, resolution):
    """
    Test move execution under various resolutions and zoom levels for Lichess.
    """
    width, height, scale = resolution
    
    # Set viewport
    page.set_viewport_size({"width": width, "height": height})
    
    if scale != 1.0:
        # Simulate browser zoom
        page.evaluate(f"document.body.style.zoom = '{scale}';")
        
    page.wait_for_timeout(3000)
    
    # Trigger move from mock server
    page.evaluate("window.sendMockServerMessage({type: 'move', uci: 'g1f3', autoPlay: true});")
    
    page.wait_for_timeout(2000)
    
    # Check if knight is at f3 (cgKey='f3')
    f3_piece_exists = page.evaluate("""() => {
        const pieces = document.querySelectorAll('piece');
        for (const p of pieces) {
            if (p.cgKey === 'f3') return true;
        }
        return false;
    }""")
    assert f3_piece_exists == True, f"Move failed on Lichess resolution {width}x{height} with scale {scale}"
