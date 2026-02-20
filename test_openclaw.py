import websocket
import json
import time
import hashlib

token = "213ab9540d6167ff1289ac37ad1220f62d74ef1dd4efb035"
url = f"ws://127.0.0.1:18792/ws"

print(f"Connecting to {url}...")
ws = websocket.create_connection(url, timeout=10)
print("Connected!")

# Wait for challenge
result = ws.recv()
data = json.loads(result)
print(f"Challenge: {json.dumps(data)[:200]}")

if data.get("event") == "connect.challenge":
    nonce = data["payload"]["nonce"]
    # Respond with auth token
    auth_msg = {
        "type": "event",
        "event": "connect.auth",
        "payload": {
            "token": token,
            "nonce": nonce,
            "client": "test-script",
            "role": "operator"
        }
    }
    print(f"Sending auth...")
    ws.send(json.dumps(auth_msg))

    # Wait for auth response
    result = ws.recv()
    print(f"Auth response: {result[:300]}")

    # Now send chat message
    msg = {
        "id": "test-1",
        "method": "chat.send",
        "params": {
            "session": "main",
            "text": "Hello, say hi in Korean"
        }
    }
    print(f"Sending chat message...")
    ws.send(json.dumps(msg))

    # Receive responses
    print("Waiting for responses...")
    start = time.time()
    while time.time() - start < 20:
        try:
            result = ws.recv()
            if not result:
                continue
            try:
                data = json.loads(result)
                print(f"Received: {json.dumps(data, ensure_ascii=False)[:500]}")
                if "error" in data:
                    print(f"ERROR: {data['error']}")
                    break
            except json.JSONDecodeError:
                print(f"Raw: {result[:200]}")
        except websocket.WebSocketTimeoutException:
            continue
        except Exception as e:
            print(f"Exception: {e}")
            break

ws.close()
print("Done!")
