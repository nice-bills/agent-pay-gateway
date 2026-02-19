#!/usr/bin/env python3
"""
Agent Pay Gateway
Allows AI agents to pay for API calls using USDC on Base
x402 protocol implementation
"""
import os
import time
import uuid
import hashlib
from dataclasses import dataclass, field
from typing import Dict, Optional
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, g

app = Flask(__name__)

# Configuration
USDC_ADDRESS = "0x833589fCD6eB8B1EeA6C2dd33dfe1C69BbB0dE22"  # Base USDC
GATEWAY_ADDRESS = os.environ.get("GATEWAY_ADDRESS", "0x...")
PRICE_PER_REQUEST = float(os.environ.get("PRICE_PER_REQUEST", "0.01"))  # USDC

# In-memory storage (use Redis in production)
requests_db: Dict = {}
payments_db: Dict = {}
api_keys_db: Dict = {}


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


def generate_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:16]}"


def parse_x402_header(header: str) -> Optional[Dict]:
    """Parse X-Payment header"""
    if not header:
        return None
    
    try:
        parts = header.split(",")
        result = {}
        for part in parts:
            key, value = part.strip().split("=")
            result[key.strip()] = value.strip()
        return result
    except:
        return None


def verify_payment(client_address: str, amount: float) -> bool:
    """
    In production: check on-chain USDC balance or escrow contract
    For now: simplified - trust the payment header
    """
    # TODO: Integrate with Base RPC to verify payment
    return True  # Simplified


@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "price_per_request": PRICE_PER_REQUEST,
        "currency": "USDC",
        "network": "base"
    })


@app.route('/api/v1/endpoints')
def list_endpoints():
    """List available paid endpoints"""
    return jsonify({
        "endpoints": [
            {
                "path": "/api/v1/predict",
                "description": "AI prediction endpoint",
                "price": 0.01,
                "unit": "per_request"
            },
            {
                "path": "/api/v1/analyze",
                "description": "Data analysis endpoint", 
                "price": 0.05,
                "unit": "per_request"
            },
            {
                "path": "/api/v1/search",
                "description": "Web search endpoint",
                "price": 0.001,
                "unit": "per_request"
            }
        ]
    })


@app.route('/api/v1/request', methods=['POST'])
def make_paid_request():
    """
    Make a paid API request
    Headers:
      X-Payment: max_amount=100, token=USDC
      X-Client-Address: 0x...
    """
    # Parse payment header
    payment_header = request.headers.get('X-Payment')
    client_address = request.headers.get('X-Client-Address', '')
    
    if not payment_header:
        return jsonify({
            "error": "Missing X-Payment header",
            "code": "PAYMENT_REQUIRED",
            "price": PRICE_PER_REQUEST,
            "protocol": "x402"
        }), 402
    
    payment = parse_x402_header(payment_header)
    if not payment:
        return jsonify({"error": "Invalid X-Payment header format"}), 400
    
    max_amount = float(payment.get('max_amount', 0))
    token = payment.get('token', '').upper()
    
    if token != 'USDC':
        return jsonify({"error": "Only USDC supported"}), 400
    
    if max_amount < PRICE_PER_REQUEST:
        return jsonify({
            "error": f"Insufficient payment. Required: {PRICE_PER_REQUEST} USDC",
            "code": "INSUFFICIENT_PAYMENT"
        }), 402
    
    # Verify payment (in production, check on-chain)
    if not verify_payment(client_address, max_amount):
        return jsonify({"error": "Payment verification failed"}), 402
    
    # Create request record
    request_id = generate_request_id()
    paid_req = PaidRequest(
        id=request_id,
        client_address=client_address,
        endpoint=request.path,
        max_amount=max_amount,
        amount_paid=PRICE_PER_REQUEST,
        status="completed",
        created_at=datetime.now(),
        completed_at=datetime.now()
    )
    
    requests_db[request_id] = paid_req
    
    # Return paid response
    return jsonify({
        "request_id": request_id,
        "status": "completed",
        "amount_charged": PRICE_PER_REQUEST,
        "data": {
            "result": "success",
            "message": "This is paid API response data",
            "endpoint": request.path,
            "timestamp": datetime.now().isoformat()
        }
    })


@app.route('/api/v1/predict', methods=['POST'])
def predict():
    """Example: AI prediction endpoint"""
    # Check payment
    payment_header = request.headers.get('X-Payment')
    if not payment_header:
        return jsonify({
            "error": "Payment required",
            "code": "PAYMENT_REQUIRED",
            "price": 0.01,
            "unit": "USDC per request"
        }), 402
    
    payment = parse_x402_header(payment_header)
    max_amount = float(payment.get('max_amount', 0)) if payment else 0
    
    if max_amount < 0.01:
        return jsonify({"error": "Insufficient payment"}), 402
    
    data = request.get_json() or {}
    
    # Return prediction (simplified)
    return jsonify({
        "prediction": "BULLISH",
        "confidence": 0.75,
        "model": "predict-v1",
        "price_charged": 0.01
    })


@app.route('/api/v1/analyze', methods=['POST'])
def analyze():
    """Example: Data analysis endpoint"""
    payment_header = request.headers.get('X-Payment')
    if not payment_header:
        return jsonify({
            "error": "Payment required",
            "code": "PAYMENT_REQUIRED", 
            "price": 0.05,
            "unit": "USDC per request"
        }), 402
    
    payment = parse_x402_header(payment_header)
    max_amount = float(payment.get('max_amount', 0)) if payment else 0
    
    if max_amount < 0.05:
        return jsonify({"error": "Insufficient payment"}), 402
    
    data = request.get_json() or {}
    
    return jsonify({
        "analysis": {
            "sentiment": "positive",
            "key_themes": ["AI", "crypto", "growth"],
            "confidence": 0.82
        },
        "price_charged": 0.05
    })


@app.route('/api/v1/stats')
def stats():
    """Gateway statistics"""
    total_requests = len(requests_db)
    total_revenue = sum(r.amount_paid for r in requests_db.values())
    
    return jsonify({
        "total_requests": total_requests,
        "total_revenue_usdc": total_revenue,
        "price_per_request": PRICE_PER_REQUEST,
        "network": "base",
        "currency": "USDC"
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


# === Example client usage ===
@app.route('/example/client')
def client_example():
    """Example of how an agent would pay"""
    return jsonify({
        "example": {
            "headers": {
                "X-Payment": "max_amount=100, token=USDC",
                "X-Client-Address": "0x123..."
            },
            "python_example": '''
import requests

response = requests.post(
    "https://gateway.example.com/api/v1/predict",
    headers={
        "X-Payment": "max_amount=100, token=USDC",
        "X-Client-Address": "0xYourWalletAddress"
    },
    json={"input": "data"}
)
            '''
        }
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5005"))
    print(f"💰 Agent Pay Gateway running on port {port}")
    print(f"   Price: {PRICE_PER_REQUEST} USDC per request")
    app.run(host="0.0.0.0", port=port)
