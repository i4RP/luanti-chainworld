// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title ChainWorld - On-Chain World Event Storage
/// @notice Stores Merkle roots of Luanti world event batches for verification and reconstruction.
contract ChainWorld {
    struct BatchCommit {
        bytes32 merkleRoot;
        uint256 eventCount;
        uint256 timestamp;
        address committer;
    }

    /// @notice Owner of the contract (deployer)
    address public owner;

    /// @notice Mapping from batch ID hash to commit data
    mapping(bytes32 => BatchCommit) public batchCommits;

    /// @notice Ordered list of batch ID hashes for enumeration
    bytes32[] public batchIds;

    /// @notice Total number of committed batches
    uint256 public totalBatches;

    /// @notice Total number of events across all batches
    uint256 public totalEvents;

    /// @notice Mapping of authorized committers
    mapping(address => bool) public authorizedCommitters;

    /// @notice Emitted when a new event batch is committed
    event BatchCommitted(
        string indexed batchId,
        bytes32 merkleRoot,
        uint256 eventCount,
        uint256 timestamp
    );

    /// @notice Emitted when a committer is authorized or deauthorized
    event CommitterUpdated(address indexed committer, bool authorized);

    modifier onlyOwner() {
        require(msg.sender == owner, "ChainWorld: caller is not the owner");
        _;
    }

    modifier onlyAuthorized() {
        require(
            msg.sender == owner || authorizedCommitters[msg.sender],
            "ChainWorld: caller is not authorized"
        );
        _;
    }

    constructor() {
        owner = msg.sender;
        authorizedCommitters[msg.sender] = true;
    }

    /// @notice Commit a batch of world events
    /// @param batchId Unique identifier for the batch
    /// @param merkleRoot Merkle root of the event data
    /// @param eventCount Number of events in the batch
    /// @param timestamp Unix timestamp of the batch
    function commitEventBatch(
        string calldata batchId,
        bytes32 merkleRoot,
        uint256 eventCount,
        uint256 timestamp
    ) external onlyAuthorized {
        bytes32 batchIdHash = keccak256(abi.encodePacked(batchId));

        require(
            batchCommits[batchIdHash].timestamp == 0,
            "ChainWorld: batch already committed"
        );
        require(eventCount > 0, "ChainWorld: empty batch");

        batchCommits[batchIdHash] = BatchCommit({
            merkleRoot: merkleRoot,
            eventCount: eventCount,
            timestamp: timestamp,
            committer: msg.sender
        });

        batchIds.push(batchIdHash);
        totalBatches += 1;
        totalEvents += eventCount;

        emit BatchCommitted(batchId, merkleRoot, eventCount, timestamp);
    }

    /// @notice Get commit data for a batch
    /// @param batchId The batch identifier string
    /// @return merkleRoot The Merkle root of the batch
    /// @return eventCount Number of events in the batch
    /// @return timestamp Timestamp of the commit
    /// @return committer Address that committed the batch
    function getBatchCommit(string calldata batchId)
        external
        view
        returns (
            bytes32 merkleRoot,
            uint256 eventCount,
            uint256 timestamp,
            address committer
        )
    {
        bytes32 batchIdHash = keccak256(abi.encodePacked(batchId));
        BatchCommit storage commit = batchCommits[batchIdHash];
        return (commit.merkleRoot, commit.eventCount, commit.timestamp, commit.committer);
    }

    /// @notice Verify that a batch exists with the given Merkle root
    /// @param batchId The batch identifier string
    /// @param merkleRoot The expected Merkle root
    /// @return valid True if the batch exists and the Merkle root matches
    function verifyBatch(string calldata batchId, bytes32 merkleRoot)
        external
        view
        returns (bool valid)
    {
        bytes32 batchIdHash = keccak256(abi.encodePacked(batchId));
        BatchCommit storage commit = batchCommits[batchIdHash];
        return commit.merkleRoot == merkleRoot && commit.timestamp > 0;
    }

    /// @notice Get the batch ID hash at a given index
    /// @param index Index in the batchIds array
    /// @return The batch ID hash
    function getBatchIdAtIndex(uint256 index) external view returns (bytes32) {
        require(index < batchIds.length, "ChainWorld: index out of bounds");
        return batchIds[index];
    }

    /// @notice Authorize or deauthorize a committer address
    /// @param committer The address to update
    /// @param authorized Whether to authorize or deauthorize
    function setCommitter(address committer, bool authorized) external onlyOwner {
        authorizedCommitters[committer] = authorized;
        emit CommitterUpdated(committer, authorized);
    }

    /// @notice Transfer ownership of the contract
    /// @param newOwner The new owner address
    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "ChainWorld: zero address");
        owner = newOwner;
    }
}
