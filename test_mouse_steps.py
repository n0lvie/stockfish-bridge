import pytest
from playwright.sync_api import sync_playwright

def test_chess_com_mouse_steps():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.chess.com/analysis", timeout=60000)
        page.wait_for_selector("wc-chess-board, chess-board", timeout=30000)
        page.wait_for_timeout(3000)
        
        coords = page.evaluate("""
            () => {
                const boardEl = document.querySelector('wc-chess-board, chess-board');
                const rect = boardEl.getBoundingClientRect();
                const squareSize = rect.width / 8;
                
                function getSquareCenter(file, rank) {
                    return {
                        x: rect.left + file * squareSize + squareSize / 2,
                        y: rect.top + (7 - rank) * squareSize + squareSize / 2
                    };
                }
                
                return {
                    from: getSquareCenter(4, 1), // e2
                    to: getSquareCenter(4, 3)    // e4
                };
            }
        """)
        
        page.mouse.move(coords['from']['x'], coords['from']['y'])
        page.wait_for_timeout(100)
        page.mouse.down()
        page.wait_for_timeout(100)
        
        page.mouse.move(coords['to']['x'], coords['to']['y'], steps=20)
        page.wait_for_timeout(100)
        page.mouse.up()
        
        page.wait_for_timeout(2000)
        
        e4_piece = page.evaluate("() => document.querySelector('.piece.square-54') !== null")
        print("Move registered:", e4_piece)
        browser.close()

if __name__ == "__main__":
    test_chess_com_mouse_steps()
