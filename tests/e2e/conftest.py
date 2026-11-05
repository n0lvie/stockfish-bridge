import os
import pytest
import server.bridge
import server.cv_module

try:
    import cv_module
except ImportError:
    cv_module = None

# Ensure mock_stockfish file exists for offline engine testing
MOCK_SF_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "mock_stockfish"))

@pytest.fixture(autouse=True, scope="session")
def ensure_mock_stockfish_file():
    if not os.path.exists(MOCK_SF_PATH):
        with open(MOCK_SF_PATH, "w") as f:
            f.write("")
    yield
    try:
        if os.path.exists(MOCK_SF_PATH):
            os.remove(MOCK_SF_PATH)
    except Exception:
        pass

@pytest.fixture(autouse=True)
def patch_board_detector_capture(monkeypatch, request):
    """
    Ensure BoardDetector.capture_screenshot is patched across all imported modules
    (server.bridge, server.cv_module, cv_module) to prevent Windows GDI BitBlt
    Access Denied errors during offline automated tests.
    """
    def _get_mock_image():
        from helpers import generate_synthetic_board
        # Check if test has mock_screenshot fixture
        if "mock_screenshot" in request.fixturenames:
            mock_s = request.getfixturevalue("mock_screenshot")
            if mock_s.image is not None:
                return mock_s.image
        return generate_synthetic_board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")

    def _safe_capture():
        img = _get_mock_image()
        return img, 0, 0

    monkeypatch.setattr(server.bridge.BoardDetector, "capture_screenshot", _safe_capture)
    monkeypatch.setattr(server.cv_module.BoardDetector, "capture_screenshot", _safe_capture)
    if cv_module and hasattr(cv_module, "BoardDetector"):
        monkeypatch.setattr(cv_module.BoardDetector, "capture_screenshot", _safe_capture)


CHESS_MOCK_HTML = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fixtures", "chess_com_mock.html"))
LICHESS_MOCK_HTML = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fixtures", "lichess_mock.html"))
COMMON_JS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "extension", "content", "common.js"))
CHESS_COM_JS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "extension", "content", "chess_com.js"))
LICHESS_JS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "extension", "content", "lichess.js"))


def _setup_mock_chrome_runtime(page):
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


@pytest.fixture
def mock_chesscom_page(page):
    """
    Offline interactive mock fixture for Chess.com loading tests/fixtures/chess_com_mock.html.
    Injects mock chrome.runtime, common.js, and chess_com.js.
    """
    file_url = f"file:///{CHESS_MOCK_HTML.replace(os.sep, '/')}"
    page.goto(file_url)
    _setup_mock_chrome_runtime(page)

    with open(COMMON_JS_PATH, "r", encoding="utf-8") as f:
        common_js = f.read()
    page.add_script_tag(content=common_js)

    with open(CHESS_COM_JS_PATH, "r", encoding="utf-8") as f:
        chess_com_js = f.read()
    page.add_script_tag(content=chess_com_js)

    page.wait_for_timeout(300)
    return page


@pytest.fixture
def mock_lichess_page(page):
    """
    Offline interactive mock fixture for Lichess loading tests/fixtures/lichess_mock.html.
    Injects mock chrome.runtime, common.js, and lichess.js.
    """
    file_url = f"file:///{LICHESS_MOCK_HTML.replace(os.sep, '/')}"
    page.goto(file_url)
    _setup_mock_chrome_runtime(page)

    with open(COMMON_JS_PATH, "r", encoding="utf-8") as f:
        common_js = f.read()
    page.add_script_tag(content=common_js)

    with open(LICHESS_JS_PATH, "r", encoding="utf-8") as f:
        lichess_js = f.read()
    page.add_script_tag(content=lichess_js)

    page.wait_for_timeout(300)
    return page


# Alias live fixtures to offline mocks to eliminate all live internet requests
@pytest.fixture
def live_chess_page(mock_chesscom_page):
    """
    Redirects live_chess_page to 100% offline mock_chesscom_page.
    """
    return mock_chesscom_page


@pytest.fixture
def live_lichess_page(mock_lichess_page):
    """
    Redirects live_lichess_page to 100% offline mock_lichess_page.
    """
    return mock_lichess_page


@pytest.fixture
def mock_html_page(page):
    """
    Backward-compatible mock_html_page starting at about:blank with chess_com.js.
    """
    page.goto("about:blank")
    _setup_mock_chrome_runtime(page)

    with open(COMMON_JS_PATH, "r", encoding="utf-8") as f:
        common_js = f.read()
    page.add_script_tag(content=common_js)

    with open(CHESS_COM_JS_PATH, "r", encoding="utf-8") as f:
        chess_com_js = f.read()
    page.add_script_tag(content=chess_com_js)

    return page


@pytest.fixture
def mock_board_page(mock_chesscom_page):
    """
    Backward-compatible mock_board_page pointing to the interactive mock_chesscom_page.
    """
    return mock_chesscom_page
