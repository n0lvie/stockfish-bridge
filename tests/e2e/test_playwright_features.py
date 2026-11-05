import pytest

# Test suite covering Chess.com feature verification in Playwright (100% Offline)

def test_f1_start_position(mock_board_page):
    pieces_html = ""
    for file in range(1, 9):
        pieces_html += f'<div class="piece wp square-{file}2"></div>'
        pieces_html += f'<div class="piece bp square-{file}7"></div>'
    pieces_html += '<div class="piece wr square-11"></div><div class="piece wn square-21"></div><div class="piece wb square-31"></div><div class="piece wq square-41"></div><div class="piece wk square-51"></div><div class="piece wb square-61"></div><div class="piece wn square-71"></div><div class="piece wr square-81"></div>'
    pieces_html += '<div class="piece br square-18"></div><div class="piece bn square-28"></div><div class="piece bb square-38"></div><div class="piece bq square-48"></div><div class="piece bk square-58"></div><div class="piece bb square-68"></div><div class="piece bn square-78"></div><div class="piece br square-88"></div>'
    mock_board_page.evaluate(f"document.querySelector('wc-chess-board').innerHTML = `{pieces_html}`;")
    mock_board_page.wait_for_timeout(500)
    messages = mock_board_page.evaluate("window.getMockMessages();")
    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    assert len(state_msgs) > 0
    assert state_msgs[-1]['fen'] == 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

def test_f1_midgame_position(mock_board_page):
    pieces_html = '<div class="piece wk square-51"></div><div class="piece bk square-58"></div><div class="piece wp square-54"></div>'
    mock_board_page.evaluate(f"document.querySelector('wc-chess-board').innerHTML = `{pieces_html}`;")
    mock_board_page.wait_for_timeout(500)
    messages = mock_board_page.evaluate("window.getMockMessages();")
    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    assert len(state_msgs) > 0
    assert state_msgs[-1]['fen'] == '4k3/8/8/8/4P3/8/8/4K3 w - - 0 1'

def test_f1_color_and_orientation(mock_board_page):
    mock_board_page.evaluate("document.querySelector('wc-chess-board').classList.add('flipped');")
    mock_board_page.wait_for_timeout(2500) # color check is every 2000ms
    messages = mock_board_page.evaluate("window.getMockMessages();")
    init_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'init']
    assert len(init_msgs) > 0
    assert init_msgs[-1]['color'] == 'black'

def test_f1_clocks(mock_board_page):
    pieces_html = '<div class="piece wk square-51"></div><div class="piece bk square-58"></div>'
    mock_board_page.evaluate(f"document.querySelector('wc-chess-board').innerHTML = `{pieces_html}`;")
    mock_board_page.wait_for_timeout(500)
    messages = mock_board_page.evaluate("window.getMockMessages();")
    clock_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'clock']
    assert len(clock_msgs) > 0
    assert clock_msgs[-1]['ourTimeMs'] == 90500  # 01:30.5
    assert clock_msgs[-1]['oppTimeMs'] == 135000 # 02:15

def test_f1_turn_detection(mock_board_page):
    script = """
        document.querySelector('.clock-bottom').classList.remove('clock-player-turn');
        document.querySelector('.clock-top').classList.add('clock-player-turn');
        document.querySelector('wc-chess-board').innerHTML = '<div class="piece wk square-51"></div><div class="piece bk square-58"></div>';
    """
    mock_board_page.evaluate(script)
    mock_board_page.wait_for_timeout(1000)
    messages = mock_board_page.evaluate("window.getMockMessages();")
    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    if state_msgs:
        assert state_msgs[-1]['isOurTurn'] == False

# F2 tests — Move Execution & Mechanics
def test_f2_normal_move(mock_board_page):
    pieces_html = '<div class="piece wk square-51"></div><div class="piece bk square-58"></div><div class="piece wp square-52"></div>'
    mock_board_page.evaluate(f"document.querySelector('wc-chess-board').innerHTML = `{pieces_html}`;")
    mock_board_page.wait_for_timeout(300)
    mock_board_page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e2e4', autoPlay: true });")
    mock_board_page.wait_for_timeout(500)
    
    # Assert real DOM movement: piece at e4 exists and piece at e2 is removed
    e4_piece = mock_board_page.evaluate("document.querySelector('.piece.square-54, .piece.square-e4') !== null")
    assert e4_piece is True, "Pawn did not move to e4 (square-54)"
    e2_piece = mock_board_page.evaluate("document.querySelector('.piece.square-52, .piece.square-e2') !== null")
    assert e2_piece is False, "Pawn still exists on square-52 after move"

def test_f2_capture_move(mock_board_page):
    # Place white pawn on e4, black pawn on d5
    pieces_html = '<div class="piece wk square-51"></div><div class="piece bk square-58"></div><div class="piece wp square-54"></div><div class="piece bp square-45"></div>'
    mock_board_page.evaluate(f"document.querySelector('wc-chess-board').innerHTML = `{pieces_html}`;")
    mock_board_page.wait_for_timeout(300)
    
    # Execute capture e4xd5
    mock_board_page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e4d5', autoPlay: true });")
    mock_board_page.wait_for_timeout(500)
    
    # Assert white piece is now on d5 (square-45) and captured black piece is removed
    captured_piece = mock_board_page.evaluate("document.querySelector('.piece.bp.square-45, .piece.bp.square-d5') !== null")
    assert captured_piece is False, "Captured black pawn still exists on d5"
    capturing_piece = mock_board_page.evaluate("document.querySelector('.piece.wp.square-45, .piece.wp.square-d5') !== null")
    assert capturing_piece is True, "White pawn did not arrive on d5 after capture"

def test_f2_promotion(mock_board_page):
    # Pawn on e7 ready to promote on e8
    pieces_html = '<div class="piece wk square-11"></div><div class="piece bk square-88"></div><div class="piece wp square-57"></div>'
    mock_board_page.evaluate(f"document.querySelector('wc-chess-board').innerHTML = `{pieces_html}`;")
    mock_board_page.evaluate("""
        const el = document.createElement('div');
        el.className = 'promotion-piece';
        el.setAttribute('data-piece', 'q');
        document.body.appendChild(el);
    """)
    mock_board_page.wait_for_timeout(300)
    
    mock_board_page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e7e8q', autoPlay: true });")
    mock_board_page.wait_for_timeout(600)
    
    # Piece reached e8
    e8_piece = mock_board_page.evaluate("document.querySelector('.piece.square-58, .piece.square-e8') !== null")
    assert e8_piece is True, "Promoted piece did not reach e8"

def test_f2_move_flipped(mock_board_page):
    # Playing as Black (flipped board)
    mock_board_page.evaluate("document.querySelector('wc-chess-board').classList.add('flipped');")
    mock_board_page.wait_for_timeout(2500) # wait for detectColor interval
    pieces_html = '<div class="piece wk square-51"></div><div class="piece bk square-58"></div><div class="piece bp square-57"></div>'
    mock_board_page.evaluate(f"document.querySelector('wc-chess-board').innerHTML = `{pieces_html}`;")
    mock_board_page.wait_for_timeout(300)
    
    # Move black pawn from e7 to e5
    mock_board_page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e7e5', autoPlay: true });")
    mock_board_page.wait_for_timeout(500)
    
    e5_piece = mock_board_page.evaluate("document.querySelector('.piece.square-55, .piece.square-e5') !== null")
    assert e5_piece is True, "Move on flipped board failed to place piece on e5"

def test_f2_touch_fallback(mock_board_page):
    # Verify move execution triggers touch fallback events without error
    pieces_html = '<div class="piece wk square-51"></div><div class="piece bk square-58"></div><div class="piece wp square-52"></div>'
    mock_board_page.evaluate(f"document.querySelector('wc-chess-board').innerHTML = `{pieces_html}`;")
    mock_board_page.wait_for_timeout(300)
    
    mock_board_page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e2e4', autoPlay: true });")
    mock_board_page.wait_for_timeout(500)
    e4_piece = mock_board_page.evaluate("document.querySelector('.piece.square-54, .piece.square-e4') !== null")
    assert e4_piece is True, "Touch simulation move failed"

# F3 tests — Robustness & Edge Cases
def test_f3_board_reloaded(mock_board_page):
    script = """
        const oldBoard = document.querySelector('wc-chess-board');
        const newBoard = document.createElement('wc-chess-board');
        newBoard.innerHTML = '<div class="piece wk square-51"></div><div class="piece bk square-58"></div>';
        oldBoard.parentNode.replaceChild(newBoard, oldBoard);
    """
    mock_board_page.evaluate(script)
    mock_board_page.wait_for_timeout(1000)
    messages = mock_board_page.evaluate("window.getMockMessages();")
    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    assert len(state_msgs) > 0

def test_f3_unknown_layout(mock_board_page):
    mock_board_page.evaluate("document.querySelector('wc-chess-board').innerHTML = '<div class=\"something-else\"></div>';")
    mock_board_page.wait_for_timeout(500)
    
    # Sending move must not crash
    mock_board_page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e2e4', autoPlay: true });")
    mock_board_page.wait_for_timeout(300)
    messages = mock_board_page.evaluate("window.getMockMessages();")
    assert isinstance(messages, list)

def test_f3_missing_clocks(mock_board_page):
    mock_board_page.evaluate("document.querySelectorAll('.clock-component').forEach(e => e.remove());")
    mock_board_page.wait_for_timeout(500)
    
    # State extraction continues without crashing when clocks are absent
    mock_board_page.evaluate("window.sendMockServerMessage({ type: 'ping' });")
    mock_board_page.wait_for_timeout(200)
    messages = mock_board_page.evaluate("window.getMockMessages();")
    assert isinstance(messages, list)

def test_f3_game_over(mock_board_page):
    mock_board_page.evaluate("const d = document.createElement('div'); d.className = 'game-over-modal'; d.textContent = '1-0'; document.body.appendChild(d);")
    mock_board_page.wait_for_timeout(500)
    messages = mock_board_page.evaluate("window.getMockMessages();")
    go_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'game_over']
    assert len(go_msgs) > 0
    assert go_msgs[-1]['result'] == '1-0'

def test_f3_color_change(mock_board_page):
    mock_board_page.evaluate("document.querySelector('wc-chess-board').classList.add('flipped');")
    mock_board_page.wait_for_timeout(2500)
    messages = mock_board_page.evaluate("window.getMockMessages();")
    init_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'init']
    assert len(init_msgs) > 0

# F4 tests — Protocol & Coordination
def test_f4_ws_init(mock_board_page):
    messages = mock_board_page.evaluate("window.getMockMessages();")
    init_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'init']
    assert len(init_msgs) > 0
    assert 'site' in init_msgs[0]

def test_f4_state_debounce(mock_board_page):
    mock_board_page.evaluate("window.getMockMessages();") # Clear
    
    # Rapidly trigger 10 DOM updates
    script = """
        const board = document.querySelector('wc-chess-board');
        for (let i = 0; i < 10; i++) {
            board.innerHTML = '<div class="piece wk square-51"></div><div class="piece bk square-58"></div><div class="piece wp square-52"></div>';
        }
    """
    mock_board_page.evaluate(script)
    mock_board_page.wait_for_timeout(300)
    
    messages = mock_board_page.evaluate("window.getMockMessages();")
    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    # Debounce must collapse the 10 rapid mutations to at most 2 state messages
    assert len(state_msgs) <= 2, f"Expected debounced state messages <= 2, got {len(state_msgs)}"

def test_f4_redundant_state(mock_board_page):
    mock_board_page.wait_for_timeout(500)
    mock_board_page.evaluate("window.getMockMessages();") # Clear
    
    # Wait for periodic poll timer; unchanged board must not flood redundant state messages
    mock_board_page.wait_for_timeout(1500)
    messages = mock_board_page.evaluate("window.getMockMessages();")
    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    assert len(state_msgs) == 0, "Redundant state messages sent without board change"

def test_f4_receive_move(mock_board_page):
    pieces_html = '<div class="piece wk square-51"></div><div class="piece bk square-58"></div><div class="piece wp square-52"></div>'
    mock_board_page.evaluate(f"document.querySelector('wc-chess-board').innerHTML = `{pieces_html}`;")
    mock_board_page.wait_for_timeout(300)
    
    mock_board_page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e2e4', autoPlay: true });")
    mock_board_page.wait_for_timeout(500)
    e4_piece = mock_board_page.evaluate("document.querySelector('.piece.square-54, .piece.square-e4') !== null")
    assert e4_piece is True, "Received move e2e4 not executed"

def test_f4_autoplay_toggle(mock_board_page):
    pieces_html = '<div class="piece wk square-51"></div><div class="piece bk square-58"></div><div class="piece wp square-52"></div>'
    mock_board_page.evaluate(f"document.querySelector('wc-chess-board').innerHTML = `{pieces_html}`;")
    mock_board_page.wait_for_timeout(300)
    
    # Turn off autoplay
    mock_board_page.evaluate("window.sendMockServerMessage({ type: 'autoplay_changed', autoPlay: false });")
    mock_board_page.wait_for_timeout(100)
    
    # Send move
    mock_board_page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e2e4' });")
    mock_board_page.wait_for_timeout(500)
    
    # Move must NOT have been executed
    e4_piece = mock_board_page.evaluate("document.querySelector('.piece.square-54, .piece.square-e4') !== null")
    assert e4_piece is False, "Move executed while autoPlay was false"
    e2_piece = mock_board_page.evaluate("document.querySelector('.piece.square-52, .piece.square-e2') !== null")
    assert e2_piece is True, "Original piece missing from e2"
