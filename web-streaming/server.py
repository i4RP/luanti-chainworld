#!/usr/bin/env python3
"""
ChainWorld Web Streaming Server

Manages Luanti game sessions with noVNC streaming for browser-based play.
Supports both single-player and multiplayer modes.
"""

import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
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


def start_luanti_singleplayer(display_num: int, player_name: str, width: int = 1280, height: int = 720) -> subprocess.Popen:
    """Start Luanti in singleplayer mode on a virtual display."""
    env = os.environ.copy()
    env["DISPLAY"] = f":{display_num}"
    env["HOME"] = os.environ.get("HOME", "/home/ubuntu")

    cmd = [
        LUANTI_BIN,
        "--worldname", "chainworld_test",
        "--name", player_name,
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
            luanti_proc = start_luanti_singleplayer(display_num, req.player_name)

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
