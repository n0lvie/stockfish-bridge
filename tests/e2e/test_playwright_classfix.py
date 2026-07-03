import pytest
from playwright.sync_api import sync_playwright

def test_chess_com_move_simulation():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print("Navigating to chess.com/analysis...")
        page.goto("https://www.chess.com/analysis", timeout=60000)
        
        print("Waiting for chess board to load...")
        page.wait_for_selector("wc-chess-board, chess-board", timeout=30000)
        
        page.wait_for_timeout(3000)
        
        print("Simulating pointer events to move pawn from e2 to e4...")
        
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
                        bubbles: true, cancelable: true,
                        clientX: x, clientY: y,
                        pointerId: 1, pointerType: 'mouse'
                    });
                    target.dispatchEvent(event);
                }
                
                function simulateMouseEvent(type, target, x, y) {
                    const event = new MouseEvent(type, {
                        bubbles: true, cancelable: true,
                        clientX: x, clientY: y
                    });
                    target.dispatchEvent(event);
                }
                
                const fromCoords = getSquareCenter('e2');
                const toCoords = getSquareCenter('e4');
                const targetElement = document.elementFromPoint(fromCoords.x, fromCoords.y) || boardEl;
                
                simulatePointerEvent('pointerdown', targetElement, fromCoords.x, fromCoords.y);
                simulateMouseEvent('mousedown', targetElement, fromCoords.x, fromCoords.y);
                await delay(30);
                
                simulatePointerEvent('pointermove', boardEl, toCoords.x, toCoords.y);
                simulateMouseEvent('mousemove', boardEl, toCoords.x, toCoords.y);
                await delay(30);
                
                simulatePointerEvent('pointerup', boardEl, toCoords.x, toCoords.y);
                simulateMouseEvent('mouseup', boardEl, toCoords.x, toCoords.y);
                
                return true;
            }
        """)
        
        assert moved == True, "Failed to inject and execute move script."
        
        page.wait_for_timeout(2000)
        
        print("Verifying if DOM updated piece position to square-54...")
        e4_piece = page.evaluate("() => document.querySelector('.piece.square-54') !== null")
        assert e4_piece == True, "The move was not registered by the DOM. square-54 is empty!"
        
        print("Move successfully registered by Chess.com!")
        browser.close()

if __name__ == "__main__":
    test_chess_com_move_simulation()
