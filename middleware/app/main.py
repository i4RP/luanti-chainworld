import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.blockchain import blockchain_client, compute_events_merkle_root
from app.config import settings
from app.database import EventDatabase
from app.models import (
    EventBatch,
    EventBatchResponse,
    EventType,
    WorldStatus,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database instance
db = EventDatabase()


def chain_commit_worker() -> None:
    """Background worker that periodically commits pending events to blockchain."""
    while True:
        try:
            time.sleep(settings.batch_commit_interval)

            if not blockchain_client.is_connected:
                continue

            pending = db.get_pending_events(limit=settings.max_batch_size)
            if not pending:
                continue

            event_ids = [e["id"] for e in pending]
            merkle_root = compute_events_merkle_root(pending)
            batch_id = f"auto-{int(time.time())}-{len(pending)}"

            result = blockchain_client.commit_event_batch(
                batch_id=batch_id,
                merkle_root=merkle_root,
                event_count=len(pending),
            )

            if result and result.get("status") == 1:
                db.mark_events_committed(event_ids)
                db.record_chain_commit(
                    batch_id=batch_id,
                    tx_hash=result["tx_hash"],
                    block_number=result["block_number"],
                    merkle_root=merkle_root,
                    event_count=len(pending),
                    event_ids=event_ids,
                )
                logger.info(
                    "Auto-committed %d events (batch=%s, tx=%s)",
                    len(pending),
                    batch_id,
                    result["tx_hash"],
                )
            else:
                logger.warning("Auto-commit failed for batch %s", batch_id)

        except Exception as e:
            logger.error("Chain commit worker error: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    # Startup
    logger.info("ChainWorld Middleware starting up...")
    connected = blockchain_client.connect()
    if connected:
        logger.info("Blockchain connected, starting commit worker")
        worker = threading.Thread(target=chain_commit_worker, daemon=True)
        worker.start()
    else:
        logger.info("Running in offline mode (no blockchain connection)")

    yield

    # Shutdown
    logger.info("ChainWorld Middleware shutting down...")


app = FastAPI(
    title="ChainWorld Middleware",
    description="Bridges Luanti world events to blockchain for on-chain world management.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "name": "ChainWorld Middleware",
        "version": "0.1.0",
        "description": "On-chain world event bridge for Luanti",
    }


@app.post("/api/v1/events", response_model=EventBatchResponse)
async def receive_events(batch: EventBatch):
    """Receive a batch of world events from the Luanti ChainWorld mod."""
    try:
        events_data = [
            {
                "type": event.type.value,
                "timestamp": event.timestamp,
                "game_time": event.game_time,
                "data": event.data,
            }
            for event in batch.events
        ]

        inserted = db.insert_events(batch.batch_id, events_data)

        logger.info(
            "Received batch %s: %d events (shutdown=%s)",
            batch.batch_id,
            inserted,
            batch.is_shutdown,
        )

        return EventBatchResponse(
            batch_id=batch.batch_id,
            accepted=inserted,
            queued_for_chain=blockchain_client.is_connected,
            message=f"Accepted {inserted} events"
            + (
                " (queued for chain commit)"
                if blockchain_client.is_connected
                else " (offline mode)"
            ),
        )

    except Exception as e:
        logger.error("Error processing event batch: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/events")
async def query_events(
    event_type: EventType | None = None,
    player: str | None = None,
    since_timestamp: int | None = None,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """Query recorded world events."""
    events = db.query_events(
        event_type=event_type.value if event_type else None,
        player=player,
        since_timestamp=since_timestamp,
        limit=limit,
        offset=offset,
    )
    return {"events": events, "count": len(events)}


@app.get("/api/v1/world/status", response_model=WorldStatus)
async def world_status():
    """Get the current world sync status."""
    stats = db.get_stats()
    chain_info = blockchain_client.get_chain_info()

    return WorldStatus(
        total_events_received=stats["total_events_received"],
        total_events_committed=stats["total_events_committed"],
        pending_events=stats["pending_events"],
        last_commit_tx=stats["last_commit_tx"],
        last_commit_time=stats["last_commit_time"],
        chain_connected=chain_info.get("connected", False),
        chain_id=chain_info.get("chain_id", 0),
        contract_address=chain_info.get("contract_address", ""),
    )


@app.get("/api/v1/chain/commits")
async def chain_commits(limit: int = Query(default=50, le=200)):
    """Get recent chain commit records."""
    commits = db.get_chain_commits(limit=limit)
    return {"commits": commits, "count": len(commits)}


@app.post("/api/v1/chain/commit")
async def force_commit():
    """Force an immediate commit of pending events to the blockchain."""
    if not blockchain_client.is_connected:
        raise HTTPException(status_code=503, detail="Blockchain not connected")

    pending = db.get_pending_events(limit=settings.max_batch_size)
    if not pending:
        return {"message": "No pending events to commit"}

    event_ids = [e["id"] for e in pending]
    merkle_root = compute_events_merkle_root(pending)
    batch_id = f"manual-{int(time.time())}-{len(pending)}"

    result = blockchain_client.commit_event_batch(
        batch_id=batch_id,
        merkle_root=merkle_root,
        event_count=len(pending),
    )

    if result and result.get("status") == 1:
        db.mark_events_committed(event_ids)
        db.record_chain_commit(
            batch_id=batch_id,
            tx_hash=result["tx_hash"],
            block_number=result["block_number"],
            merkle_root=merkle_root,
            event_count=len(pending),
            event_ids=event_ids,
        )
        return {
            "message": f"Committed {len(pending)} events",
            "batch_id": batch_id,
            "tx_hash": result["tx_hash"],
            "block_number": result["block_number"],
        }
    else:
        raise HTTPException(status_code=500, detail="Chain commit failed")


@app.get("/api/v1/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "blockchain": blockchain_client.is_connected,
        "database": True,
    }
