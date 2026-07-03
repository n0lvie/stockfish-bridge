import pytest
from playwright.sync_api import sync_playwright

def test_chess_com_screenshot():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.chess.com/analysis", timeout=60000)
        page.wait_for_selector("wc-chess-board, chess-board", timeout=30000)
        page.wait_for_timeout(3000)
        page.screenshot(path="debug_screenshot.png")
        
        info = page.evaluate("""
            () => {
                const from = { x: window.innerWidth / 2, y: window.innerHeight / 2 }; // Just an example
                const boardEl = document.querySelector('wc-chess-board, chess-board');
                const rect = boardEl.getBoundingClientRect();
                const squareSize = rect.width / 8;
                const file = 4; // e
                const rank = 1; // 2
                const x = rect.left + file * squareSize + squareSize / 2;
                const y = rect.top + (7 - rank) * squareSize + squareSize / 2;
                
                const target = document.elementFromPoint(x, y);
                return {
                    targetTag: target ? target.tagName : 'null',
                    targetClass: target ? target.className : 'null',
                    x, y
                };
            }
        """)
        
        print("TARGET INFO:", info)
        browser.close()

if __name__ == "__main__":
    test_chess_com_screenshot()
