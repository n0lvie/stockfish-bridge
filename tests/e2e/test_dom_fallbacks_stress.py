import pytest

def test_f1_clocks_multiple_containers(mock_board_page):
    # Simulate an adversarial scenario where there are extra clock containers,
    # e.g., sidebars or hidden clocks.
    script = """
        // Remove existing .clock-bottom and .clock-top to trigger the generic container fallback
        document.querySelectorAll('.clock-bottom, .clock-top').forEach(el => {
            el.classList.remove('clock-bottom');
            el.classList.remove('clock-top');
        });

        // Add dummy clock components that might confuse the sort logic
        const dummyTop = document.createElement('div');
        dummyTop.className = 'clock-component';
        dummyTop.textContent = '10:00';
        dummyTop.style.position = 'absolute';
        dummyTop.style.top = '-1000px'; // Extremely high up

        const dummyBottom = document.createElement('div');
        dummyBottom.className = 'clock-component';
        dummyBottom.textContent = '10:00';
        dummyBottom.style.position = 'absolute';
        dummyBottom.style.top = '5000px'; // Extremely low down

        document.body.appendChild(dummyTop);
        document.body.appendChild(dummyBottom);

        // Put pieces on board to trigger state update
        document.querySelector('wc-chess-board').innerHTML = '<div class="piece wk square-51"></div><div class="piece bk square-58"></div>';
    """
    mock_board_page.evaluate(script)
    mock_board_page.wait_for_timeout(1000)
    messages = mock_board_page.evaluate("window.getMockMessages();")
    clock_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'clock']
    
    assert len(clock_msgs) > 0
    # Our time was 01:30.5 (90500 ms) and opponent was 02:15 (135000 ms)
    # The dummy clocks have 10:00 (600000 ms). If the logic incorrectly picks the dummies,
    # it will return 600000.
    
    last_msg = clock_msgs[-1]
    assert last_msg['ourTimeMs'] == 90500, f"Expected 90500, got {last_msg['ourTimeMs']}"
    assert last_msg['oppTimeMs'] == 135000, f"Expected 135000, got {last_msg['oppTimeMs']}"

def test_f1_turn_multiple_containers(mock_board_page):
    script = """
        // Remove existing .clock-bottom and .clock-top classes
        document.querySelectorAll('.clock-bottom, .clock-top').forEach(el => {
            el.classList.remove('clock-bottom');
            el.classList.remove('clock-top');
            el.classList.remove('clock-player-turn');
        });

        // Set one of the middle containers to have clock-player-turn
        const containers = document.querySelectorAll('.clock-component');
        // Let's assume the actual top clock gets the turn
        containers[0].classList.add('clock-player-turn'); // Opponent's clock

        // Add dummy clock components
        const dummyTop = document.createElement('div');
        dummyTop.className = 'clock-component';
        dummyTop.style.position = 'absolute';
        dummyTop.style.top = '-1000px';

        const dummyBottom = document.createElement('div');
        dummyBottom.className = 'clock-component clock-player-turn'; // Make it our turn on the dummy
        dummyBottom.style.position = 'absolute';
        dummyBottom.style.top = '5000px';

        document.body.appendChild(dummyTop);
        document.body.appendChild(dummyBottom);

        document.querySelector('wc-chess-board').innerHTML = '<div class="piece wk square-51"></div><div class="piece bk square-58"></div>';
    """
    mock_board_page.evaluate(script)
    mock_board_page.wait_for_timeout(1000)
    messages = mock_board_page.evaluate("window.getMockMessages();")
    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    
    if state_msgs:
        # Since opponent clock has the turn, ourTurn should be false.
        # But if the dummy clocks are selected, it might return false or true incorrectly.
        last_state = state_msgs[-1]
        assert last_state['isOurTurn'] == False, "Expected opponent turn"

def test_f3_game_over_adversarial(mock_board_page):
    script = """
        // Add a benign element that happens to match [class*="game-over"]
        const fakeGameOver = document.createElement('div');
        fakeGameOver.className = 'some-unrelated-game-overview';
        fakeGameOver.textContent = 'A great 1-0 victory in history!';
        document.body.appendChild(fakeGameOver);

        // Put pieces on board to trigger state update
        document.querySelector('wc-chess-board').innerHTML = '<div class="piece wk square-51"></div><div class="piece bk square-58"></div>';
    """
    mock_board_page.evaluate(script)
    mock_board_page.wait_for_timeout(1000)
    messages = mock_board_page.evaluate("window.getMockMessages();")
    
    # Check if a game_over message was sent
    go_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'game_over']
    
    # We should NOT have triggered a game over from a fake element
    assert len(go_msgs) == 0, f"False positive game over triggered: {go_msgs}"
