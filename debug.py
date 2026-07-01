from playwright.sync_api import sync_playwright
import os

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("about:blank")
    page.on("console", lambda msg: print(f"CONSOLE: {msg.text}"))
    page.evaluate("""
        window.chrome = {
            runtime: {
                lastError: null,
                sendMessage: function(msg, callback) {
                    window._mockMessages = window._mockMessages || [];
                    window._mockMessages.push(msg);
                    if (callback) {
                        setTimeout(() => callback({ connected: true, autoPlay: true }), 0);
                    }
                },
                onMessage: {
                    addListener: function(listener) {
                        window._mockListener = listener;
                    }
                }
            }
        };
        window._mockMessages = [];
        window.getMockMessages = function() {
            const msgs = window._mockMessages.slice();
            window._mockMessages = [];
            return msgs;
        };
    """)
    common_js_path = os.path.abspath("extension/content/common.js")
    with open(common_js_path, "r", encoding="utf-8") as f:
        page.add_script_tag(content=f.read())
    chess_com_js_path = os.path.abspath("extension/content/chess_com.js")
    with open(chess_com_js_path, "r", encoding="utf-8") as f:
        page.add_script_tag(content=f.read())
    page.evaluate("""
        document.body.innerHTML = `<wc-chess-board class="flipped">
            <div class="piece wk square-51"></div>
            <div class="piece bk square-58"></div>
        </wc-chess-board>`;
    """)
    page.wait_for_timeout(1000)
    print(page.evaluate("window.getMockMessages()"))
    browser.close()
