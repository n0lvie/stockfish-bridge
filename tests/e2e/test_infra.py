import pytest
import asyncio
from helpers import MockExtensionClient, MockDashboardClient

def test_websocket_server_startup_and_handshake(mock_server):
    bridge, port = mock_server
    
    async def run_test():
        ext_url = f"ws://127.0.0.1:{port}/ws"
        ext_client = MockExtensionClient(ext_url)
        
        await ext_client.connect()
        try:
            # Upon connection, the extension client expects to receive autoplay state
            msg = await ext_client.recv_message()
            assert msg is not None
            assert msg["type"] == "autoplay_changed"
            assert msg["autoPlay"] is True
            
            # Send init command
            await ext_client.send_init()
            
            # Receive status message
            status_msg = await ext_client.recv_message()
            assert status_msg is not None
            assert status_msg["type"] == "status"
            assert status_msg["state"] == "ready"
        finally:
            await ext_client.close()

    asyncio.run(run_test())

def test_dashboard_settings_sync(mock_server):
    bridge, port = mock_server
    
    async def run_test():
        dash_url = f"ws://127.0.0.1:{port}/ws_dashboard"
        dash_client = MockDashboardClient(dash_url)
        
        await dash_client.connect()
        try:
            # Upon connection, dashboard receives current settings and cv_state
            settings_msg = await dash_client.recv_message()
            assert settings_msg is not None
            assert settings_msg["type"] == "settings"
            
            cv_state_msg = await dash_client.recv_message()
            assert cv_state_msg is not None
            assert cv_state_msg["type"] == "cv_state"
            
            # Simulating dashboard sending settings update
            new_settings = {
                "autoplay": False,
                "threads": 4,
                "safety_buffer": 3000
            }
            await dash_client.send_update_settings(new_settings)
            await asyncio.sleep(0.2) # allow time for server to apply and broadcast
            
            # Verify server state was updated
            assert bridge._autoplay is False
            assert bridge._strategy.safety_buffer_ms == 3000
            assert bridge._settings["threads"] == 4
            
        finally:
            await dash_client.close()

    asyncio.run(run_test())
