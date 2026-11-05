import pytest
import time
from playwright.sync_api import expect

def test_tier3_interaction_1_2_move_triggers_board_update(mock_board_page):
    """
    Interaction 1+2: Move Execution triggers Board Detection update.
    Ensure that when a move is executed via DOM, the observer catches it
    and sends a new state message over WebSocket.
    """
    page = mock_board_page
    # Setup initial board with kings to pass stability validation
    pieces_html = '<div class="piece wk square-51"></div><div class="piece bk square-58"></div><div class="piece wp square-52"></div>'
    page.evaluate(f"document.querySelector('wc-chess-board').innerHTML = `{pieces_html}`;")
    page.wait_for_timeout(500)
    
    # Clear previous messages
    page.evaluate("window.getMockMessages();")
    
    # Execute move
    page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e2e4' });")
    page.wait_for_timeout(500)
    
    # Check if state update was triggered
    messages = page.evaluate("window.getMockMessages();")
    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    assert len(state_msgs) > 0, "Move execution did not trigger a state update"

def test_tier3_interaction_1_2_live(live_chess_page):
    page = live_chess_page
    page.wait_for_timeout(3000)
    page.evaluate("window.getMockMessages();") # Clear
    
    page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e2e4', autoPlay: true });")
    page.wait_for_timeout(2000)
    
    messages = page.evaluate("window.getMockMessages();")
    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    assert len(state_msgs) > 0, "Move execution did not trigger a state update"
    assert any('fen' in s for s in state_msgs), "State update missing FEN after move"

def test_tier3_interaction_1_3_live(live_chess_page):
    """
    Interaction 1+3: System Recovery + Board Detection.
    Flip the board and ensure the color is re-detected correctly.
    """
    page = live_chess_page
    page.wait_for_timeout(3000)
    page.evaluate("window.getMockMessages();") # Clear
    
    # Flip board
    page.evaluate("document.querySelector('wc-chess-board, chess-board').classList.add('flipped');")
    page.wait_for_timeout(3000) # color check is every 2000ms
    
    messages = page.evaluate("window.getMockMessages();")
    init_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'init']
    assert len(init_msgs) > 0, "No new init message sent upon board flip"
    assert init_msgs[-1]['color'] == 'black', "Color not detected correctly after flip"

def test_tier3_interaction_2_4_autoplay(mock_board_page):
    """
    Interaction 2+4: WebSocket Orchestration controls Move Execution via autoPlay flag.
    """
    page = mock_board_page
    pieces_html = '<div class="piece wp square-52"></div>'
    page.evaluate(f"document.querySelector('wc-chess-board').innerHTML = `{pieces_html}`;")
    page.wait_for_timeout(500)
    
    # Disable autoPlay
    page.evaluate("window.sendMockServerMessage({ type: 'autoplay_changed', autoPlay: false });")
    page.wait_for_timeout(100)
    page.evaluate("window.getMockMessages();") # Clear message queue
    
    # Send move
    page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e2e4' });")
    page.wait_for_timeout(500)
    
    # We expect the move was NOT executed
    messages = page.evaluate("window.getMockMessages();")
    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    assert len(state_msgs) == 0, "Move executed despite autoPlay=false"

def test_tier3_interaction_3_4_reconnect(mock_board_page):
    """
    Interaction 3+4: System Recovery triggers WebSocket Orchestration.
    When the connection drops and reconnects, an init message should be sent.
    """
    page = mock_board_page
    page.wait_for_timeout(500)
    page.evaluate("window.getMockMessages();")
    
    # Simulate reconnect
    page.evaluate("window.sendMockServerMessage({ type: 'connected', connected: true });")
    page.wait_for_timeout(500)
    
    messages = page.evaluate("window.getMockMessages();")
    init_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'init']
    assert len(init_msgs) > 0, "Did not send init upon WebSocket reconnect"
