import pytest
from playwright.sync_api import sync_playwright

def test_chess_com_game_object():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.chess.com/analysis", timeout=60000)
        page.wait_for_selector("wc-chess-board", timeout=30000)
        page.wait_for_timeout(3000)
        
        info = page.evaluate("""
            () => {
                const board = document.querySelector('wc-chess-board');
                if (!board || !board.game) return 'no game object';
                
                let methods = [];
                for (let key in board.game) {
                    if (typeof board.game[key] === 'function') {
                        methods.push(key);
                    }
                }
                
                return {
                    keys: Object.keys(board.game),
                    methods: methods,
                    fen: board.game.getFEN ? board.game.getFEN() : null
                };
            }
        """)
        
        print("GAME INFO:")
        print(info)
        browser.close()

if __name__ == "__main__":
    test_chess_com_game_object()
