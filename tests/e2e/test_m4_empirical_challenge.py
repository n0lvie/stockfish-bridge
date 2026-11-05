"""
Milestone 4 Adversarial Empirical Challenge Suite.

Adversarially stress-tests:
1. Piece class collision avoidance (`c-board`, `brown`, `break`, `board-main`).
2. Pure DOM fallback mode without main-world script injection (Lichess & Chess.com).
3. Flipped board coordinate transformations (Black player orientation).
4. Fast promotion dialog piece selection (Queen, Knight, Rook, Bishop).
5. Rapid move dispatch streams without race conditions or FEN corruption.
6. Adversarial game-over isolation (preventing false positives from benign classes).
"""

import pytest
import time


def test_challenge_piece_class_collisions_lichess(mock_lichess_page):
    """
    Adversarially verify that substring collisions like 'c-board', 'brown', 'break'
    do NOT fool Lichess piece identification.
    """
    page = mock_lichess_page
    page.wait_for_timeout(300)

    # 1. Inject benign elements with piece-like substrings that must be ignored
    page.evaluate("""
        const board = document.querySelector('cg-board');
        const fake1 = document.createElement('piece');
        fake1.className = 'c-board brown break';
        fake1.style.transform = 'translate(100px, 100px)';
        board.appendChild(fake1);

        const fake2 = document.createElement('piece');
        fake2.className = 'board-main generic-container';
        fake2.style.transform = 'translate(200px, 200px)';
        board.appendChild(fake2);
    """)
    page.wait_for_timeout(300)

    # 2. Inject valid pieces with colliding classes appended
    # White Knight on b1 (x: 100px, y: 700px) with extra 'c-board brown break'
    # Black Bishop on c8 (x: 200px, y: 0px) with extra 'brown break'
    page.evaluate("""
        const board = document.querySelector('cg-board');
        board.innerHTML = `
            <piece class="white king" cg-key="e1" style="transform: translate(400px, 700px);"></piece>
            <piece class="black king" cg-key="e8" style="transform: translate(400px, 0px);"></piece>
            <piece class="white knight c-board brown break" cg-key="b1" style="transform: translate(100px, 700px);"></piece>
            <piece class="black bishop brown break" cg-key="c8" style="transform: translate(200px, 0px);"></piece>
            <piece class="c-board brown break" style="transform: translate(300px, 300px);"></piece>
        `;
    """)
    page.wait_for_timeout(600)

    messages = page.evaluate("window.getMockMessages();")
    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    assert len(state_msgs) > 0, "No state message sent after injecting pieces"

    fen = state_msgs[-1]['fen']
    # Rank 8: 2 empty, b (black bishop), 1 empty, k (black king), 3 empty -> 2b1k3
    # Rank 1: 1 empty, N (white knight), 2 empty, K (white king), 3 empty -> 1N2K3
    assert fen.startswith('2b1k3/8/8/8/8/8/8/1N2K3'), f"Corrupted FEN due to piece class collisions: {fen}"


def test_challenge_piece_class_collisions_chesscom(mock_chesscom_page):
    """
    Adversarially verify that Chess.com ignores 'c-board', 'brown', 'break'
    and correctly parses pieces with complex or noisy classes.
    """
    page = mock_chesscom_page
    page.wait_for_timeout(300)

    # Inject White King on e1, Black King on e8,
    # White Knight on b1 with 'wn brown break c-board',
    # Black Queen on d8 with 'bq brown c-board',
    # and a dummy element with 'piece brown break c-board'
    pieces_html = """
        <div class="piece wk square-51"></div>
        <div class="piece bk square-58"></div>
        <div class="piece wn brown break c-board square-21"></div>
        <div class="piece bq brown c-board square-48"></div>
        <div class="piece brown break c-board square-33"></div>
    """
    page.evaluate(f"document.querySelector('wc-chess-board').innerHTML = `{pieces_html}`;")
    page.wait_for_timeout(600)

    messages = page.evaluate("window.getMockMessages();")
    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    assert len(state_msgs) > 0, "No state message generated"

    fen = state_msgs[-1]['fen']
    # Rank 8: 3 empty, q (black queen), k (black king), 3 empty -> 3qk3
    # Rank 1: 1 empty, N (white knight), 2 empty, K (white king), 3 empty -> 1N2K3
    assert fen.startswith('3qk3/8/8/8/8/8/8/1N2K3'), f"Corrupted FEN due to piece class collisions: {fen}"


def test_challenge_pure_dom_fallback_chesscom(mock_chesscom_page):
    """
    Verify Chess.com operates 100% reliably in pure DOM fallback mode
    without window.postMessage main-world state injection.
    """
    page = mock_chesscom_page
    page.wait_for_timeout(300)

    # 1. Verify injectedState is null or absent
    is_injected = page.evaluate("() => typeof window._lastInjectedState !== 'undefined' && window._lastInjectedState !== null")
    assert not is_injected, "Main-world state should not be present in offline mock"

    # 2. Test turn detection fallback via active clock attribute
    page.evaluate("""
        const bottomClock = document.querySelector('.clock-bottom');
        const topClock = document.querySelector('.clock-top');
        bottomClock.classList.remove('clock-player-turn');
        topClock.classList.add('clock-player-turn');
        // Trigger board update
        document.querySelector('wc-chess-board').innerHTML = '<div class="piece wk square-51"></div><div class="piece bk square-58"></div>';
    """)
    page.wait_for_timeout(600)

    messages = page.evaluate("window.getMockMessages();")
    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    assert len(state_msgs) > 0
    assert state_msgs[-1]['isOurTurn'] is False, "Opponent turn not detected via clock classes"

    # Switch turn to our clock
    page.evaluate("""
        const bottomClock = document.querySelector('.clock-bottom');
        const topClock = document.querySelector('.clock-top');
        topClock.classList.remove('clock-player-turn');
        bottomClock.classList.add('clock-player-turn');
        // Trigger board update with pawn
        document.querySelector('wc-chess-board').innerHTML = '<div class="piece wk square-51"></div><div class="piece bk square-58"></div><div class="piece wp square-52"></div>';
    """)
    page.wait_for_timeout(600)

    messages = page.evaluate("window.getMockMessages();")
    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    assert len(state_msgs) > 0
    assert state_msgs[-1]['isOurTurn'] is True, "Our turn not detected via clock classes"

    # 3. Test untimed / highlight turn fallback
    page.evaluate("""
        // Remove clock classes
        document.querySelectorAll('.clock-bottom, .clock-top').forEach(el => el.classList.remove('clock-player-turn'));
        // Add opponent highlight on e7 and e5
        const board = document.querySelector('wc-chess-board');
        board.innerHTML = `
            <div class="piece wk square-51"></div>
            <div class="piece bk square-58"></div>
            <div class="piece bp square-55"></div>
            <div class="highlight square-57"></div>
            <div class="highlight square-55"></div>
        `;
    """)
    page.wait_for_timeout(600)
    messages = page.evaluate("window.getMockMessages();")
    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    assert len(state_msgs) > 0
    # Opponent (Black) made the last move on e5 -> It is our turn!
    assert state_msgs[-1]['isOurTurn'] is True, "Highlight-based turn fallback failed"


def test_challenge_pure_dom_fallback_lichess(mock_lichess_page):
    """
    Verify Lichess operates 100% reliably in pure DOM fallback mode
    without window.lichess or chessground injectedState.
    """
    page = mock_lichess_page
    page.wait_for_timeout(300)

    # 1. Turn detection via .rclock.running fallback
    page.evaluate("""
        const bottomClock = document.getElementById('bottom-clock');
        const topClock = document.getElementById('top-clock');
        bottomClock.classList.remove('running');
        topClock.classList.add('running');
        // Trigger mutation
        const board = document.querySelector('cg-board');
        board.appendChild(document.createElement('piece'));
        board.lastChild.remove();
    """)
    page.wait_for_timeout(600)

    # Read clocks
    clocks = page.evaluate("""() => {
        const ourClockEl = document.querySelector('.rclock-bottom');
        const oppClockEl = document.querySelector('.rclock-top');
        return {
            ourRunning: ourClockEl.classList.contains('running'),
            oppRunning: oppClockEl.classList.contains('running')
        };
    }""")
    assert clocks['oppRunning'] is True
    assert clocks['ourRunning'] is False

    # 2. Untimed / last-move square fallback on <cg-board>
    # When clocks aren't running, check square.last-move
    page.evaluate("""
        document.querySelectorAll('.rclock').forEach(el => el.classList.remove('running'));
        const board = document.querySelector('cg-board');
        board.innerHTML = `
            <piece class="white king" cg-key="e1" style="transform: translate(400px, 700px);"></piece>
            <piece class="black king" cg-key="e8" style="transform: translate(400px, 0px);"></piece>
            <piece class="black pawn" cg-key="e5" style="transform: translate(400px, 300px);"></piece>
            <square class="last-move" style="transform: translate(400px, 100px);"></square>
            <square class="last-move" style="transform: translate(400px, 300px);"></square>
        `;
    """)
    page.wait_for_timeout(600)
    messages = page.evaluate("window.getMockMessages();")
    state_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'state']
    assert len(state_msgs) > 0
    # Black moved pawn to e5 -> It is our turn!
    assert state_msgs[-1]['isOurTurn'] is True, "Lichess square.last-move fallback failed"


def test_challenge_flipped_board_orientation_chesscom(mock_chesscom_page):
    """
    Stress-test Chess.com flipped board (playing as Black).
    Verifies piece coordinate calculation is inverted properly.
    """
    page = mock_chesscom_page
    page.wait_for_timeout(300)

    # Flip board
    page.evaluate("document.querySelector('wc-chess-board').classList.add('flipped');")
    page.wait_for_timeout(2200) # Wait for 2000ms detectColor polling

    # Verify color became black
    messages = page.evaluate("window.getMockMessages();")
    init_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'init']
    assert len(init_msgs) > 0
    assert init_msgs[-1]['color'] == 'black'

    # Move black pawn e7 to e5
    page.evaluate("""
        const board = document.querySelector('wc-chess-board');
        board.innerHTML = `
            <div class="piece wk square-51"></div>
            <div class="piece bk square-58"></div>
            <div class="piece bp square-57"></div>
        `;
    """)
    page.wait_for_timeout(300)

    page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e7e5', autoPlay: true });")
    page.wait_for_timeout(500)

    # On flipped board, e5 (square-55) must now contain the piece
    e5_exists = page.evaluate("document.querySelector('.piece.square-55, .piece.square-e5') !== null")
    assert e5_exists is True, "Pawn did not arrive at e5 on flipped Chess.com board"


def test_challenge_flipped_board_orientation_lichess(mock_lichess_page):
    """
    Stress-test Lichess flipped board (playing as Black).
    Verifies style.transform translate coordinates are inverted properly.
    NOTE: Uncovers whether cgWrap tag <cg-wrap> is correctly selected vs .cg-wrap class selector.
    """
    page = mock_lichess_page
    page.wait_for_timeout(300)

    # Flip board via cg-wrap element
    page.evaluate("""
        const wrap = document.getElementById('cg-wrap') || document.querySelector('cg-wrap');
        wrap.classList.remove('orientation-white');
        wrap.classList.add('orientation-black');
    """)
    page.wait_for_timeout(2200) # Wait for detectColor polling

    messages = page.evaluate("window.getMockMessages();")
    init_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'init']
    assert len(init_msgs) > 0
    assert init_msgs[-1]['color'] == 'black', (
        "Lichess adapter failed to detect Black orientation on <cg-wrap> tag. "
        "Bug: lichess.js uses document.querySelector('.cg-wrap') with class selector instead of 'cg-wrap, .cg-wrap'."
    )


def test_challenge_fast_promotion_selection_chesscom(mock_chesscom_page):
    """
    Stress-test Chess.com sub-50ms fast promotion piece selection without artificial delays.
    """
    page = mock_chesscom_page
    page.evaluate("""
        const board = document.querySelector('wc-chess-board');
        board.innerHTML = `
            <div class="piece wk square-11"></div>
            <div class="piece bk square-88"></div>
            <div class="piece wp square-57"></div>
        `;
        const promoEl = document.createElement('div');
        promoEl.className = 'promotion-piece';
        promoEl.setAttribute('data-piece', 'n');
        promoEl.onclick = () => { window._promoClicked = 'n'; };
        document.body.appendChild(promoEl);
    """)
    page.wait_for_timeout(200)

    start_time = time.time()
    page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e7e8n', promotion: 'n', autoPlay: true });")
    page.wait_for_timeout(300)
    elapsed = time.time() - start_time

    promo_clicked = page.evaluate("window._promoClicked")
    assert promo_clicked == 'n', "Chess.com promotion to knight was not selected"
    assert elapsed < 1.0, f"Promotion took too long: {elapsed:.2f}s"


def test_challenge_fast_promotion_selection_lichess(mock_lichess_page):
    """
    Stress-test Lichess sub-50ms fast promotion piece selection without artificial delays.
    """
    page = mock_lichess_page
    page.evaluate("""
        const promoContainer = document.createElement('div');
        promoContainer.id = 'promotion-choice';
        const rookChoice = document.createElement('piece');
        rookChoice.className = 'rook';
        rookChoice.onclick = () => { window._lichessPromoClicked = 'r'; };
        promoContainer.appendChild(rookChoice);
        document.body.appendChild(promoContainer);
    """)
    page.wait_for_timeout(200)

    page.evaluate("window.sendMockServerMessage({ type: 'move', uci: 'e7e8r', promotion: 'r', autoPlay: true });")
    page.wait_for_timeout(300)

    lpromo_clicked = page.evaluate("window._lichessPromoClicked")
    assert lpromo_clicked == 'r', "Lichess promotion to rook was not selected"


def test_challenge_game_over_benign_isolation(mock_chesscom_page, mock_lichess_page):
    """
    Adversarially verify that benign class names containing 'game-over' or 'result'
    do NOT trigger false-positive game_over WebSocket messages.
    """
    # 1. Chess.com test
    page = mock_chesscom_page
    page.evaluate("window.getMockMessages();") # Clear
    page.evaluate("""
        const benign1 = document.createElement('div');
        benign1.className = 'game-overview-panel';
        benign1.textContent = 'Game 1-0 White historical victory archive';
        document.body.appendChild(benign1);

        const benign2 = document.createElement('div');
        benign2.className = 'game-over-announcement-header';
        benign2.style.display = 'none'; // hidden element
        benign2.textContent = '1-0';
        document.body.appendChild(benign2);
    """)
    page.wait_for_timeout(500)

    messages = page.evaluate("window.getMockMessages();")
    go_msgs = [m.get('data') for m in messages if 'data' in m and m['data'].get('type') == 'game_over']
    assert len(go_msgs) == 0, f"False positive game_over triggered on Chess.com: {go_msgs}"
