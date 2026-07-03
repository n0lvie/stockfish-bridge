import json
from playwright.sync_api import sync_playwright

def explore():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://lichess.org/setup/ai", timeout=60000)
        
        # Start a game against AI
        try:
            page.click("button[type='submit']", timeout=5000)
            page.wait_for_selector("cg-board", timeout=10000)
        except:
            pass
            
        page.wait_for_timeout(3000)
        
        props = page.evaluate("""
            () => {
                const result = { lichess: {} };
                if (window.lichess) {
                    result.lichess.keys = Object.keys(window.lichess);
                    if (window.lichess.clock) result.lichess.clockKeys = Object.keys(window.lichess.clock);
                    if (window.lichess.info) result.lichess.infoKeys = Object.keys(window.lichess.info);
                }
                const cgBoard = document.querySelector('cg-board');
                if (cgBoard && cgBoard.parentElement && cgBoard.parentElement.chessground) {
                    const cg = cgBoard.parentElement.chessground;
                    result.cgState = {
                        turnColor: cg.state.turnColor,
                        orientation: cg.state.orientation
                    };
                }
                
                // Get clock elements
                result.clockText = Array.from(document.querySelectorAll('.clock, .rclock')).map(e => e.textContent);
                return JSON.stringify(result, null, 2);
            }
        """)
        
        print("LICHESS LIVE PROPS:\n", props)
        browser.close()

if __name__ == '__main__':
    explore()
