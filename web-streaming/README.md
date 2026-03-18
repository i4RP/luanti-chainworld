# ChainWorld Web Streaming

Browser-based play for ChainWorld using noVNC streaming. Play Luanti from your smartphone browser with touch controls.

## Architecture

```
Browser (smartphone/PC)
    |
    | WebSocket (noVNC)
    |
websockify (WS -> VNC bridge)
    |
x11vnc (VNC server)
    |
Xvfb (virtual display)
    |
Luanti (game client)
```

## Features

- **Browser Play**: Play Luanti directly from any browser (mobile or desktop)
- **Touch Controls**: Virtual joystick, action buttons (dig/place/jump), hotbar, camera control
- **Multiplayer**: Run a Luanti server and connect multiple browser players
- **Session Management**: FastAPI backend manages game sessions (Xvfb + Luanti + x11vnc + websockify per player)

## Requirements

- Python 3.10+
- x11vnc
- Xvfb
- Luanti (built from source in parent directory)

### Install system dependencies

```bash
sudo apt-get install -y x11vnc xvfb
pip install -r requirements.txt
```

## Quick Start

```bash
# From the web-streaming directory
./start.sh
```

Or manually:

```bash
export LUANTI_BIN=../bin/luanti
export LUANTI_ROOT=..
python3 -m uvicorn server:app --host 0.0.0.0 --port 8080
```

Then open `http://<server-ip>:8080` in your browser.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Landing page |
| `/play` | GET | Game player page (noVNC + touch controls) |
| `/api/sessions` | POST | Create a new game session |
| `/api/sessions` | GET | List active sessions |
| `/api/sessions/{id}` | DELETE | Stop a session |
| `/api/server/start` | POST | Start multiplayer server |
| `/api/server/stop` | POST | Stop multiplayer server |
| `/api/server/status` | GET | Get server status |
| `/api/health` | GET | Health check |

## Touch Controls

- **Left joystick**: Movement (W/A/S/D)
- **Center area**: Camera look (mouse movement)
- **DIG button**: Left click (hold to dig)
- **PLACE button**: Right click (place block)
- **JUMP button**: Space key
- **SNEAK button**: Shift key
- **Hotbar 1-8**: Select inventory slot
- **I**: Open inventory
- **T**: Open chat
- **FLY**: Toggle fly mode
- **ESC**: Escape/menu
- **X**: Leave game

## Multiplayer

1. Click "Multiplayer" mode on the landing page
2. Click "Start Server" to launch the Luanti server
3. Click "Start Game" - each player gets their own streaming session
4. Multiple players can join from different browsers
