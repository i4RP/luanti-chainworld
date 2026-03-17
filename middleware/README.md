# ChainWorld Middleware

FastAPI service that bridges Luanti world events to blockchain. Receives event batches from the ChainWorld Lua mod, stores them locally, and commits Merkle roots to an EVM-compatible smart contract.

## Setup

### Requirements

- Python 3.11+
- Poetry

### Install

```bash
cd middleware
poetry install
```

### Configure

Copy `.env.example` to `.env` and edit:

```bash
cp .env.example .env
```

Key settings:
- `CHAINWORLD_CHAIN_RPC_URL` - Your EVM RPC endpoint
- `CHAINWORLD_CHAIN_ID` - Chain ID (e.g., 1 for Ethereum mainnet, 31337 for local)
- `CHAINWORLD_CONTRACT_ADDRESS` - Deployed ChainWorld contract address
- `CHAINWORLD_PRIVATE_KEY` - Private key for signing transactions

### Run

```bash
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Offline Mode

The middleware works without blockchain connection. Events are stored locally in SQLite and can be committed to chain later when configured.

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/events` | Receive event batch from Lua mod |
| `GET` | `/api/v1/events` | Query stored events |
| `GET` | `/api/v1/world/status` | World sync status |
| `GET` | `/api/v1/chain/commits` | List chain commit records |
| `POST` | `/api/v1/chain/commit` | Force immediate chain commit |
| `GET` | `/api/v1/health` | Health check |

## Smart Contract

The Solidity contract is in `contracts/ChainWorld.sol`. It stores:
- Merkle roots of event batches
- Event counts per batch
- Timestamps and committer addresses

Deploy using your preferred tool (Hardhat, Foundry, Remix, etc.).
