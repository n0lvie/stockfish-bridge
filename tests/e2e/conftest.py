import os
import pytest

@pytest.fixture
def mock_html_page(page):
    """
    Sets up a page with mock chrome.runtime, common.js, and chess_com.js injected.
    It returns the page and a mock message collector.
    """
    page.goto("about:blank")
    
    # 1. Mock chrome.runtime
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
        window.sendMockServerMessage = function(data) {
            if (window._mockListener) {
                window._mockListener({ source: 'background', data: data }, {}, () => {});
            }
        };
    """)
    
    # 2. Inject common.js
    common_js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "extension", "content", "common.js"))
    with open(common_js_path, "r", encoding="utf-8") as f:
        common_js = f.read()
    page.add_script_tag(content=common_js)
    
    # 3. Inject chess_com.js
    chess_com_js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "extension", "content", "chess_com.js"))
    with open(chess_com_js_path, "r", encoding="utf-8") as f:
        chess_com_js = f.read()
    page.add_script_tag(content=chess_com_js)
    
    return page

@pytest.fixture
def live_chess_page(page):
    """
    Sets up a page on chess.com/analysis with the extension injected.
    """
    page.goto("https://www.chess.com/analysis", timeout=60000)
    page.wait_for_selector("wc-chess-board, chess-board", timeout=30000)
    page.wait_for_timeout(3000)
    
    # Mock chrome.runtime before injecting extension
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
        window.sendMockServerMessage = function(data) {
            if (window._mockListener) {
                window._mockListener({ source: 'background', data: data }, {}, () => {});
            }
        };
    """)
    
    common_js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "extension", "content", "common.js"))
    with open(common_js_path, "r", encoding="utf-8") as f:
        common_js = f.read()
    page.add_script_tag(content=common_js)
    
    chess_com_js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "extension", "content", "chess_com.js"))
    with open(chess_com_js_path, "r", encoding="utf-8") as f:
        chess_com_js = f.read()
    page.add_script_tag(content=chess_com_js)
    
    return page

@pytest.fixture
def mock_board_page(mock_html_page):
    html_content = """
    <div class="board-layout-component">
        <div class="clock-component clock-top">02:15</div>
        <wc-chess-board style="width: 800px; height: 800px; display: block; position: relative;">
        </wc-chess-board>
        <div class="clock-component clock-bottom clock-player-turn">01:30.5</div>
    </div>
    """
    mock_html_page.evaluate(f"document.body.innerHTML = `{html_content}`;")
    return mock_html_page


@pytest.fixture
def live_lichess_page(page):
    """
    Sets up a page on lichess.org/editor with the extension injected.
    """
    page.goto("https://lichess.org/editor", timeout=60000)
    page.wait_for_selector("cg-board", timeout=30000)
    page.wait_for_timeout(3000)
    
    # Mock chrome.runtime before injecting extension
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
        window.sendMockServerMessage = function(data) {
            if (window._mockListener) {
                window._mockListener({ source: 'background', data: data }, {}, () => {});
            }
        };
    """)
    
    common_js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "extension", "content", "common.js"))
    with open(common_js_path, "r", encoding="utf-8") as f:
        common_js = f.read()
    page.add_script_tag(content=common_js)
    
    lichess_js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "extension", "content", "lichess.js"))
    with open(lichess_js_path, "r", encoding="utf-8") as f:
        lichess_js = f.read()
    page.add_script_tag(content=lichess_js)
    
    return page
