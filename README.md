# core-utils: Cross-Chain Bridge Event Listener

This project is a simulation of a core component for a decentralized cross-chain bridge. It acts as an off-chain oracle or relayer that listens for specific events on a source blockchain (e.g., Ethereum) and simulates the corresponding action on a destination blockchain (e.g., Polygon).

This script is designed with a focus on architectural clarity, robustness, and modularity, showcasing how such a system would be structured in a production environment.

## Concept

A cross-chain bridge allows users to transfer assets or data from one blockchain to another. A common mechanism involves a 'lock-and-mint' or 'burn-and-release' pattern:

1.  A user **locks** tokens in a smart contract on the **source chain**.
2.  This action emits an event (e.g., `TokensLocked`).
3.  An off-chain listener (this script) detects and verifies this event.
4.  After ensuring the event is final (i.e., has enough block confirmations to be safe from re-orgs), the listener triggers an action on the **destination chain**.
5.  This action is typically a signed transaction that instructs a contract on the destination chain to **mint** an equivalent amount of a pegged token for the user.

This event listener is the critical link between the two chains, ensuring that events on the source chain are securely and reliably relayed to the destination chain.

## Code Architecture

The script is designed with a clear separation of concerns, broken down into several key classes:

-   `ChainConnector`
    -   **Responsibility**: Manages the Web3 connection to a single blockchain node.
    -   **Features**: Handles connection initialization, provides a clean interface for fetching block numbers, and creates contract instances. It's instantiated for both the source and destination chains.

-   `TransactionStateManager`
    -   **Responsibility**: Tracks the state of each cross-chain transaction.
    -   **Features**: Manages the lifecycle of a transaction through various statuses: `PENDING_CONFIRMATION` -> `CONFIRMED` -> `PROCESSED` / `FAILED`. In this simulation, it's an in-memory dictionary, but it's designed to be easily replaced by a persistent database like Redis or PostgreSQL for production use.

-   `BridgeEventProcessor`
    -   **Responsibility**: Contains the core business logic for handling bridge events.
    -   **Features**: It checks for block confirmations and, once an event is deemed final, it simulates the process of creating and sending a transaction to the destination chain. It also includes a call to a mock external API for notifications.

-   `CrossChainEventListener`
    -   **Responsibility**: The main orchestrator that ties all the components together.
    -   **Features**: It runs the main asynchronous loop, polling for new events, delegating confirmation checks and processing tasks to the `BridgeEventProcessor`, and handling top-level errors like connection loss and recovery.

### Data Flow Diagram

```
[Source Chain] --( emits TokensLocked event )--> [CrossChainEventListener]
        ^
        | (polls for new events)
        v
[ChainConnector] <--( interacts with node )--> [CrossChainEventListener]
        |
        v (new event detected)
[TransactionStateManager] --( stores as PENDING )--> [CrossChainEventListener]
        |
        v (checks confirmations)
[BridgeEventProcessor] --( marks as CONFIRMED )--> [TransactionStateManager]
        |
        v (processes confirmed event)
[BridgeEventProcessor] --( simulates tx )--> [Destination Chain]
        |                                       (via ChainConnector)
        v (notifies external service)
[requests] --> [External API]
        |
        v (marks as PROCESSED)
[BridgeEventProcessor] --> [TransactionStateManager]
```

## How it Works

1.  **Initialization**: The `CrossChainEventListener` is instantiated. It creates `ChainConnector` instances for both the source and destination chains and initializes the `TransactionStateManager` and `BridgeEventProcessor`.
2.  **Event Filter**: It creates an event filter on the source chain's bridge contract to listen for `TokensLocked` events from the latest block onwards.
3.  **Polling Loop**: The `run()` method starts an infinite `asyncio` loop.
4.  **Fetch New Events**: In each iteration, it calls `event_filter.get_new_entries()` to fetch any new events that have occurred since the last poll. New events are added to the `TransactionStateManager` with the status `PENDING_CONFIRMATION`.
5.  **Check Confirmations**: The `BridgeEventProcessor` checks all transactions in the `PENDING_CONFIRMATION` state. It compares the block number where the event was detected against the current latest block number. If the difference (`latest_block - event_block`) is greater than or equal to `BLOCK_CONFIRMATIONS_REQUIRED`, it updates the transaction's status to `CONFIRMED`.
6.  **Process Confirmed Events**: The listener gets all transactions with the `CONFIRMED` status and passes them to the `BridgeEventProcessor`. The processor then simulates the cross-chain action (logging steps for preparing, signing, and sending a transaction to the destination chain) and notifies an external API.
7.  **Finalize State**: After successful processing, the transaction's status is updated to `PROCESSED`.
8.  **Error Handling**: The main loop includes robust error handling. If a connection to a node is lost, it enters a reconnection routine with a delay. Other unexpected errors are logged, and the loop continues after a brief pause.

## Usage Example

### 1. Prerequisites

-   Python 3.8+
-   Access to RPC endpoints for two EVM-compatible chains (e.g., Sepolia and Polygon Mumbai testnets from providers like Infura, Alchemy, or Ankr).

### 2. Setup

Clone the repository and install the required dependencies.

```bash
# Clone the repository (example)
# git clone https://github.com/your-username/core-utils.git
# cd core-utils

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration

Create a `.env` file in the root of the project directory and add your RPC URLs. This file is used to securely manage sensitive information.

**.env file:**
```
SOURCE_CHAIN_RPC_URL="https://your-sepolia-rpc-url.com/your-api-key"
DEST_CHAIN_RPC_URL="https://your-polygon-mumbai-rpc-url.com/your-api-key"
```

**Note**: The script uses mock contract addresses (`0x123...`). For a real test, you would need to deploy corresponding smart contracts and update these addresses in the script.

### 4. Running the Script

Execute the Python script from your terminal.

```bash
python script.py
```

### 5. Sample Output

The listener will start and begin logging its activities. Since no real events will be emitted by the mock contract, it will continuously poll for new blocks and check its (empty) state. If you were to interact with a real contract, the output would look something like this:

```
2023-10-27 10:30:00 - INFO - [__main__] - Successfully connected to SourceChain. Chain ID: 11155111
2023-10-27 10:30:01 - INFO - [__main__] - Successfully connected to DestinationChain. Chain ID: 80001
2023-10-27 10:30:01 - INFO - [__main__] - Transaction State Manager initialized.
2023-10-27 10:30:01 - INFO - [__main__] - Bridge Event Processor initialized.
2023-10-27 10:30:02 - INFO - [__main__] - Event listener initialized. Starting scan from block 4500100.
2023-10-27 10:30:02 - INFO - [__main__] - Starting cross-chain event listener service...
...
2023-10-27 10:30:48 - INFO - [__main__] - Found 1 new event(s).
2023-10-27 10:30:48 - INFO - [__main__] - New transaction 0xabc...def added. Status: PENDING_CONFIRMATION.
...
2023-10-27 10:32:05 - INFO - [__main__] - Transaction 0xabc...def has reached 5 confirmations. Marking as CONFIRMED.
2023-10-27 10:32:05 - INFO - [__main__] - Transaction 0xabc...def status updated to: CONFIRMED
2023-10-27 10:32:20 - INFO - [__main__] - Processing confirmed transaction 0xabc...def for sender 0xSenderAddress...
2023-10-27 10:32:20 - INFO - [__main__] - [SIMULATION] Checking if 0xabc...def has already been processed on DestinationChain.
2023-10-27 10:32:21 - INFO - [__main__] - [SIMULATION] Preparing transaction to release 100000000 of token 0xTokenAddress on DestinationChain.
2023-10-27 10:32:22 - INFO - [__main__] - [SIMULATION] Submitting transaction to DestinationChain...
2023-10-27 10:32:23 - INFO - [__main__] - Successfully notified external API about 0xabc...def.
2023-10-27 10:32:23 - INFO - [__main__] - Transaction 0xabc...def status updated to: PROCESSED
```
