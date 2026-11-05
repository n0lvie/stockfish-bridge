import pytest
import time

def test_tier4_complete_game_simulated_chess_com(mock_board_page):
    """
    Tier 4: Complete game on simulated Chess.com board.
    Test FEN updates, move execution, and game over sequence.
    """
    page = mock_board_page
    # Set up starting board
    pieces_html = ""
    for file in range(1, 9):
        pieces_html += f'<div class="piece wp square-{file}2"></div>'
        pieces_html += f'<div class="piece bp square-{file}7"></div>'
    pieces_html += '<div class="piece wr square-11"></div><div class="piece wn square-21"></div><div class="piece wb square-31"></div><div class="piece wq square-41"></div><div class="piece wk square-51"></div><div class="piece wb square-61"></div><div class="piece wn square-71"></div><div class="piece wr square-81"></div>'
    pieces_html += '<div class="piece br square-18"></div><div class="piece bn square-28"></div><div class="piece bb square-38"></div><div class="piece bq square-48"></div><div class="piece bk square-58"></div><div class="piece bb square-68"></div><div class="piece bn square-78"></div><div class="piece br square-88"></div>'
    page.evaluate(f"document.querySelector('wc-chess-board').innerHTML = `{pieces_html}`;")
    page.wait_for_timeout(500)
    
    # 1. Start game
    messages = page.evaluate("window.getMockMessages();")
    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    assert len(state_msgs) > 0
    assert state_msgs[-1]['fen'].startswith('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR')
    
    # 2. Simulate move (e2e4)
    page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e2e4', autoPlay: true });")
    page.wait_for_timeout(500)
    
    # Check piece moved in DOM
    e4_piece = page.evaluate("document.querySelector('.piece.square-54, .piece.square-e4') !== null")
    assert e4_piece is True, "Piece did not move to e4 via event handlers"
    
    messages = page.evaluate("window.getMockMessages();")
    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    assert len(state_msgs) > 0
    assert '4P3' in state_msgs[-1]['fen'], "FEN did not update properly after e2e4"
    
    # 3. Simulate game over
    page.evaluate("const d = document.createElement('div'); d.className = 'game-over-modal'; d.textContent = '1-0'; document.body.appendChild(d);")
    page.wait_for_timeout(500)
    messages = page.evaluate("window.getMockMessages();")
    go_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'game_over']
    assert len(go_msgs) > 0
    assert go_msgs[-1]['result'] == '1-0'


def test_tier4_complete_game_simulated_lichess(mock_lichess_page):
    """
    Tier 4: Complete game on simulated Lichess board.
    Test FEN extraction, move execution via transform/cgKey, and game over.
    """
    page = mock_lichess_page
    page.wait_for_timeout(500)

    # 1. Start game verification
    messages = page.evaluate("window.getMockMessages();")
    init_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'init']
    assert len(init_msgs) > 0
    assert init_msgs[-1]['color'] == 'white'

    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    assert len(state_msgs) > 0
    assert state_msgs[-1]['fen'].startswith('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR')

    # 2. Simulate move (e2e4)
    page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e2e4', autoPlay: true });")
    page.wait_for_timeout(500)

    # Check piece moved to e4 on Lichess
    e4_piece_exists = page.evaluate("""() => {
        const pieces = document.querySelectorAll('piece');
        for (const p of pieces) {
            if (p.getAttribute('cg-key') === 'e4' || p.cgKey === 'e4') return true;
        }
        return false;
    }""")
    assert e4_piece_exists is True, "Piece did not move to e4 on Lichess"

    # Verify clock turn switched
    top_running = page.evaluate("document.querySelector('#top-clock').classList.contains('running')")
    assert top_running is True, "Clock did not switch to opponent after move"

    # 3. Simulate game over
    page.evaluate("""
        const modal = document.createElement('div');
        modal.className = 'cg-wrap';
        const result = document.createElement('div');
        result.className = 'result';
        result.textContent = '1-0';
        modal.appendChild(result);
        document.body.appendChild(modal);
    """)
    page.wait_for_timeout(500)
    messages = page.evaluate("window.getMockMessages();")
    go_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'game_over']
    assert len(go_msgs) > 0


def test_tier4_time_scramble(mock_board_page):
    """
    Tier 4: Time scramble (fast clock updates).
    Ensures rapid DOM updates for clock don't crash or flood WebSocket unnecessarily.
    """
    page = mock_board_page
    page.evaluate("window.getMockMessages();")
    
    # Rapidly change clock over 1 second (10 times)
    script = """
        for (let i = 0; i < 10; i++) {
            setTimeout(() => {
                const el = document.querySelector('.clock-bottom .time') || document.querySelector('.clock-bottom');
                if (el) el.textContent = `00:0${9-i}.${i}`;
            }, i * 100);
        }
    """
    page.evaluate(script)
    page.wait_for_timeout(1500)
    
    messages = page.evaluate("window.getMockMessages();")
    clock_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'clock']
    assert len(clock_msgs) > 0
    assert clock_msgs[-1]['ourTimeMs'] < 1000


def test_tier4_disconnect_reconnect_recovery(mock_board_page):
    """
    Tier 4: Disconnect & Reconnect recovery.
    """
    page = mock_board_page
    page.wait_for_timeout(300)
    
    # Signal disconnect
    page.evaluate("window.sendMockServerMessage({ type: 'connected', connected: false });")
    page.wait_for_timeout(200)
    page.evaluate("window.getMockMessages();")
    
    # Reconnect
    page.evaluate("window.sendMockServerMessage({ type: 'connected', connected: true });")
    page.wait_for_timeout(500)
    
    messages = page.evaluate("window.getMockMessages();")
    init_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'init']
    assert len(init_msgs) > 0, "System did not recover and send init on reconnect"


def test_tier4_unknown_board_layout_fallback(mock_board_page):
    """
    Tier 4: Unknown board layout fallback.
    Tests robustness when the board DOM structure changes unexpectedly.
    """
    page = mock_board_page
    # Inject unknown layout
    page.evaluate("document.querySelector('wc-chess-board').innerHTML = '<div class=\"weird-piece\" id=\"weird\"></div>';")
    page.wait_for_timeout(500)
    
    # Execute a move - it shouldn't crash, even if it fails
    page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e2e4' });")
    page.wait_for_timeout(500)
    
    # Just checking it didn't throw exceptions and still handles messages
    messages = page.evaluate("window.getMockMessages();")
    assert type(messages) is list
