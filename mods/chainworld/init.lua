-- ChainWorld: On-Chain World Sync Mod
-- Records all world events and syncs them to a blockchain via middleware.

local MOD_NAME = core.get_current_modname()
local MOD_PATH = core.get_modpath(MOD_NAME)

-- Load settings
local config = {
    middleware_url = core.settings:get("chainworld_middleware_url") or "http://localhost:8000",
    sync_interval = tonumber(core.settings:get("chainworld_sync_interval")) or 5.0,
    batch_size = tonumber(core.settings:get("chainworld_batch_size")) or 100,
    debug = core.settings:get_bool("chainworld_debug", false),
    record_mapgen = core.settings:get_bool("chainworld_record_mapgen", false),
}

-- Request HTTP API (must be done at load time)
local http_api = core.request_http_api()

if not http_api then
    core.log("error", "[ChainWorld] HTTP API access denied. Add 'chainworld' to secure.http_mods in minetest.conf")
    return
end

core.log("action", "[ChainWorld] Initialized with middleware URL: " .. config.middleware_url)

-- Event queue
local event_queue = {}
local queue_lock = false

-- Utility: debug log
local function debug_log(msg)
    if config.debug then
        core.log("action", "[ChainWorld] " .. msg)
    end
end

-- Utility: serialize position
local function serialize_pos(pos)
    return {x = pos.x, y = pos.y, z = pos.z}
end

-- Utility: get current game time
local function get_timestamp()
    return os.time()
end

-- Utility: get player info safely
local function get_player_name(player_or_obj)
    if player_or_obj and player_or_obj.get_player_name then
        return player_or_obj:get_player_name()
    end
    return "<unknown>"
end

-- Add event to queue
local function queue_event(event_type, data)
    local event = {
        type = event_type,
        timestamp = get_timestamp(),
        game_time = core.get_gametime(),
        data = data,
    }
    table.insert(event_queue, event)
    debug_log("Queued event: " .. event_type .. " (queue size: " .. #event_queue .. ")")
end

-- Flush events to middleware
local function flush_events()
    if #event_queue == 0 or queue_lock then
        return
    end

    queue_lock = true

    -- Take a batch from the queue
    local batch = {}
    local count = math.min(#event_queue, config.batch_size)
    for i = 1, count do
        table.insert(batch, event_queue[i])
    end

    local payload = core.write_json({
        world_id = core.get_worldpath(),
        batch_id = tostring(get_timestamp()) .. "-" .. tostring(math.random(10000)),
        events = batch,
        event_count = count,
    })

    if not payload then
        core.log("error", "[ChainWorld] Failed to serialize event batch")
        queue_lock = false
        return
    end

    debug_log("Flushing " .. count .. " events to middleware")

    http_api.fetch({
        url = config.middleware_url .. "/api/v1/events",
        method = "POST",
        data = payload,
        extra_headers = {
            "Content-Type: application/json",
        },
        timeout = 10,
    }, function(result)
        if result.succeeded and result.code == 200 then
            -- Remove sent events from queue
            for i = 1, count do
                table.remove(event_queue, 1)
            end
            debug_log("Successfully flushed " .. count .. " events (remaining: " .. #event_queue .. ")")
        else
            local code = result.code or "N/A"
            core.log("warning", "[ChainWorld] Failed to flush events (HTTP " .. tostring(code) .. ")")
        end
        queue_lock = false
    end)
end

-- Register periodic flush timer
local flush_timer = 0
core.register_globalstep(function(dtime)
    flush_timer = flush_timer + dtime
    if flush_timer >= config.sync_interval then
        flush_timer = 0
        flush_events()
    end
end)

---------------------------------------------------------------------------
-- Event Capture: Node Placement
---------------------------------------------------------------------------
core.register_on_placenode(function(pos, newnode, placer, oldnode, itemstack, pointed_thing)
    queue_event("node_place", {
        pos = serialize_pos(pos),
        new_node = {name = newnode.name, param1 = newnode.param1, param2 = newnode.param2},
        old_node = oldnode and {name = oldnode.name, param1 = oldnode.param1, param2 = oldnode.param2} or nil,
        player = get_player_name(placer),
    })
end)

---------------------------------------------------------------------------
-- Event Capture: Node Dig
---------------------------------------------------------------------------
core.register_on_dignode(function(pos, oldnode, digger)
    queue_event("node_dig", {
        pos = serialize_pos(pos),
        old_node = {name = oldnode.name, param1 = oldnode.param1, param2 = oldnode.param2},
        player = get_player_name(digger),
    })
end)

---------------------------------------------------------------------------
-- Event Capture: Node Punch
---------------------------------------------------------------------------
core.register_on_punchnode(function(pos, node, puncher, pointed_thing)
    queue_event("node_punch", {
        pos = serialize_pos(pos),
        node = {name = node.name, param1 = node.param1, param2 = node.param2},
        player = get_player_name(puncher),
    })
end)

---------------------------------------------------------------------------
-- Event Capture: Player Join
---------------------------------------------------------------------------
core.register_on_joinplayer(function(player, last_login)
    local pos = player:get_pos()
    queue_event("player_join", {
        player = player:get_player_name(),
        pos = pos and serialize_pos(pos) or nil,
        last_login = last_login,
    })
end)

---------------------------------------------------------------------------
-- Event Capture: Player Leave
---------------------------------------------------------------------------
core.register_on_leaveplayer(function(player, timed_out)
    local pos = player:get_pos()
    queue_event("player_leave", {
        player = player:get_player_name(),
        pos = pos and serialize_pos(pos) or nil,
        timed_out = timed_out,
    })
end)

---------------------------------------------------------------------------
-- Event Capture: Player Death
---------------------------------------------------------------------------
core.register_on_dieplayer(function(player, reason)
    local pos = player:get_pos()
    queue_event("player_death", {
        player = player:get_player_name(),
        pos = pos and serialize_pos(pos) or nil,
        reason = reason and reason.type or "unknown",
    })
end)

---------------------------------------------------------------------------
-- Event Capture: Player Respawn
---------------------------------------------------------------------------
core.register_on_respawnplayer(function(player)
    queue_event("player_respawn", {
        player = player:get_player_name(),
    })
end)

---------------------------------------------------------------------------
-- Event Capture: New Player
---------------------------------------------------------------------------
core.register_on_newplayer(function(player)
    queue_event("player_new", {
        player = player:get_player_name(),
    })
end)

---------------------------------------------------------------------------
-- Event Capture: Chat Messages
---------------------------------------------------------------------------
core.register_on_chat_message(function(name, message)
    queue_event("chat_message", {
        player = name,
        message = message,
    })
end)

---------------------------------------------------------------------------
-- Event Capture: Player HP Change
---------------------------------------------------------------------------
core.register_on_player_hpchange(function(player, hp_change, reason)
    if hp_change ~= 0 then
        queue_event("player_hp_change", {
            player = player:get_player_name(),
            hp_change = hp_change,
            reason = reason and reason.type or "unknown",
        })
    end
end)

---------------------------------------------------------------------------
-- Event Capture: Mapgen (optional, can generate large data)
---------------------------------------------------------------------------
if config.record_mapgen then
    core.register_on_generated(function(minp, maxp, blockseed)
        queue_event("mapgen", {
            minp = serialize_pos(minp),
            maxp = serialize_pos(maxp),
            blockseed = blockseed,
        })
    end)
end

---------------------------------------------------------------------------
-- Event Capture: Server Shutdown
---------------------------------------------------------------------------
core.register_on_shutdown(function()
    core.log("action", "[ChainWorld] Server shutting down, flushing remaining " .. #event_queue .. " events...")
    -- Force sync remaining events
    if #event_queue > 0 then
        local payload = core.write_json({
            world_id = core.get_worldpath(),
            batch_id = "shutdown-" .. tostring(get_timestamp()),
            events = event_queue,
            event_count = #event_queue,
            is_shutdown = true,
        })

        if payload then
            -- Use synchronous-style approach for shutdown
            http_api.fetch({
                url = config.middleware_url .. "/api/v1/events",
                method = "POST",
                data = payload,
                extra_headers = {
                    "Content-Type: application/json",
                },
                timeout = 15,
            }, function(result)
                if result.succeeded then
                    core.log("action", "[ChainWorld] Shutdown flush succeeded")
                else
                    core.log("error", "[ChainWorld] Shutdown flush failed")
                end
            end)
        end
    end
end)

---------------------------------------------------------------------------
-- Chat Commands
---------------------------------------------------------------------------
core.register_chatcommand("chainworld_status", {
    description = "Show ChainWorld sync status",
    privs = {server = true},
    func = function(name, param)
        local status = string.format(
            "ChainWorld Status:\n" ..
            "  Middleware URL: %s\n" ..
            "  Queue size: %d\n" ..
            "  Sync interval: %.1fs\n" ..
            "  Batch size: %d\n" ..
            "  Mapgen recording: %s",
            config.middleware_url,
            #event_queue,
            config.sync_interval,
            config.batch_size,
            config.record_mapgen and "ON" or "OFF"
        )
        return true, status
    end,
})

core.register_chatcommand("chainworld_flush", {
    description = "Force flush ChainWorld event queue",
    privs = {server = true},
    func = function(name, param)
        if #event_queue == 0 then
            return true, "Event queue is empty."
        end
        flush_events()
        return true, "Flush initiated for " .. #event_queue .. " events."
    end,
})

core.log("action", "[ChainWorld] Mod loaded successfully. Event capture active.")
