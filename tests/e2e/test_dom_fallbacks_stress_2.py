
def test_stress_piece_identification_substring_bug(mock_board_page):
    pieces_html = '<div class="piece wq pointer-down square-41"></div><div class="piece br slowplaying square-18"></div><div class="piece wk square-51"></div><div class="piece bk square-58"></div>'
    mock_board_page.evaluate(f"document.querySelector('wc-chess-board').innerHTML = `{pieces_html}`;")
    mock_board_page.wait_for_timeout(1000)
    messages = mock_board_page.evaluate("window.getMockMessages();")
    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    
    assert len(state_msgs) > 0
    fen = state_msgs[-1]['fen']
    # If correct: 'r3k3/8/8/8/8/8/8/3QK3 w - - 0 1'
    assert fen.startswith('r3k3/8/8/8/8/8/8/3QK3'), f"Buggy FEN: {fen}"

def test_stress_clock_nested_elements(mock_board_page):
    script = """
        document.querySelectorAll('.clock-component').forEach(e => e.remove());
        const clocks = `
        <div class="clock-component" style="position:absolute; top:10px;">
            <div class="clock-component" style="position:absolute; top:10px;">12:00</div>
        </div>
        <div class="clock-component" style="position:absolute; top:500px;">05:00</div>
        `;
        document.body.insertAdjacentHTML('beforeend', clocks);
    """
    mock_board_page.evaluate(script)
    mock_board_page.wait_for_timeout(1000)
    messages = mock_board_page.evaluate("window.getMockMessages();")
    clock_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'clock']
    assert len(clock_msgs) > 0
    assert clock_msgs[-1]['ourTimeMs'] == 300000
    assert clock_msgs[-1]['oppTimeMs'] == 720000
