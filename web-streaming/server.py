#!/usr/bin/env python3
"""
ChainWorld Web Streaming Server

Manages Luanti game sessions with noVNC streaming for browser-based play.
Supports both single-player and multiplayer modes.
"""

import asyncio
import logging
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Configuration
LUANTI_BIN = os.environ.get("LUANTI_BIN", str(Path(__file__).parent.parent / "bin" / "luanti"))
LUANTI_ROOT = os.environ.get("LUANTI_ROOT", str(Path(__file__).parent.parent))
WORLD_DIR = os.environ.get("WORLD_DIR", str(Path(__file__).parent.parent / "worlds" / "chainworld_test"))
BASE_DISPLAY = 50  # Start virtual displays from :50
BASE_VNC_PORT = 5950  # VNC ports start from 5950
BASE_WS_PORT = 6080  # WebSocket ports start from 6080
LUANTI_SERVER_PORT = 30000  # Default Luanti server port
MAX_SESSIONS = 10

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")
logger = logging.getLogger("chainworld")

app = FastAPI(title="ChainWorld Web Streaming", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session management
sessions: dict[str, dict] = {}
server_process: Optional[subprocess.Popen] = None
server_display: Optional[int] = None


class SessionRequest(BaseModel):
    player_name: str = "Player"
    mode: str = "singleplayer"  # "singleplayer" or "multiplayer"


class SessionResponse(BaseModel):
    session_id: str
    ws_port: int
    player_name: str
    mode: str
    status: str


def find_free_slot() -> Optional[int]:
    """Find a free display/port slot."""
    used_slots = {s["slot"] for s in sessions.values()}
    for i in range(MAX_SESSIONS):
        if i not in used_slots:
            return i
    return None


def start_xvfb(display_num: int, width: int = 1280, height: int = 720) -> subprocess.Popen:
    """Start a virtual framebuffer."""
    cmd = [
        "Xvfb", f":{display_num}",
        "-screen", "0", f"{width}x{height}x24",
        "-ac",  # Disable access control
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    return proc


def start_luanti_singleplayer(display_num: int, player_name: str, session_id: str, width: int = 1280, height: int = 720) -> subprocess.Popen:
    """Start Luanti in singleplayer mode on a virtual display.
    
    Copies the world to a per-session temp directory to avoid world lock conflicts.
    """
    env = os.environ.copy()
    env["DISPLAY"] = f":{display_num}"
    env["HOME"] = os.environ.get("HOME", "/home/ubuntu")

    # Copy world to per-session directory to avoid lock conflicts
    session_world_dir = Path(LUANTI_ROOT) / "worlds" / f"chainworld_session_{session_id}"
    source_world_dir = Path(WORLD_DIR)
    if source_world_dir.exists():
        if session_world_dir.exists():
            shutil.rmtree(session_world_dir)
        shutil.copytree(source_world_dir, session_world_dir)
        logger.info(f"Copied world to {session_world_dir}")
    else:
        logger.warning(f"Source world not found: {source_world_dir}")

    cmd = [
        LUANTI_BIN,
        "--worldname", f"chainworld_session_{session_id}",
        "--name", player_name,
        "--go",
    ]

    logger.info(f"Starting Luanti singleplayer: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        env=env,
        cwd=LUANTI_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(3)
    if proc.poll() is not None:
        stderr_out = proc.stderr.read().decode() if proc.stderr else ""
        logger.error(f"Luanti crashed on startup (exit code {proc.returncode}): {stderr_out[:500]}")
    else:
        logger.info(f"Luanti started successfully (PID {proc.pid})")
    return proc


def start_luanti_server(display_num: int) -> subprocess.Popen:
    """Start Luanti in server mode."""
    env = os.environ.copy()
    env["DISPLAY"] = f":{display_num}"
    env["HOME"] = os.environ.get("HOME", "/home/ubuntu")

    cmd = [
        LUANTI_BIN,
        "--server",
        "--worldname", "chainworld_test",
        "--port", str(LUANTI_SERVER_PORT),
    ]

    proc = subprocess.Popen(
        cmd,
        env=env,
        cwd=LUANTI_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(2)
    return proc


def start_luanti_client(display_num: int, player_name: str, server_addr: str = "127.0.0.1", width: int = 1280, height: int = 720) -> subprocess.Popen:
    """Start Luanti client connecting to a server."""
    env = os.environ.copy()
    env["DISPLAY"] = f":{display_num}"
    env["HOME"] = os.environ.get("HOME", "/home/ubuntu")

    cmd = [
        LUANTI_BIN,
        "--name", player_name,
        "--address", server_addr,
        "--port", str(LUANTI_SERVER_PORT),
        "--go",
    ]

    proc = subprocess.Popen(
        cmd,
        env=env,
        cwd=LUANTI_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(2)
    return proc


def start_x11vnc(display_num: int, vnc_port: int) -> subprocess.Popen:
    """Start x11vnc server for a display."""
    cmd = [
        "x11vnc",
        "-display", f":{display_num}",
        "-rfbport", str(vnc_port),
        "-nopw",  # No password
        "-shared",
        "-forever",
        "-noxdamage",
        "-cursor", "arrow",
        "-nowf",
        "-noxfixes",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    return proc


def start_websockify(ws_port: int, vnc_port: int) -> subprocess.Popen:
    """Start websockify to bridge WebSocket to VNC."""
    cmd = [
        "websockify",
        "--web", str(Path(__file__).parent / "novnc"),
        str(ws_port),
        f"localhost:{vnc_port}",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    return proc


def kill_session(session_id: str):
    """Kill all processes for a session."""
    if session_id not in sessions:
        return
    session = sessions[session_id]
    for proc_name in ["websockify", "x11vnc", "luanti", "xvfb"]:
        proc = session.get(proc_name)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    proc.kill()
                except OSError:
                    pass
    # Clean up session world directory
    session_world_dir = Path(LUANTI_ROOT) / "worlds" / f"chainworld_session_{session_id}"
    if session_world_dir.exists():
        try:
            shutil.rmtree(session_world_dir)
            logger.info(f"Cleaned up session world: {session_world_dir}")
        except OSError as e:
            logger.warning(f"Failed to clean up session world: {e}")
    del sessions[session_id]


# Serve static files and noVNC
static_dir = Path(__file__).parent / "static"
novnc_dir = Path(__file__).parent / "novnc"
app.mount("/novnc", StaticFiles(directory=str(novnc_dir)), name="novnc")
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main page."""
    index_path = static_dir / "index.html"
    return FileResponse(str(index_path))


@app.get("/play", response_class=HTMLResponse)
async def play_page():
    """Serve the game player page."""
    player_path = static_dir / "player.html"
    return FileResponse(str(player_path))


@app.post("/api/sessions", response_model=SessionResponse)
async def create_session(req: SessionRequest):
    """Create a new game session."""
    slot = find_free_slot()
    if slot is None:
        raise HTTPException(status_code=503, detail="No free slots available")

    session_id = str(uuid.uuid4())[:8]
    display_num = BASE_DISPLAY + slot
    vnc_port = BASE_VNC_PORT + slot
    ws_port = BASE_WS_PORT + slot

    try:
        # Start virtual display
        xvfb_proc = start_xvfb(display_num)

        if req.mode == "multiplayer":
            # Start Luanti client connecting to the server
            luanti_proc = start_luanti_client(display_num, req.player_name)
        else:
            # Start singleplayer
            luanti_proc = start_luanti_singleplayer(display_num, req.player_name, session_id)

        # Start VNC server
        vnc_proc = start_x11vnc(display_num, vnc_port)

        # Start WebSocket proxy
        ws_proc = start_websockify(ws_port, vnc_port)

        sessions[session_id] = {
            "slot": slot,
            "display": display_num,
            "vnc_port": vnc_port,
            "ws_port": ws_port,
            "player_name": req.player_name,
            "mode": req.mode,
            "xvfb": xvfb_proc,
            "luanti": luanti_proc,
            "x11vnc": vnc_proc,
            "websockify": ws_proc,
            "created_at": time.time(),
        }

        return SessionResponse(
            session_id=session_id,
            ws_port=ws_port,
            player_name=req.player_name,
            mode=req.mode,
            status="running",
        )

    except Exception as e:
        # Cleanup on failure
        kill_session(session_id)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions")
async def list_sessions():
    """List active sessions."""
    result = []
    for sid, s in sessions.items():
        luanti_alive = s["luanti"].poll() is None if s.get("luanti") else False
        result.append({
            "session_id": sid,
            "ws_port": s["ws_port"],
            "player_name": s["player_name"],
            "mode": s["mode"],
            "status": "running" if luanti_alive else "stopped",
            "created_at": s["created_at"],
        })
    return {"sessions": result}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Stop and remove a session."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    kill_session(session_id)
    return {"status": "deleted"}


@app.post("/api/server/start")
async def start_server():
    """Start the Luanti multiplayer server."""
    global server_process, server_display

    if server_process and server_process.poll() is None:
        return {"status": "already_running", "port": LUANTI_SERVER_PORT}

    # Use a dedicated display for the server
    server_display = BASE_DISPLAY + MAX_SESSIONS
    start_xvfb(server_display)
    server_process = start_luanti_server(server_display)

    return {"status": "started", "port": LUANTI_SERVER_PORT}


@app.post("/api/server/stop")
async def stop_server():
    """Stop the Luanti multiplayer server."""
    global server_process

    if server_process and server_process.poll() is None:
        server_process.terminate()
        try:
            server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_process.kill()
        server_process = None

    return {"status": "stopped"}


@app.get("/api/server/status")
async def server_status():
    """Get server status."""
    running = server_process is not None and server_process.poll() is None
    return {
        "running": running,
        "port": LUANTI_SERVER_PORT if running else None,
        "active_sessions": len(sessions),
    }


@app.websocket("/ws/vnc/{session_id}")
async def vnc_proxy(websocket: WebSocket, session_id: str):
    """WebSocket proxy to forward VNC traffic for a session."""
    proxy_log = logging.getLogger("vnc_proxy")

    if session_id not in sessions:
        proxy_log.warning(f"Session {session_id} not found")
        await websocket.close(code=4004)
        return

    session = sessions[session_id]
    vnc_port = session["vnc_port"]

    await websocket.accept()
    proxy_log.info(f"WebSocket accepted for session {session_id}, VNC port {vnc_port}")

    # Retry VNC connection a few times (x11vnc may still be starting)
    reader = None
    writer = None
    for attempt in range(5):
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", vnc_port)
            proxy_log.info(f"Connected to VNC server on port {vnc_port} (attempt {attempt + 1})")
            break
        except Exception as e:
            proxy_log.warning(f"VNC connection attempt {attempt + 1} failed: {e}")
            if attempt < 4:
                await asyncio.sleep(1)

    if reader is None or writer is None:
        proxy_log.error(f"Failed to connect to VNC on port {vnc_port} after 5 attempts")
        await websocket.close(code=4500)
        return

    async def vnc_to_ws():
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    proxy_log.info("VNC server closed connection")
                    break
                await websocket.send_bytes(data)
        except (WebSocketDisconnect, ConnectionError):
            proxy_log.info("vnc_to_ws: client disconnected")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            proxy_log.error(f"vnc_to_ws error: {type(e).__name__}: {e}")

    async def ws_to_vnc():
        try:
            while True:
                msg = await websocket.receive()
                if msg.get("type") == "websocket.disconnect":
                    proxy_log.info("ws_to_vnc: client sent disconnect")
                    break
                data = msg.get("bytes") or msg.get("text", "").encode()
                if data:
                    writer.write(data)
                    await writer.drain()
        except (WebSocketDisconnect, ConnectionError):
            proxy_log.info("ws_to_vnc: client disconnected")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            proxy_log.error(f"ws_to_vnc error: {type(e).__name__}: {e}")

    task1 = asyncio.create_task(vnc_to_ws())
    task2 = asyncio.create_task(ws_to_vnc())

    try:
        done, pending = await asyncio.wait(
            [task1, task2], return_when=asyncio.FIRST_COMPLETED
        )
        for t in done:
            exc = t.exception()
            if exc:
                proxy_log.error(f"Task exception: {exc}")
        for t in pending:
            t.cancel()
    finally:
        writer.close()
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/api/health")
async def health():
    return {"status": "ok", "sessions": len(sessions)}


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown."""
    global server_process
    for sid in list(sessions.keys()):
        kill_session(sid)
    if server_process and server_process.poll() is None:
        server_process.terminate()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
