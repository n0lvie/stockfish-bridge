import pytest
from playwright.sync_api import sync_playwright

def test_chess_com_move_simulation():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print("Navigating to chess.com/analysis...")
        page.goto("https://www.chess.com/analysis", timeout=60000)
        page.wait_for_selector("wc-chess-board, chess-board", timeout=30000)
        page.wait_for_timeout(3000)
        
        moved = page.evaluate("""
            async () => {
                const boardEl = document.querySelector('wc-chess-board, chess-board');
                if (!boardEl) return false;
                
                const rect = boardEl.getBoundingClientRect();
                const squareSize = rect.width / 8;
                const isFlipped = boardEl.classList.contains('flipped');
                
                const delay = ms => new Promise(res => setTimeout(res, ms));
                
                function getSquareCenter(square) {
                    const file = square.charCodeAt(0) - 97;
                    const rank = parseInt(square[1]) - 1;
                    let x, y;
                    if (isFlipped) {
                        x = rect.left + (7 - file) * squareSize + squareSize / 2;
                        y = rect.top + rank * squareSize + squareSize / 2;
                    } else {
                        x = rect.left + file * squareSize + squareSize / 2;
                        y = rect.top + (7 - rank) * squareSize + squareSize / 2;
                    }
                    return { x, y };
                }
                
                function simulatePointerEvent(type, target, x, y) {
                    const event = new PointerEvent(type, {
                        bubbles: true, cancelable: true, composed: true, view: window,
                        clientX: x, clientY: y, screenX: x, screenY: y,
                        pointerId: 1, pointerType: 'mouse', isPrimary: true,
                        button: 0, buttons: type === 'pointerup' ? 0 : 1
                    });
                    target.dispatchEvent(event);
                }
                
                function getDeepElement(x, y) {
                    let el = document.elementFromPoint(x, y);
                    while (el && el.shadowRoot) {
                        const shadowEl = el.shadowRoot.elementFromPoint(x, y);
                        if (!shadowEl || shadowEl === el) break;
                        el = shadowEl;
                    }
                    return el;
                }
                
                const fromCoords = getSquareCenter('e2');
                const toCoords = getSquareCenter('e4');
                
                const targetElement = getDeepElement(fromCoords.x, fromCoords.y) || boardEl;
                
                simulatePointerEvent('pointerdown', targetElement, fromCoords.x, fromCoords.y);
                await delay(30);
                
                simulatePointerEvent('pointermove', targetElement, toCoords.x, toCoords.y);
                await delay(30);
                
                simulatePointerEvent('pointerup', targetElement, toCoords.x, toCoords.y);
                
                return true;
            }
        """)
        
        assert moved == True, "Failed to inject and execute move script."
        
        page.wait_for_timeout(2000)
        
        e4_piece = page.evaluate("() => document.querySelector('.piece.square-e4') !== null")
        if not e4_piece:
            # check shadow root
            e4_piece = page.evaluate("() => document.querySelector('wc-chess-board, chess-board').shadowRoot?.querySelector('.piece.square-e4') !== null")
        assert e4_piece == True, "The move was not registered by the DOM. square-e4 is empty!"
        
        print("Move successfully registered by Chess.com!")
        browser.close()

if __name__ == "__main__":
    test_chess_com_move_simulation()
