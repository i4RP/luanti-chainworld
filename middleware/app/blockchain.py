import hashlib
import json
import logging

from web3 import Web3

from app.config import settings

logger = logging.getLogger(__name__)

# ChainWorld contract ABI (minimal interface for event recording)
CONTRACT_ABI = [
    {
        "inputs": [
            {"name": "batchId", "type": "string"},
            {"name": "merkleRoot", "type": "bytes32"},
            {"name": "eventCount", "type": "uint256"},
            {"name": "timestamp", "type": "uint256"},
        ],
        "name": "commitEventBatch",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "batchId", "type": "string"}],
        "name": "getBatchCommit",
        "outputs": [
            {"name": "merkleRoot", "type": "bytes32"},
            {"name": "eventCount", "type": "uint256"},
            {"name": "timestamp", "type": "uint256"},
            {"name": "committer", "type": "address"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalBatches",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalEvents",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "batchId", "type": "string"},
            {"indexed": False, "name": "merkleRoot", "type": "bytes32"},
            {"indexed": False, "name": "eventCount", "type": "uint256"},
            {"indexed": False, "name": "timestamp", "type": "uint256"},
        ],
        "name": "BatchCommitted",
        "type": "event",
    },
]


def compute_events_merkle_root(events: list[dict]) -> str:
    """Compute a simple Merkle root from a list of events."""
    if not events:
        return "0x" + "0" * 64

    # Hash each event
    leaves = []
    for event in events:
        event_str = json.dumps(event, sort_keys=True)
        leaf = hashlib.sha256(event_str.encode()).hexdigest()
        leaves.append(leaf)

    # Build Merkle tree
    while len(leaves) > 1:
        if len(leaves) % 2 == 1:
            leaves.append(leaves[-1])  # Duplicate last if odd
        new_leaves = []
        for i in range(0, len(leaves), 2):
            combined = leaves[i] + leaves[i + 1]
            parent = hashlib.sha256(combined.encode()).hexdigest()
            new_leaves.append(parent)
        leaves = new_leaves

    return "0x" + leaves[0]


class BlockchainClient:
    """Client for interacting with the ChainWorld smart contract."""

    def __init__(self) -> None:
        self.w3: Web3 | None = None
        self.contract = None
        self.account = None
        self._connected = False

    def connect(self) -> bool:
        """Attempt to connect to the blockchain."""
        try:
            if not settings.chain_rpc_url or not settings.contract_address:
                logger.info("Blockchain not configured, running in offline mode")
                return False

            self.w3 = Web3(Web3.HTTPProvider(settings.chain_rpc_url))

            if not self.w3.is_connected():
                logger.warning("Failed to connect to blockchain at %s", settings.chain_rpc_url)
                return False

            if settings.contract_address:
                self.contract = self.w3.eth.contract(
                    address=Web3.to_checksum_address(settings.contract_address),
                    abi=CONTRACT_ABI,
                )

            if settings.private_key:
                self.account = self.w3.eth.account.from_key(settings.private_key)

            self._connected = True
            logger.info("Connected to blockchain (chain_id=%d)", settings.chain_id)
            return True

        except Exception as e:
            logger.error("Blockchain connection error: %s", e)
            self._connected = False
            return False

    @property
    def is_connected(self) -> bool:
        if self._connected and self.w3:
            try:
                return self.w3.is_connected()
            except Exception:
                self._connected = False
        return False

    def commit_event_batch(
        self, batch_id: str, merkle_root: str, event_count: int
    ) -> dict | None:
        """Commit an event batch to the smart contract."""
        if not self.is_connected or not self.contract or not self.account:
            logger.warning("Cannot commit: not connected or not configured")
            return None

        try:
            import time

            merkle_root_bytes = bytes.fromhex(merkle_root.replace("0x", ""))

            tx = self.contract.functions.commitEventBatch(
                batch_id,
                merkle_root_bytes,
                event_count,
                int(time.time()),
            ).build_transaction(
                {
                    "from": self.account.address,
                    "nonce": self.w3.eth.get_transaction_count(self.account.address),
                    "chainId": settings.chain_id,
                }
            )

            signed_tx = self.w3.eth.account.sign_transaction(tx, settings.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)

            result = {
                "tx_hash": receipt.transactionHash.hex(),
                "block_number": receipt.blockNumber,
                "status": receipt.status,
            }
            logger.info("Batch %s committed: tx=%s", batch_id, result["tx_hash"])
            return result

        except Exception as e:
            logger.error("Failed to commit batch %s: %s", batch_id, e)
            return None

    def get_chain_info(self) -> dict:
        """Get basic chain information."""
        if not self.is_connected or not self.w3:
            return {"connected": False}

        try:
            return {
                "connected": True,
                "chain_id": self.w3.eth.chain_id,
                "block_number": self.w3.eth.block_number,
                "contract_address": settings.contract_address,
            }
        except Exception:
            return {"connected": False}


# Global blockchain client instance
blockchain_client = BlockchainClient()
