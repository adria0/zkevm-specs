from __future__ import annotations
from typing import Any, Iterator, Optional, Sequence
from functools import reduce
from itertools import chain

from ..util import (
    U64,
    U160,
    U256,
    Array3,
    Array4,
    RLC,
    keccak256,
    GAS_COST_TX_CALL_DATA_PER_NON_ZERO_BYTE,
    GAS_COST_TX_CALL_DATA_PER_ZERO_BYTE,
    EMPTY_HASH,
    EMPTY_TRIE_HASH,
)
from .table import BlockContextFieldTag, TxContextFieldTag
from .opcode import get_push_size, Opcode


class Block:
    coinbase: U160
    gas_limit: U64
    block_number: U256
    time: U64
    difficulty: U256
    base_fee: U256

    # history_hashes contains most recent 256 block hashes in history, where
    # the lastest one is at history_hashes[-1].
    history_hashes: Sequence[U256]

    def __init__(
        self,
        coinbase: U160 = 0x10,
        gas_limit: U64 = int(15e6),
        block_number: U256 = 0,
        time: U64 = 0,
        difficulty: U256 = 0,
        base_fee: U256 = int(1e9),
        history_hashes: Sequence[U256] = [],
    ) -> None:
        assert len(history_hashes) <= min(256, block_number)

        self.coinbase = coinbase
        self.gas_limit = gas_limit
        self.block_number = block_number
        self.time = time
        self.difficulty = difficulty
        self.base_fee = base_fee
        self.history_hashes = history_hashes

    def table_assignments(self, randomness: int) -> Sequence[Array3]:
        return [
            (BlockContextFieldTag.Coinbase, 0, self.coinbase),
            (BlockContextFieldTag.GasLimit, 0, self.gas_limit),
            (BlockContextFieldTag.BlockNumber, 0, RLC(self.block_number, randomness)),
            (BlockContextFieldTag.Time, 0, RLC(self.time, randomness)),
            (BlockContextFieldTag.Difficulty, 0, RLC(self.difficulty, randomness)),
            (BlockContextFieldTag.BaseFee, 0, RLC(self.base_fee, randomness)),
        ] + [
            (BlockContextFieldTag.BlockHash, self.block_number - idx - 1, RLC(block_hash, randomness))
            for idx, block_hash in enumerate(reversed(self.history_hashes))
        ]


class Transaction:
    id: int
    nonce: U64
    gas: U64
    gas_price: U256
    caller_address: U160
    callee_address: Optional[U160]
    value: U256
    call_data: bytes

    def __init__(
        self,
        id: int = 1,
        nonce: U64 = 0,
        gas: U64 = 21000,
        gas_price: U256 = int(2e9),
        caller_address: U160 = 0,
        callee_address: Optional[U160] = None,
        value: U256 = 0,
        call_data: bytes = bytes(),
    ) -> None:
        self.id = id
        self.nonce = nonce
        self.gas = gas
        self.gas_price = gas_price
        self.caller_address = caller_address
        self.callee_address = callee_address
        self.value = value
        self.call_data = call_data

    def call_data_gas_cost(self) -> int:
        return reduce(
            lambda acc, byte: (
                acc + (GAS_COST_TX_CALL_DATA_PER_ZERO_BYTE if byte is 0 else GAS_COST_TX_CALL_DATA_PER_NON_ZERO_BYTE)
            ),
            self.call_data,
            0,
        )

    def table_assignments(self, randomness: int) -> Iterator[Array4]:
        return chain(
            [
                (self.id, TxContextFieldTag.Nonce, 0, self.nonce),
                (self.id, TxContextFieldTag.Gas, 0, self.gas),
                (self.id, TxContextFieldTag.GasPrice, 0, RLC(self.gas_price, randomness)),
                (self.id, TxContextFieldTag.CallerAddress, 0, self.caller_address),
                (self.id, TxContextFieldTag.CalleeAddress, 0, self.callee_address),
                (self.id, TxContextFieldTag.IsCreate, 0, self.callee_address is None),
                (self.id, TxContextFieldTag.Value, 0, RLC(self.value, randomness)),
                (self.id, TxContextFieldTag.CallDataLength, 0, len(self.call_data)),
                (self.id, TxContextFieldTag.CallDataGasCost, 0, self.call_data_gas_cost()),
            ],
            map(lambda item: (self.id, TxContextFieldTag.CallData, item[0], item[1]), enumerate(self.call_data)),
        )


class Bytecode:
    code: bytearray

    def __init__(self, code: Optional[bytearray] = None) -> None:
        self.code = bytearray() if code is None else code

    def __getattr__(self, name: str):
        def method(*args) -> Bytecode:
            try:
                opcode = Opcode[name.removesuffix("_").upper()]
            except KeyError:
                raise ValueError(f"Invalid opcode {name}")

            if opcode.is_push():
                assert len(args) == 1
                self.push(args[0], opcode - Opcode.PUSH1 + 1)
            elif opcode.is_dup() or opcode.is_swap():
                assert len(args) == 0
                self.code.append(opcode)
            else:
                assert len(args) <= 1024 - opcode.max_stack_pointer()
                for arg in reversed(args):
                    self.push(arg, 32)
                self.code.append(opcode)

            return self

        return method

    def push(self, value: Any, n_bytes: int = 32) -> Bytecode:
        if isinstance(value, int):
            value = value.to_bytes(n_bytes, "big")
        elif isinstance(value, str):
            value = bytes.fromhex(value.lower().removeprefix("0x"))
        elif isinstance(value, RLC):
            value = value.be_bytes()
        elif isinstance(value, bytes) or isinstance(value, bytearray):
            ...
        else:
            raise NotImplementedError(f"Value of type {type(value)} is not yet supported")

        assert 0 < len(value) <= n_bytes, ValueError("Too many bytes as data portion of PUSH*")

        opcode = Opcode.PUSH1 + n_bytes - 1
        self.code.append(opcode)
        self.code.extend(value.rjust(n_bytes, bytes(1)))

        return self

    def hash(self) -> int:
        return int.from_bytes(keccak256(self.code), "big")

    def table_assignments(self, randomness: int) -> Iterator[Array4]:
        class BytecodeIterator:
            idx: int
            push_data_left: int
            hash: RLC
            code: bytes

            def __init__(self, hash: RLC, code: bytes):
                self.idx = 0
                self.push_data_left = 0
                self.hash = hash
                self.code = code

            def __iter__(self):
                return self

            def __next__(self):
                if self.idx == len(self.code):
                    raise StopIteration

                idx = self.idx
                byte = self.code[idx]

                is_code = self.push_data_left == 0
                self.push_data_left = get_push_size(byte) if is_code else self.push_data_left - 1

                self.idx += 1

                return (self.hash, idx, byte, is_code)

        return BytecodeIterator(RLC(self.hash(), randomness), self.code)


class Account:
    address: U160
    nonce: U256
    balance: U256
    code_hash: U256
    storage_trie_hash: U256

    def __init__(
        self,
        address: U160 = 0,
        nonce: U256 = 0,
        balance: U256 = 0,
        code_hash: U256 = EMPTY_HASH,
        storage_trie_hash: U256 = EMPTY_TRIE_HASH,
    ) -> None:
        self.address = address
        self.nonce = nonce
        self.balance = balance
        self.code_hash = code_hash
        self.storage_trie_hash = storage_trie_hash
