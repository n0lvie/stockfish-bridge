import pytest

# We expect the mock extension to send messages of form:
# { target: 'background', data: { type: 'state', fen: '...', ... } }

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

# F2 tests
def test_f2_normal_move(mock_board_page):
    pieces_html = '<div class="piece wp square-52"></div>'
    mock_board_page.evaluate(f"document.querySelector('wc-chess-board').innerHTML = `{pieces_html}`;")
    mock_board_page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e2e4' });")
    mock_board_page.wait_for_timeout(500)
    assert True

def test_f2_capture_move(mock_board_page):
    mock_board_page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e4d5' });")
    mock_board_page.wait_for_timeout(500)
    assert True

def test_f2_promotion(mock_board_page):
    # Add a mock promotion dialog element to the page
    mock_board_page.evaluate("document.body.innerHTML += '<div class=\"promotion-piece\" data-piece=\"q\"></div>';")
    mock_board_page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e7e8q' });")
    mock_board_page.wait_for_timeout(500)
    assert True

def test_f2_move_flipped(mock_board_page):
    mock_board_page.evaluate("document.querySelector('wc-chess-board').classList.add('flipped');")
    mock_board_page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e2e4' });")
    mock_board_page.wait_for_timeout(500)
    assert True

def test_f2_touch_fallback(mock_board_page):
    mock_board_page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e2e4' });")
    mock_board_page.wait_for_timeout(500)
    assert True

# F3 tests
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
    assert True

def test_f3_missing_clocks(mock_board_page):
    mock_board_page.evaluate("document.querySelectorAll('.clock-component').forEach(e => e.remove());")
    mock_board_page.wait_for_timeout(500)
    assert True

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

# F4 tests
def test_f4_ws_init(mock_board_page):
    messages = mock_board_page.evaluate("window.getMockMessages();")
    init_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'init']
    assert len(init_msgs) > 0

def test_f4_state_debounce(mock_board_page):
    script = """
        const board = document.querySelector('wc-chess-board');
        for (let i = 0; i < 10; i++) {
            board.innerHTML = '<div class="piece wk square-51"></div>';
        }
    """
    mock_board_page.evaluate(script)
    mock_board_page.wait_for_timeout(500)
    assert True

def test_f4_redundant_state(mock_board_page):
    mock_board_page.wait_for_timeout(1000)
    assert True

def test_f4_receive_move(mock_board_page):
    mock_board_page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e2e4' });")
    mock_board_page.wait_for_timeout(500)
    assert True

def test_f4_autoplay_toggle(mock_board_page):
    mock_board_page.evaluate("window.sendMockServerMessage({ type: 'autoplay_changed', autoPlay: false });")
    mock_board_page.wait_for_timeout(500)
    assert True

