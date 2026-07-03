import pytest
from playwright.sync_api import sync_playwright

def test_chess_com_screenshot():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print("Navigating to chess.com/analysis...")
        page.goto("https://www.chess.com/analysis", timeout=60000)
        
        page.wait_for_selector("wc-chess-board, chess-board", timeout=30000)
        page.wait_for_timeout(3000)
        
        page.screenshot(path="board_screenshot.png")
        
        browser.close()

if __name__ == "__main__":
    test_chess_com_screenshot()
