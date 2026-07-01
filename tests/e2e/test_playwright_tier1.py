import pytest
import time
from playwright.sync_api import expect

def test_chess_com_extraction_live(live_chess_page):
    """
    Test that the chess.com adapter can successfully detect the board and send state updates.
    Includes FEN, turn, playingAs (color), clocks, and game over status.
    """
    page = live_chess_page
    
    page.wait_for_timeout(3000)
    messages = page.evaluate("window.getMockMessages();")
    
    # Verify Init message
    init_msgs = [m['data'] for m in messages if 'data' in m and m['data'].get('type') == 'init']
    assert len(init_msgs) > 0, "No init message sent"
    assert 'color' in init_msgs[0], "playingAs (color) missing in init"
    
    # Verify State message
    state_msgs = [m['data'] for m in messages if 'data' in m and m['data'].get('type') == 'state']
    assert len(state_msgs) > 0, "No state message sent to server"
    
    latest_state = state_msgs[-1]
    assert 'fen' in latest_state
    assert latest_state['fen'].count('/') == 7, "Invalid FEN structure extracted"
    assert 'isOurTurn' in latest_state, "Turn data missing"
    assert 'ourTimeMs' in latest_state, "Clock data missing"
    assert 'oppTimeMs' in latest_state, "Clock data missing"

def test_chess_com_game_over_extraction(live_chess_page):
    """
    Simulate a game over modal and verify that the adapter sends a game_over event.
    """
    page = live_chess_page
    page.wait_for_timeout(2000)
    
    # Inject a mock game over modal
    page.evaluate("""
        const modal = document.createElement('div');
        modal.className = 'game-over-modal';
        modal.textContent = 'White wins by Checkmate';
        document.body.appendChild(modal);
    """)
    page.wait_for_timeout(1000)
    
    messages = page.evaluate("window.getMockMessages();")
    game_over_msgs = [m['data'] for m in messages if 'data' in m and m['data'].get('type') == 'game_over']
    assert len(game_over_msgs) > 0, "Game over event not detected"
    assert game_over_msgs[0]['result'] == '1-0', f"Incorrect game over result: {game_over_msgs[0].get('result')}"

def test_chess_com_move_execution_live(live_chess_page):
    """
    Test that the chess.com adapter's move execution triggers piece movement in the DOM.
    """
    page = live_chess_page
    page.wait_for_timeout(3000)
    
    page.evaluate("window.sendMockServerMessage({type: 'move', uci: 'e2e4', autoPlay: true});")
    page.wait_for_timeout(2000)
    
    e4_piece = page.evaluate("document.querySelector('.piece.square-e4') !== null")
    assert e4_piece == True, "Piece did not move to e4 via DOM events"

def test_lichess_extraction_live(live_lichess_page):
    """
    Test that the lichess adapter can successfully detect the board and send state updates.
    """
    page = live_lichess_page
    page.wait_for_timeout(3000)
    
    messages = page.evaluate("window.getMockMessages();")
    
    # Verify Init message
    init_msgs = [m['data'] for m in messages if 'data' in m and m['data'].get('type') == 'init']
    assert len(init_msgs) > 0, "No init message sent"
    assert 'color' in init_msgs[0], "playingAs (color) missing in init"
    
    state_msgs = [m['data'] for m in messages if 'data' in m and m['data'].get('type') == 'state']
    assert len(state_msgs) > 0, "No state message sent to server"
    
    latest_state = state_msgs[-1]
    assert 'fen' in latest_state
    assert latest_state['fen'].count('/') == 7, "Invalid FEN structure extracted"
    assert 'isOurTurn' in latest_state, "Turn data missing"
    assert 'ourTimeMs' in latest_state, "Clock data missing"
    assert 'oppTimeMs' in latest_state, "Clock data missing"

def test_lichess_game_over_extraction(live_lichess_page):
    """
    Simulate a game over modal and verify that the adapter sends a game_over event.
    """
    page = live_lichess_page
    page.wait_for_timeout(2000)
    
    # Inject a mock game over state for Lichess
    page.evaluate("""
        const modal = document.createElement('div');
        modal.className = 'cg-wrap';
        const result = document.createElement('div');
        result.className = 'result';
        result.textContent = '0-1';
        modal.appendChild(result);
        document.body.appendChild(modal);
    """)
    page.wait_for_timeout(1000)
    
    messages = page.evaluate("window.getMockMessages();")
    game_over_msgs = [m['data'] for m in messages if 'data' in m and m['data'].get('type') == 'game_over']
    assert len(game_over_msgs) > 0, "Game over event not detected"

def test_lichess_move_execution_live(live_lichess_page):
    """
    Test that the lichess adapter's move execution triggers piece movement in the DOM.
    """
    page = live_lichess_page
    page.wait_for_timeout(3000)
    
    page.evaluate("window.sendMockServerMessage({type: 'move', uci: 'e2e4', autoPlay: true});")
    page.wait_for_timeout(2000)
    
    e4_piece_exists = page.evaluate("""() => {
        const pieces = document.querySelectorAll('piece');
        for (const p of pieces) {
            if (p.cgKey === 'e4') return true;
        }
        return false;
    }""")
    assert e4_piece_exists == True, "Piece did not move to e4 on Lichess"
