# Transactions proof

The transactions proof verifies each transaction signature and makes the
transactions data easily accessible to the EVM proof via the transactions
table.


## Transaction encoding

Different types of transaction encoding exists.  On the first iteration of the zkEVM we will only support Legacy transactions with EIP-155.  We plan to add support for Non-Legacy (EIP-2718) transactions later.

### Legacy type:

```
rlp([nonce, gasPrice, gasLimit, to, value, data, v, r, s])
```

Before EIP-155:

Hashed data to sign: `(nonce, gasprice, startgas, to, value, data)` with `sig_v = {0,1} + 27`

After EIP-155:

Hashed data to sign: `(nonce, gasprice, startgas, to, value, data, chain_id, 0, 0)` with `sig_v = {0,1} + CHAIN_ID * 2 + 35`

Where `{0,1}` is the parity of the `y` value of the curve point for which `r`
is the x-value in the secp256k1 signing process.

### Non-Legacy (EIP-2718) type:

From https://eips.ethereum.org/EIPS/eip-1559 and https://eips.ethereum.org/EIPS/eip-2718

```
0x02 || rlp([chain_id, nonce, max_priority_fee_per_gas, max_fee_per_gas, gas_limit, destination, amount, data, access_list, signature_y_parity, signature_r, signature_s])
```

Hashed data to sign: TODO

## Circuit behaviour

For every transaction defined as the parameters `{nonce, gas_price, gas_limit,
to, value, data, sig_v, sig_r, sig_s}`, the circuit verifies the following:

1. `txSignData = rlp([nonce, gas_price, gas_limit, to, value, data, chain_id, 0, 0])`
2. `txSignHash = keccak(txSignData)`
3. `sig_parity = sig_v - 35 - chain_id / 2`
4. `ecRecover(txSignHash, sig_parity, sig_r, sig_s) = pubKey`
5. `fromAddress = keccak(pubKey)[-20:]`

- The rlp encoding of transaction parameters (step 1) will be done in the rlp
  circuit; the tx circuit will do a lookup to the rlp table.
  - NOTE(Edu): I'm not really sure if we'll go this route, or we'll just use
    rlp chips/gadgets in the circuits that need them.
- The keccak hash verification (step 2) will be done in the keccak circuit;
  the tx circuit will do a lookup to the keccak table.
- The public key recovery from the message and signature (step 3) will be done
  in the ECDSA circuit; the tx circuit will do a lookup to the keccak table.

From this information the circuit builds the TxTable:

Where:
- Gas = gas_limit
- GasTipCap = 0
- GasFeeCap = 0
- CallerAddress = fromAddress
- CalleeAddress = to
- IsCreate = ?
- CallDataLength = len(data)
- CallData[$ByteIndex] = data[$ByteIndex]

| 0 TxID | 1 Tag               | 2          | 3 value |
| ---    | ---                 | ---        | ---     |
|        | *TxContextFieldTag* |            |         |
| $TxID  | Nonce               | 0          | $value  |
| $TxID  | Gas                 | 0          | $value  |
| $TxID  | GasPrice            | 0          | $value  |
| $TxID  | GasTipCap           | 0          | $value  |
| $TxID  | GasFeeCap           | 0          | $value  |
| $TxID  | CallerAddress       | 0          | $value  |
| $TxID  | CalleeAddress       | 0          | $value  |
| $TxID  | IsCreate            | 0          | $value  |
| $TxID  | Value               | 0          | $value  |
| $TxID  | CallDataLength      | 0          | $value  |
| $TxID  | CallData            | $ByteIndex | $value  |


## Code

Please refer to `src/zkevm-specs/tx.py`.
