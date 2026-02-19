# Agent Pay Gateway - PRD

## Problem

AI agents need to pay for API calls but:
- Can't use credit cards
- API keys are risky (leak = infinite billing)
- No standard way for agents to pay per-request

## Solution

x402 Payment Gateway - AI agents pay for API calls with USDC on Base

## How It Works

1. **Server** advertises price per request (e.g., $0.001 per API call)
2. **Agent** sends USDC to gateway + includes requested data
3. **Gateway** verifies payment, returns data
4. **No API keys needed**

## Architecture

```
Agent → x402 Header (max_amount) → Gateway Contract → API Response
                                    ↓
                            Payment held in escrow
                                    ↓
                            Released to service provider
```

## Protocol (x402)

- Uses HTTP 402 Payment Required
- Header: `X-Payment: max_amount=1000, token=USDC`
- Agent includes payment in request
- Server validates and serves

## Features

1. **Payment Validation** - Verify USDC transfer before serving
2. **Rate Limiting** - Per-agent limits
3. **Escrow** - Hold payments until service rendered
4. **Refund** - For failed requests
5. **Dashboard** - Track earnings

## Tech Stack

- Python (Flask/FastAPI)
- Solidity (payment contract)
- Base (USDC)
- x402 protocol

## Success Metrics

- Requests served via crypto
- Revenue generated
- Latency overhead (should be <100ms)
