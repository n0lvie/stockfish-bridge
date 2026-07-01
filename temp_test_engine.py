import asyncio
import logging
import sys
from server.engine import StockfishEngine

logging.basicConfig(level=logging.DEBUG)

async def stress_test():
    engine = StockfishEngine(engine_path=sys.executable)
    # We need to pass the script as argument, but StockfishEngine doesn't support arguments in engine_path directly?
    # Wait, asyncio.create_subprocess_exec uses the first argument as program, rest as args.
    # We can patch start() in StockfishEngine just for this test, or subclass it.
    pass

class FakeStockfishEngine(StockfishEngine):
    async def start(self):
        if self._alive:
            return
            
        self._alive = True
        self._ready_event.clear()
        self._uciok_event.clear()
        
        # Use python fake_engine.py
        self._process = await asyncio.create_subprocess_exec(
            sys.executable, "fake_engine.py",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )
        
        self._read_task = asyncio.ensure_future(self._read_stdout())
        
        await self._send("uci")
        await asyncio.wait_for(self._uciok_event.wait(), timeout=5.0)
        
        await self._send("isready")
        await asyncio.wait_for(self._ready_event.wait(), timeout=5.0)

async def run_stress():
    engine = FakeStockfishEngine()
    await engine.start()
    
    # Send go infinite and immediately stop
    for i in range(10):
        await engine.set_position("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        await engine.go_infinite()
        await asyncio.sleep(0.01) # Sleep briefly to allow engine to start searching
        await engine.stop() # Wait for stop? The stop method returns awaitable
        await asyncio.sleep(0.05) # Wait for bestmove?
        
    await asyncio.sleep(1)
    print(f"Engine generation: {engine._search_generation}, completed: {engine._completed_searches}")
    
    await engine.quit()

if __name__ == "__main__":
    asyncio.run(run_stress())
