from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class EventType(str, Enum):
    NODE_PLACE = "node_place"
    NODE_DIG = "node_dig"
    NODE_PUNCH = "node_punch"
    PLAYER_JOIN = "player_join"
    PLAYER_LEAVE = "player_leave"
    PLAYER_DEATH = "player_death"
    PLAYER_RESPAWN = "player_respawn"
    PLAYER_NEW = "player_new"
    PLAYER_HP_CHANGE = "player_hp_change"
    CHAT_MESSAGE = "chat_message"
    MAPGEN = "mapgen"


class Position(BaseModel):
    x: float
    y: float
    z: float


class NodeData(BaseModel):
    name: str
    param1: int = 0
    param2: int = 0


class WorldEvent(BaseModel):
    type: EventType
    timestamp: int
    game_time: int = 0
    data: dict


class EventBatch(BaseModel):
    world_id: str
    batch_id: str
    events: list[WorldEvent]
    event_count: int
    is_shutdown: bool = False


class EventBatchResponse(BaseModel):
    batch_id: str
    accepted: int
    queued_for_chain: bool
    message: str


class ChainCommitRecord(BaseModel):
    batch_id: str
    tx_hash: str
    block_number: int
    events_merkle_root: str
    event_count: int
    committed_at: datetime


class WorldStatus(BaseModel):
    total_events_received: int = 0
    total_events_committed: int = 0
    pending_events: int = 0
    last_commit_tx: str = ""
    last_commit_time: str = ""
    chain_connected: bool = False
    chain_id: int = 0
    contract_address: str = ""


class EventQuery(BaseModel):
    event_type: EventType | None = None
    player: str | None = None
    since_timestamp: int | None = None
    limit: int = Field(default=100, le=1000)
    offset: int = 0
