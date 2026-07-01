with open('tests/e2e/conftest.py', 'a') as f:
    f.write('''
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
''')
