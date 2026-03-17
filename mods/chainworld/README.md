# ChainWorld - On-Chain World Sync Mod for Luanti

A Luanti server mod that captures all world events (node placement, digging, player actions, etc.) and syncs them to a blockchain via an external middleware service.

## Architecture

```
Luanti Server + ChainWorld Mod
        |
        | HTTP (event batches)
        v
  Python Middleware (FastAPI)
        |
        | Web3 (Merkle roots)
        v
  Smart Contract (EVM)
```

## Setup

### 1. Enable the Mod

Add `chainworld` to `secure.http_mods` in your `minetest.conf`:

```
secure.http_mods = chainworld
```

Enable the mod in your world's `world.mt`:

```
load_mod_chainworld = true
```

### 2. Configure

Add these settings to `minetest.conf` (or use the in-game settings UI):

```
chainworld_middleware_url = http://localhost:8000
chainworld_sync_interval = 5.0
chainworld_batch_size = 100
chainworld_debug = false
chainworld_record_mapgen = false
```

### 3. Start Middleware

See `middleware/README.md` for middleware setup instructions.

## Chat Commands

- `/chainworld_status` - Show sync status (requires `server` privilege)
- `/chainworld_flush` - Force flush the event queue (requires `server` privilege)

## Captured Events

| Event Type | Trigger |
|---|---|
| `node_place` | Player places a node |
| `node_dig` | Player digs a node |
| `node_punch` | Player punches a node |
| `player_join` | Player joins the server |
| `player_leave` | Player leaves the server |
| `player_death` | Player dies |
| `player_respawn` | Player respawns |
| `player_new` | New player first joins |
| `player_hp_change` | Player HP changes |
| `chat_message` | Chat message sent |
| `mapgen` | New terrain generated (optional) |
