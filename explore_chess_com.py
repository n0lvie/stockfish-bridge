import json
from playwright.sync_api import sync_playwright

def explore():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.chess.com/play/computer", timeout=60000)
        page.wait_for_selector("wc-chess-board, chess-board", timeout=30000)
        
        # Click the 'Play' or 'Choose' button if there is a modal
        try:
            page.click("button.ui_v5-button-primary", timeout=3000)
        except:
            pass
            
        page.wait_for_timeout(3000)
        
        moved = page.evaluate("""
            () => {
                const board = document.querySelector('wc-chess-board, chess-board');
                try {
                    if (board.game && board.game.move) {
                        board.game.move({from: "e2", to: "e4"});
                        return true;
                    }
                } catch (e) {}
                return false;
            }
        """)
        print("Moved via board.game.move?", moved)
        page.wait_for_timeout(3000) # Wait for computer response
        
        fen = page.evaluate("""
            () => {
                const board = document.querySelector('wc-chess-board, chess-board');
                return board.game.getFEN();
            }
        """)
        print("FEN:", fen)
        
        browser.close()

if __name__ == '__main__':
    explore()
