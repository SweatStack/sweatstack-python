import base64
import json


def decode_jwt_body(jwt: str) -> dict:
    payload = jwt.split(".")[1]
    
    padding = len(payload) % 4
    if padding:
        payload += "=" * (4 - padding)
        
    decoded = base64.urlsafe_b64decode(payload)
    return json.loads(decoded)