import os
import json
import random
import time
import requests
from fake_useragent import UserAgent
from web3 import Web3, HTTPProvider, Account
import colorlog
import logging
from colorama import init, Fore

# Load MintFun ABI and private keys
with open("MintFun_ABI.json", 'r') as f:
    MintFun_ABI = json.load(f)

with open('private_keys.txt', 'r') as keys_file:
    private_keys = keys_file.read().splitlines()


# DESIRED_GAS_PRICE = int(input("Enter the desired gas price (e.g., 15): "))
# MIN_DELAY = int(input("Enter the minimum delay in seconds (e.g., 120): "))
# MAX_DELAY = int(input("Enter the maximum delay in seconds (e.g., 240): "))

USE_RAINBOW = True
DESIRED_GAS_PRICE = 33
MIN_DELAY = 120
MAX_DELAY = 240

def SetupGayLogger(logger_name, USE_RAINBOW_COLORS=USE_RAINBOW):
    """Set up logger with optional rainbow colors."""
    init()

    def rainbow_colorize(text):
        """Add rainbow colors to the text."""
        colors = [Fore.RED, Fore.YELLOW, Fore.GREEN, Fore.CYAN, Fore.BLUE, Fore.MAGENTA]
        return ''.join(colors[i % len(colors)] + char for i, char in enumerate(text))

    class RainbowColoredFormatter(colorlog.ColoredFormatter):
        def format(self, record):
            message = super().format(record)
            return rainbow_colorize(message) if USE_RAINBOW_COLORS else message

    logger = colorlog.getLogger(logger_name)
    logger.handlers.clear()

    handler = colorlog.StreamHandler()
    formatter = RainbowColoredFormatter(
        "|%(log_color)s%(asctime)s| - [%(name)s] - %(levelname)s - %(message)s",
        datefmt=None,
        reset=False,
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_white',
        }
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    return logger
def wait_for_gas_price_to_decrease(node_url, desired_gas_price):
    """Wait until the Ethereum base fee drops to a desired level."""
    while True:
        try:
            # Fetching the base fee for the latest block
            data = {
                "jsonrpc":"2.0",
                "method":"eth_getBlockByNumber",
                "params":['latest', True],
                "id":1
            }
            headers = {'Content-Type': 'application/json'}
            response = requests.post(node_url, headers=headers, data=json.dumps(data))
            response.raise_for_status()

            result = response.json()['result']
            current_base_fee = int(result['baseFeePerGas'], 16) / 10**9  # Convert from Wei to Gwei

        except requests.exceptions.HTTPError as errh:
            print(f"HTTP Error: {errh}")
            time.sleep(10)  # Retry after 10 sec in case of a HTTP error
            continue
        except requests.exceptions.ConnectionError as errc:
            print(f"Error Connecting: {errc}")
            time.sleep(10)  # Retry after 10 sec in case of a connection error
            continue

        if current_base_fee <= desired_gas_price:
            break  # Exit the loop if the base fee is less than or equal to the desired level
        else:
            print(f"Current base fee ({current_base_fee} Gwei) is higher than desired ({desired_gas_price} Gwei). Waiting...", end="", flush=True)
            time.sleep(10)
            print("\033[K", end="\r", flush=True)
def get_sign(main_address: str):
    """Fetch signature for a given address."""
    while True:
        try:
            url = f'https://mint.fun/api/mintfun/fundrop/season1/mint?address={main_address}'
            headers ={
                'User-Agent': UserAgent().random,
                'Referer': 'https://mint.fun/fundrop',
            }
            resp = requests.get(url, headers=headers)
            if resp.status_code == 200:
                a = json.loads(resp.text)
                sign = a['signature']
                return sign
        except Exception:
            print("An error occurred while fetching the signature.")
            time.sleep(10)  # Wait a bit before retrying

def mint(private_key, logger):
    """Mint tokens using a given private key."""
    w3 = Web3(HTTPProvider('https://ethereum.publicnode.com'))
    account = w3.eth.account.from_key(private_key)
    address_checksum = w3.to_checksum_address(account.address)
    contract_address = w3.to_checksum_address('0xfFFffffFB9059A7285849baFddf324e2c308c164')
    contract = w3.eth.contract(address=contract_address, abi=MintFun_ABI)

    base_fee = w3.eth.fee_history(w3.eth.get_block_number(), 'latest')['baseFeePerGas'][-1]
    priority_max = w3.to_wei(1, 'gwei')

    signature = get_sign(address_checksum)

    swap_txn = contract.functions.mint([4], [1], 1, signature).build_transaction({
        'from': address_checksum,
        'nonce': w3.eth.get_transaction_count(address_checksum),
        'maxFeePerGas': base_fee + priority_max,
        'maxPriorityFeePerGas': priority_max
    })

    # Estimate gas limit and update the transaction
    estimated_gas_limit = round(w3.eth.estimate_gas(swap_txn))
    swap_txn.update({'gas': estimated_gas_limit})

    # Sign transaction using private key
    signed_txn = w3.eth.account.sign_transaction(swap_txn, private_key)

    try:
        txn_hash = w3.eth.send_raw_transaction(signed_txn.rawTransaction)
        txn_receipt = w3.eth.wait_for_transaction_receipt(txn_hash, timeout=666)
    except ValueError:
        logger.warning("Insufficient funds for transaction or another error occurred. Check manually.")
        with open('failed_transactions.txt', 'a') as f:
            f.write(f'{address_checksum}, transaction failed due to error\n')
        return 0

    # Check transaction status
    if txn_receipt['status'] == 1:
        if private_key in private_keys:
            private_keys.remove(private_key)
        with open('private_keys.txt', 'w') as keys_file:
            for key in private_keys:
                keys_file.write(key + '\n')

        logger.info(f"Transaction was successful. Txn hash: https://etherscan.io/tx/{txn_hash.hex()}")
        with open('successful_transactions.txt', 'a') as f:
            f.write(f'{address_checksum}, successful transaction, Txn hash: https://etherscan.io/tx/{txn_hash.hex()}\n')
        return 1
    else:
        logger.warning(f"Transaction was unsuccessful. Txn hash: https://etherscan.io/tx/{txn_hash.hex()}")
        with open('failed_transactions.txt', 'a') as f:
            f.write(f'{address_checksum}, transaction failed, Txn hash: https://etherscan.io/tx/{txn_hash.hex()}\n')
        return 0

# Main Execution
print("Author channel: https://t.me/CryptoBub_ble")
random.shuffle(private_keys)
logger = SetupGayLogger("Mister Chocolate")

for id, private_key in enumerate(private_keys):
    account = Account.from_key(private_key)
    wait_for_gas_price_to_decrease("https://ethereum.publicnode.com", DESIRED_GAS_PRICE)
    logger.info(f"Started work with wallet: {account.address}")
    mint(private_key, logger)
    slp = random.randint(MIN_DELAY, MAX_DELAY)
    logger.warning(f"Sleeping for {slp} seconds before the next operation.")
    logger.error("Subscribe - https://t.me/CryptoBub_ble")
    time.sleep(slp)