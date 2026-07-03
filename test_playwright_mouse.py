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
        
        coords = page.evaluate("""
            () => {
                const boardEl = document.querySelector('wc-chess-board, chess-board');
                const rect = boardEl.getBoundingClientRect();
                const squareSize = rect.width / 8;
                const isFlipped = boardEl.classList.contains('flipped');
                
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
                
                return {
                    from: getSquareCenter('e2'),
                    to: getSquareCenter('e4')
                };
            }
        """)
        
        # Use playwright's mouse to do the drag
        page.mouse.move(coords['from']['x'], coords['from']['y'])
        page.mouse.down()
        page.wait_for_timeout(30)
        
        # Move slightly to start drag
        page.mouse.move(coords['from']['x'], coords['from']['y'] - 10)
        page.wait_for_timeout(30)
        
        page.mouse.move(coords['to']['x'], coords['to']['y'])
        page.wait_for_timeout(30)
        page.mouse.up()
        
        page.wait_for_timeout(2000)
        
        e4_piece = page.evaluate("() => document.querySelector('.piece.square-e4') !== null")
        assert e4_piece == True, "The move was not registered by the DOM. square-e4 is empty!"
        
        print("Move successfully registered by Chess.com!")
        browser.close()

if __name__ == "__main__":
    test_chess_com_move_simulation()
