import os
import time
import logging
import asyncio
from typing import Dict, Any, Optional, List

import requests
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import ContractLogicError, TransactionNotFound
from dotenv import load_dotenv

# --- Basic Configuration ---
load_dotenv()

# Configure logging to provide detailed output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- Constants and Mock Data ---
# In a real-world scenario, these would be loaded from a config file or environment
SOURCE_CHAIN_RPC = os.getenv('SOURCE_CHAIN_RPC_URL', 'https://rpc.sepolia.org')
DEST_CHAIN_RPC = os.getenv('DEST_CHAIN_RPC_URL', 'https://rpc.ankr.com/polygon_mumbai')

# Mock contract ABIs for demonstration purposes
# This represents a simple bridge contract with a 'TokensLocked' event
SOURCE_BRIDGE_ABI = '''
[
    {
        "anonymous": false,
        "inputs": [
            {"indexed": true, "internalType": "bytes32", "name": "transactionId", "type": "bytes32"},
            {"indexed": true, "internalType": "address", "name": "sender", "type": "address"},
            {"indexed": true, "internalType": "address", "name": "token", "type": "address"},
            {"indexed": false, "internalType": "uint256", "name": "amount", "type": "uint256"},
            {"indexed": false, "internalType": "uint256", "name": "destinationChainId", "type": "uint256"}
        ],
        "name": "TokensLocked",
        "type": "event"
    }
]
'''

# Mock addresses
SOURCE_BRIDGE_ADDRESS = '0x1234567890123456789012345678901234567890' # Replace with a real address for testing
DEST_BRIDGE_ADDRESS = '0x0987654321098765432109876543210987654321'   # Replace with a real address for testing

# --- System Configuration ---
BLOCK_CONFIRMATIONS_REQUIRED = 5  # Number of blocks to wait for event confirmation
POLLING_INTERVAL_SECONDS = 15.0   # How often to check for new blocks
API_ENDPOINT_FOR_NOTIFICATIONS = 'https://api.example.com/bridge/notify' # Mock API for notifications


class ChainConnector:
    """
    Manages the connection to a single blockchain node via Web3.py.
    Handles connection setup, retries, and provides a stable interface for chain interactions.
    """
    def __init__(self, rpc_url: str, chain_name: str):
        """
        Initializes the connector for a specific chain.
        Args:
            rpc_url (str): The HTTP RPC endpoint for the blockchain node.
            chain_name (str): A human-readable name for the chain (e.g., 'Sepolia', 'Polygon Mumbai').
        """
        self.rpc_url = rpc_url
        self.chain_name = chain_name
        self.web3: Optional[Web3] = None
        self.connect()

    def connect(self) -> None:
        """
        Establishes a connection to the blockchain node.
        Includes basic retry logic for initial connection failure.
        """
        logger.info(f"Attempting to connect to {self.chain_name} at {self.rpc_url}...")
        try:
            self.web3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not self.web3.is_connected():
                raise ConnectionError(f"Failed to connect to {self.chain_name}.")
            logger.info(f"Successfully connected to {self.chain_name}. Chain ID: {self.web3.eth.chain_id}")
        except Exception as e:
            logger.error(f"Connection to {self.chain_name} failed: {e}")
            self.web3 = None
            # In a production system, you might implement more robust retry logic here.
            raise

    def get_latest_block_number(self) -> int:
        """
        Fetches the latest block number from the connected chain.
        Returns: The latest block number.
        Raises: ConnectionError if not connected.
        """
        if not self.web3 or not self.web3.is_connected():
            raise ConnectionError(f"Not connected to {self.chain_name}.")
        return self.web3.eth.block_number

    def get_contract(self, address: str, abi: str) -> Contract:
        """
        Creates a Web3 Contract object for interaction.
        Args:
            address (str): The contract's address.
            abi (str): The contract's ABI.
        Returns: A Web3.py Contract instance.
        Raises: ConnectionError if not connected.
        """
        if not self.web3 or not self.web3.is_connected():
            raise ConnectionError(f"Not connected to {self.chain_name}.")
        return self.web3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)


class TransactionStateManager:
    """
    A simple in-memory state manager for tracking cross-chain transactions.
    In a production system, this would be backed by a persistent database (e.g., Redis, PostgreSQL).
    """
    def __init__(self):
        # State: { 'transactionId': {'status': 'PENDING_CONFIRMATION'|'CONFIRMED'|'PROCESSED'|'FAILED', 'event_data': {...}} }
        self.transactions: Dict[str, Dict[str, Any]] = {}
        logger.info("Transaction State Manager initialized.")

    def add_pending_transaction(self, event_data: Dict[str, Any]) -> bool:
        """
        Adds a new transaction detected from an event to the state.
        Args:
            event_data (Dict[str, Any]): The processed event data.
        Returns:
            bool: True if the transaction was new, False if it was already tracked.
        """
        tx_id = event_data['args']['transactionId'].hex()
        if tx_id not in self.transactions:
            self.transactions[tx_id] = {
                'status': 'PENDING_CONFIRMATION',
                'event_data': event_data,
                'detected_at_block': event_data['blockNumber']
            }
            logger.info(f"New transaction {tx_id} added. Status: PENDING_CONFIRMATION.")
            return True
        return False

    def update_transaction_status(self, tx_id: str, status: str) -> None:
        """
        Updates the status of an existing transaction.
        """
        if tx_id in self.transactions:
            self.transactions[tx_id]['status'] = status
            logger.info(f"Transaction {tx_id} status updated to: {status}")
        else:
            logger.warning(f"Attempted to update status for unknown transaction ID: {tx_id}")

    def get_transactions_by_status(self, status: str) -> List[Dict[str, Any]]:
        """
        Retrieves all transactions with a given status.
        """
        return [tx for tx_id, tx in self.transactions.items() if tx['status'] == status]


class BridgeEventProcessor:
    """
    Handles the core business logic of processing bridge events.
    This includes confirming events and simulating actions on the destination chain.
    """
    def __init__(self, source_chain: ChainConnector, dest_chain: ChainConnector, state_manager: TransactionStateManager):
        self.source_chain = source_chain
        self.dest_chain = dest_chain
        self.state_manager = state_manager
        logger.info("Bridge Event Processor initialized.")

    async def process_confirmed_event(self, tx_id: str):
        """
        Simulates the processing of a confirmed event on the destination chain.
        In a real bridge, this would involve submitting a signed transaction to mint/release tokens.
        Args:
            tx_id (str): The unique transaction identifier from the event.
        """
        tx_data = self.state_manager.transactions.get(tx_id)
        if not tx_data or tx_data['status'] != 'CONFIRMED':
            logger.warning(f"Skipping processing for {tx_id}: not in a 'CONFIRMED' state.")
            return

        event_args = tx_data['event_data']['args']
        logger.info(f"Processing confirmed transaction {tx_id} for sender {event_args['sender']}...")

        # --- SIMULATION --- #
        # 1. Check for double-spending on the destination chain (idempotency check)
        # This could involve calling a 'isTransactionProcessed(tx_id)' view function on the dest contract.
        logger.info(f"[SIMULATION] Checking if {tx_id} has already been processed on {self.dest_chain.chain_name}.")
        await asyncio.sleep(1) # Simulate network latency

        # 2. Prepare and sign the transaction for the destination chain
        logger.info(f"[SIMULATION] Preparing transaction to release {event_args['amount']} of token {event_args['token']} on {self.dest_chain.chain_name}.")
        await asyncio.sleep(1)

        # 3. Send the transaction
        logger.info(f"[SIMULATION] Submitting transaction to {self.dest_chain.chain_name}...")
        # Here you would use self.dest_chain.web3.eth.send_raw_transaction

        # 4. Notify external systems (e.g., via a webhook)
        try:
            response = requests.post(API_ENDPOINT_FOR_NOTIFICATIONS, json={
                'transactionId': tx_id,
                'status': 'PROCESSED',
                'details': f"Released tokens on {self.dest_chain.chain_name}"
            }, timeout=10)
            if response.status_code == 200:
                logger.info(f"Successfully notified external API about {tx_id}.")
            else:
                logger.warning(f"Failed to notify API for {tx_id}. Status: {response.status_code}")
        except requests.RequestException as e:
            logger.error(f"API notification failed for {tx_id}: {e}")

        # Update state to final status
        self.state_manager.update_transaction_status(tx_id, 'PROCESSED')

    def check_confirmations(self):
        """
        Checks transactions pending confirmation to see if they have reached the required block depth.
        """
        pending_txs = self.state_manager.get_transactions_by_status('PENDING_CONFIRMATION')
        if not pending_txs:
            return

        try:
            latest_block = self.source_chain.get_latest_block_number()
        except ConnectionError as e:
            logger.error(f"Could not check confirmations: {e}")
            return

        for tx in pending_txs:
            tx_id = tx['event_data']['args']['transactionId'].hex()
            block_detected = tx['detected_at_block']
            confirmations = latest_block - block_detected

            if confirmations >= BLOCK_CONFIRMATIONS_REQUIRED:
                logger.info(
                    f"Transaction {tx_id} has reached {confirmations} confirmations. Marking as CONFIRMED."
                )
                self.state_manager.update_transaction_status(tx_id, 'CONFIRMED')
            else:
                logger.debug(
                    f"Transaction {tx_id} is waiting for confirmations. Current: {confirmations}/{BLOCK_CONFIRMATIONS_REQUIRED}"
                )


class CrossChainEventListener:
    """
    The main orchestrator for the bridge event listening service.
    It manages the polling loop, fetches events, and delegates processing.
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.source_chain = ChainConnector(config['source_rpc'], 'SourceChain')
        self.dest_chain = ChainConnector(config['dest_rpc'], 'DestinationChain')
        self.state_manager = TransactionStateManager()
        self.processor = BridgeEventProcessor(self.source_chain, self.dest_chain, self.state_manager)

        self.source_contract = self.source_chain.get_contract(
            address=config['source_contract_address'],
            abi=config['source_contract_abi']
        )
        self.event_filter = self.source_contract.events.TokensLocked.create_filter(fromBlock='latest')
        self.last_processed_block = self.source_chain.get_latest_block_number()
        logger.info(f"Event listener initialized. Starting scan from block {self.last_processed_block}.")

    async def poll_for_events(self):
        """
        Polls for new 'TokensLocked' events from the source chain contract.
        """
        try:
            new_entries = self.event_filter.get_new_entries()
            if new_entries:
                logger.info(f"Found {len(new_entries)} new event(s).")
                for event in new_entries:
                    self.state_manager.add_pending_transaction(event)
        except Exception as e:
            logger.error(f"Error polling for events: {e}")
            # Potential reconnection logic could be triggered here

    async def run(self):
        """
        The main execution loop for the listener service.
        """
        logger.info("Starting cross-chain event listener service...")
        while True:
            try:
                # 1. Poll for new events from the source chain
                await self.poll_for_events()

                # 2. Check for required block confirmations for pending events
                self.processor.check_confirmations()

                # 3. Process events that are fully confirmed
                confirmed_txs = self.state_manager.get_transactions_by_status('CONFIRMED')
                for tx in confirmed_txs:
                    tx_id = tx['event_data']['args']['transactionId'].hex()
                    await self.processor.process_confirmed_event(tx_id)

                # Wait for the next polling interval
                logger.debug(f"Loop finished. Waiting for {POLLING_INTERVAL_SECONDS} seconds...")
                await asyncio.sleep(POLLING_INTERVAL_SECONDS)

            except ConnectionError as e:
                logger.critical(f"A chain connection was lost: {e}. Attempting to reconnect...")
                await self._reconnect()
            except KeyboardInterrupt:
                logger.info("Shutdown signal received. Exiting...")
                break
            except Exception as e:
                logger.critical(f"An unexpected error occurred in the main loop: {e}", exc_info=True)
                await asyncio.sleep(POLLING_INTERVAL_SECONDS * 2) # Longer delay on critical failure

    async def _reconnect(self):
        """
        Handles the reconnection logic for chain connectors.
        """
        # Simple reconnect logic, could be enhanced with exponential backoff
        while True:
            try:
                self.source_chain.connect()
                self.dest_chain.connect()
                # Re-create filter after reconnection
                self.event_filter = self.source_contract.events.TokensLocked.create_filter(fromBlock='latest')
                logger.info("Successfully reconnected to both chains.")
                break
            except Exception as e:
                logger.error(f"Reconnection failed: {e}. Retrying in 30 seconds...")
                await asyncio.sleep(30)


if __name__ == '__main__':
    # In a real application, you would validate the configuration more thoroughly.
    app_config = {
        'source_rpc': SOURCE_CHAIN_RPC,
        'dest_rpc': DEST_CHAIN_RPC,
        'source_contract_address': SOURCE_BRIDGE_ADDRESS,
        'source_contract_abi': SOURCE_BRIDGE_ABI,
    }

    # Basic check for required environment variables
    if not app_config['source_rpc'] or not app_config['dest_rpc']:
        logger.critical("RPC URLs for source and/or destination chains are not configured. Please set SOURCE_CHAIN_RPC_URL and DEST_CHAIN_RPC_URL.")
    else:
        listener = CrossChainEventListener(app_config)
        asyncio.run(listener.run())

# @-internal-utility-start
def get_config_value_3468(key: str):
    """Reads a value from a simple key-value config. Added on 2025-11-05 09:12:43"""
    with open('config.ini', 'r') as f:
        for line in f:
            if line.startswith(key):
                return line.split('=')[1].strip()
    return None
# @-internal-utility-end

