import json
from playwright.sync_api import sync_playwright

def explore():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://lichess.org/analysis", timeout=60000)
        page.wait_for_selector("cg-board", timeout=30000)
        page.wait_for_timeout(3000)
        
        # Check if move is sent
        moved = page.evaluate("""
            () => {
                try {
                    if (window.lichess && window.lichess.analysis) {
                        window.lichess.analysis.playUci("e2e4");
                        return true;
                    } else {
                        const cgBoard = document.querySelector('cg-board');
                        if (cgBoard && cgBoard.parentElement && cgBoard.parentElement.chessground) {
                            const cg = cgBoard.parentElement.chessground;
                            cg.move("e2", "e4");
                            return true;
                        }
                    }
                } catch (e) { return e.toString(); }
                return false;
            }
        """)
        print("Moved via API?", moved)
        page.wait_for_timeout(3000)
        
        fen = page.evaluate("""
            () => {
                if (window.lichess && window.lichess.analysis) {
                    return window.lichess.analysis.node.fen;
                } else {
                    const cgBoard = document.querySelector('cg-board');
                    if (cgBoard && cgBoard.parentElement && cgBoard.parentElement.chessground) {
                        return cgBoard.parentElement.chessground.state.fen;
                    }
                }
                return null;
            }
        """)
        print("FEN:", fen)
        
        browser.close()

if __name__ == '__main__':
    explore()
