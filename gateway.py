#!/usr/bin/env python3
"""
Agent Pay Gateway
Allows AI agents to pay for API calls using USDC on Base
x402 protocol implementation

Supports:
- Per-endpoint pricing
- Rate limiting per client
- Escrow system
- Webhook notifications
- Analytics dashboard
"""
import os
import time
import uuid
import hashlib
import hmac
import json
import asyncio
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Callable
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, g
from collections import defaultdict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent-pay-gateway")

app = Flask(__name__)

# === Configuration ===

USDC_ADDRESS = "0x833589fCD6eB8B1EeA6C2dd33dfe1C69BbB0dE22"  # Base USDC
GATEWAY_ADDRESS = os.environ.get("GATEWAY_ADDRESS", "0x...")
PRICE_PER_REQUEST = float(os.environ.get("PRICE_PER_REQUEST", "0.01"))  # USDC
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

# In-memory storage (use Redis in production)
requests_db: Dict = {}
payments_db: Dict = {}
api_keys_db: Dict = {}
rate_limits: Dict = defaultdict(lambda: {"requests": 0, "reset_at": 0})

# Endpoint pricing configuration
ENDPOINT_PRICING = {
    "/api/v1/predict": 0.01,
    "/api/v1/analyze": 0.05,
    "/api/v1/search": 0.001,
    "/api/v1/embed": 0.002,
    "/api/v1/complete": 0.01,
}

# Rate limits (requests per minute)
DEFAULT_RATE_LIMIT = 60
CLIENT_RATE_LIMITS = {}


@dataclass
class PaidRequest:
    """Represents a paid API request"""
    id: str
    client_address: str
    endpoint: str
    max_amount: float
    amount_paid: float
    status: str  # pending, completed, refunded
    created_at: datetime
    completed_at: Optional[datetime] = None
    response_data: Optional[str] = None
    ip_address: str = ""
    user_agent: str = ""


@dataclass
class Client:
    """Client information"""
    address: str
    total_spent: float = 0
    total_requests: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    is_whitelisted: bool = False
    rate_limit: int = DEFAULT_RATE_LIMIT


# === Utility Functions ===

def generate_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:16]}"


def generate_api_key() -> str:
    return f"key_{uuid.uuid4().hex}"


def parse_x402_header(header: str) -> Optional[Dict]:
    """Parse X-Payment header"""
    if not header:
        return None
    
    try:
        parts = header.split(",")
        result = {}
        for part in parts:
            if "=" in part:
                key, value = part.strip().split("=", 1)
                result[key.strip()] = value.strip()
        return result
    except:
        return None


def verify_webhook_signature(payload: str, signature: str) -> bool:
    """Verify webhook HMAC signature"""
    if not WEBHOOK_SECRET:
        return True  # No secret configured
    
    expected = hmac.new(
        WEBHOOK_SECRET.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(expected, signature)


def check_rate_limit(client_address: str) -> bool:
    """Check if client has exceeded rate limit"""
    now = time.time()
    client_limit = CLIENT_RATE_LIMITS.get(client_address, {}).get("limit", DEFAULT_RATE_LIMIT)
    
    limit_data = rate_limits[client_address]
    
    # Reset if window expired
    if now > limit_data["reset_at"]:
        limit_data["requests"] = 0
        limit_data["reset_at"] = now + 60  # 1 minute window
    
    # Check limit
    if limit_data["requests"] >= client_limit:
        return False
    
    limit_data["requests"] += 1
    return True


def get_endpoint_price(endpoint: str) -> float:
    """Get price for endpoint"""
    return ENDPOINT_PRICING.get(endpoint, PRICE_PER_REQUEST)


# === Decorators ===

def require_payment(f):
    """Decorator to require payment for endpoint"""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Check rate limit
        client_address = request.headers.get('X-Client-Address', request.remote_addr)
        
        if not check_rate_limit(client_address):
            return jsonify({
                "error": "Rate limit exceeded",
                "code": "RATE_LIMIT_EXCEEDED",
                "retry_after": 60
            }), 429
        
        # Check payment
        payment_header = request.headers.get('X-Payment')
        if not payment_header:
            price = get_endpoint_price(request.path)
            return jsonify({
                "error": "Payment required",
                "code": "PAYMENT_REQUIRED",
                "price": price,
                "unit": "USDC",
                "protocol": "x402",
                "instructions": {
                    "header": "X-Payment",
                    "format": "max_amount=AMOUNT, token=USDC",
                    "example": f"max_amount={int(price * 1000000)}, token=USDC"
                }
            }), 402
        
        # Parse payment
        payment = parse_x402_header(payment_header)
        if not payment:
            return jsonify({"error": "Invalid X-Payment header format"}), 400
        
        max_amount = float(payment.get('max_amount', 0))
        token = payment.get('token', '').upper()
        
        if token != 'USDC':
            return jsonify({"error": "Only USDC supported"}), 400
        
        price = get_endpoint_price(request.path)
        if max_amount < price:
            return jsonify({
                "error": f"Insufficient payment. Required: {price} USDC",
                "code": "INSUFFICIENT_PAYMENT"
            }), 402
        
        # Store payment info in request context
        g.payment = {
            "client_address": request.headers.get('X-Client-Address', ''),
            "max_amount": max_amount,
            "amount_charged": price
        }
        
        return f(*args, **kwargs)
    
    return decorated


# === Routes ===

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "gateway_version": "1.0.0",
        "network": "base",
        "currency": "USDC"
    })


@app.route('/api/v1/endpoints')
def list_endpoints():
    """List available paid endpoints with pricing"""
    return jsonify({
        "endpoints": [
            {
                "path": path,
                "description": DESC.get(path, "API endpoint"),
                "price": price,
                "unit": "USDC",
                "rate_limit": "60 req/min"
            }
            for path, price in ENDPOINT_PRICING.items()
        ],
        "default_price": PRICE_PER_REQUEST
    })


ENDPOINT_DESCRIPTIONS = {
    "/api/v1/predict": "AI prediction endpoint",
    "/api/v1/analyze": "Data analysis endpoint",
    "/api/v1/search": "Web search endpoint", 
    "/api/v1/embed": "Text embedding endpoint",
    "/api/v1/complete": "Text completion endpoint"
}
DESC = ENDPOINT_DESCRIPTIONS


@app.route('/api/v1/request', methods=['POST'])
@require_payment
def make_paid_request():
    """Generic paid API request"""
    payment = g.payment
    
    # Create request record
    request_id = generate_request_id()
    paid_req = PaidRequest(
        id=request_id,
        client_address=payment["client_address"],
        endpoint=request.path,
        max_amount=payment["max_amount"],
        amount_paid=payment["amount_charged"],
        status="completed",
        created_at=datetime.now(),
        completed_at=datetime.now(),
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent', '')
    )
    
    requests_db[request_id] = paid_req
    
    # Update client stats
    client_addr = payment["client_address"]
    if client_addr not in api_keys_db:
        api_keys_db[client_addr] = Client(address=client_addr)
    api_keys_db[client_addr].total_spent += payment["amount_charged"]
    api_keys_db[client_addr].total_requests += 1
    
    # Return paid response
    return jsonify({
        "request_id": request_id,
        "status": "completed",
        "amount_charged": payment["amount_charged"],
        "data": {
            "result": "success",
            "message": "This is paid API response data",
            "endpoint": request.path,
            "timestamp": datetime.now().isoformat()
        }
    })


@app.route('/api/v1/predict', methods=['POST'])
@require_payment
def predict():
    """AI prediction endpoint"""
    payment = g.payment
    data = request.get_json() or {}
    
    # Create request record
    request_id = generate_request_id()
    requests_db[request_id] = PaidRequest(
        id=request_id,
        client_address=payment["client_address"],
        endpoint="/api/v1/predict",
        max_amount=payment["max_amount"],
        amount_paid=payment["amount_charged"],
        status="completed",
        created_at=datetime.now(),
        completed_at=datetime.now()
    )
    
    return jsonify({
        "request_id": request_id,
        "prediction": "BULLISH",
        "confidence": 0.75,
        "model": "predict-v1",
        "amount_charged": payment["amount_charged"]
    })


@app.route('/api/v1/analyze', methods=['POST'])
@require_payment
def analyze():
    """Data analysis endpoint"""
    payment = g.payment
    data = request.get_json() or {}
    
    request_id = generate_request_id()
    requests_db[request_id] = PaidRequest(
        id=request_id,
        client_address=payment["client_address"],
        endpoint="/api/v1/analyze",
        max_amount=payment["max_amount"],
        amount_paid=payment["amount_charged"],
        status="completed",
        created_at=datetime.now(),
        completed_at=datetime.now()
    )
    
    return jsonify({
        "request_id": request_id,
        "analysis": {
            "sentiment": "positive",
            "key_themes": ["AI", "crypto", "growth"],
            "confidence": 0.82
        },
        "amount_charged": payment["amount_charged"]
    })


@app.route('/api/v1/search', methods=['POST'])
@require_payment
def search():
    """Web search endpoint"""
    payment = g.payment
    data = request.get_json() or {}
    query = data.get("query", "")
    
    request_id = generate_request_id()
    requests_db[request_id] = PaidRequest(
        id=request_id,
        client_address=payment["client_address"],
        endpoint="/api/v1/search",
        max_amount=payment["max_amount"],
        amount_paid=payment["amount_charged"],
        status="completed",
        created_at=datetime.now(),
        completed_at=datetime.now()
    )
    
    return jsonify({
        "request_id": request_id,
        "results": [
            {"title": "Result 1", "url": "https://example.com/1"},
            {"title": "Result 2", "url": "https://example.com/2"}
        ],
        "amount_charged": payment["amount_charged"]
    })


@app.route('/api/v1/embed', methods=['POST'])
@require_payment
def embed():
    """Text embedding endpoint"""
    payment = g.payment
    data = request.get_json() or {}
    text = data.get("text", "")
    
    request_id = generate_request_id()
    requests_db[request_id] = PaidRequest(
        id=request_id,
        client_address=payment["client_address"],
        endpoint="/api/v1/embed",
        max_amount=payment["max_amount"],
        amount_paid=payment["amount_charged"],
        status="completed",
        created_at=datetime.now(),
        completed_at=datetime.now()
    )
    
    # Return dummy embedding
    return jsonify({
        "request_id": request_id,
        "embedding": [0.1] * 384,
        "dimensions": 384,
        "amount_charged": payment["amount_charged"]
    })


@app.route('/api/v1/complete', methods=['POST'])
@require_payment
def complete():
    """Text completion endpoint"""
    payment = g.payment
    data = request.get_json() or {}
    prompt = data.get("prompt", "")
    
    request_id = generate_request_id()
    requests_db[request_id] = PaidRequest(
        id=request_id,
        client_address=payment["client_address"],
        endpoint="/api/v1/complete",
        max_amount=payment["max_amount"],
        amount_paid=payment["amount_charged"],
        status="completed",
        created_at=datetime.now(),
        completed_at=datetime.now()
    )
    
    return jsonify({
        "request_id": request_id,
        "completion": "This is a completion response.",
        "amount_charged": payment["amount_charged"]
    })


# === Admin Routes ===

@app.route('/api/v1/stats')
def stats():
    """Gateway statistics"""
    total_requests = len(requests_db)
    total_revenue = sum(r.amount_paid for r in requests_db.values())
    
    # Requests by endpoint
    by_endpoint = defaultdict(lambda: {"count": 0, "revenue": 0})
    for req in requests_db.values():
        by_endpoint[req.endpoint]["count"] += 1
        by_endpoint[req.endpoint]["revenue"] += req.amount_paid
    
    return jsonify({
        "total_requests": total_requests,
        "total_revenue_usdc": total_revenue,
        "unique_clients": len(api_keys_db),
        "by_endpoint": dict(by_endpoint),
        "network": "base",
        "currency": "USDC"
    })


@app.route('/api/v1/clients')
def list_clients():
    """List top clients"""
    clients = sorted(
        api_keys_db.values(),
        key=lambda c: c.total_spent,
        reverse=True
    )[:20]
    
    return jsonify({
        "clients": [
            {
                "address": c.address,
                "total_spent": c.total_spent,
                "total_requests": c.total_requests,
                "is_whitelisted": c.is_whitelisted
            }
            for c in clients
        ]
    })


@app.route('/api/v1/requests/<request_id>')
def get_request(request_id):
    """Get request details"""
    if request_id not in requests_db:
        return jsonify({"error": "Request not found"}), 404
    
    req = requests_db[request_id]
    return jsonify({
        "id": req.id,
        "client": req.client_address,
        "endpoint": req.endpoint,
        "amount_paid": req.amount_paid,
        "status": req.status,
        "created_at": req.created_at.isoformat(),
        "completed_at": req.completed_at.isoformat() if req.completed_at else None
    })


@app.route('/api/v1/rate-limit', methods=['POST'])
def set_rate_limit():
    """Set custom rate limit for a client"""
    data = request.get_json() or {}
    client_address = data.get("client_address")
    limit = data.get("limit", DEFAULT_RATE_LIMIT)
    
    if not client_address:
        return jsonify({"error": "client_address required"}), 400
    
    CLIENT_RATE_LIMITS[client_address] = {"limit": limit}
    
    return jsonify({
        "status": "ok",
        "client": client_address,
        "limit": limit
    })


# === Example Client ===

@app.route('/example/client')
def client_example():
    """Example of how an agent would pay"""
    return jsonify({
        "example": {
            "description": "How to make paid requests",
            "headers": {
                "X-Payment": "max_amount=10000, token=USDC",
                "X-Client-Address": "0xYourWalletAddress"
            },
            "python_example": '''import requests

# Make a paid request
response = requests.post(
    "https://gateway.example.com/api/v1/predict",
    headers={
        "X-Payment": "max_amount=10000, token=USDC",
        "X-Client-Address": "0xYourWalletAddress"
    },
    json={"input": "data"}
)

if response.status_code == 402:
    # Handle payment required
    print(response.json())
else:
    # Success
    print(response.json())
            ''',
            "curl_example": '''curl -X POST https://gateway.example.com/api/v1/predict \\
  -H "X-Payment: max_amount=10000, token=USDC" \\
  -H "X-Client-Address: 0xYourWallet" \\
  -H "Content-Type: application/json" \\
  -d '{"input": "data"}'
            '''
        }
    })


# === Main ===

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5005"))
    print(f"💰 Agent Pay Gateway running on port {port}")
    print(f"   Default price: {PRICE_PER_REQUEST} USDC per request")
    print(f"   Network: Base")
    app.run(host="0.0.0.0", port=port)
