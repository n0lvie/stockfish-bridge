import pytest
from playwright.sync_api import sync_playwright

def test_chess_com_dump():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        page.goto("https://www.chess.com/analysis", timeout=60000)
        page.wait_for_selector("wc-chess-board, chess-board", timeout=30000)
        page.wait_for_timeout(3000)
        
        html = page.evaluate("""
            () => {
                const b = document.querySelector('wc-chess-board, chess-board');
                return b ? b.innerHTML : 'Not found';
            }
        """)
        with open('board_html.txt', 'w', encoding='utf-8') as f:
            f.write(html)
        browser.close()

if __name__ == "__main__":
    test_chess_com_dump()
