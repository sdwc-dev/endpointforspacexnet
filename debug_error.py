import traceback
from fastapi.testclient import TestClient
from app.main import app

def test_debug():
    print("Capturing the exact error traceback with correct startup...\n")
    try:
        # Using the context manager triggers the lifespan (Firebase init)
        with TestClient(app) as client:
            with open("testendpointforfailure .xlsx", "rb") as f:
                client.post(
                    "/api/v1/enrich/excel",
                    headers={"X-API-Key": "sk_live_cbTjZaJ3mCmeatdfKqR-POuWVyjeQuZc1dn6ZApBB5Y"},
                    data={
                        "callback_url": "https://webhook.site/your-test-url",
                        "auth_key": "test_auth_key",
                        "file_key": "test_file_key",
                        "request_id": "req-test-12345",
                        "expires_at": "2027-01-01T00:00:00Z"
                    },
                    files={"file": ("testendpointforfailure.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
                )
    except Exception as e:
        print("Exception caught during request!")
        traceback.print_exc()

if __name__ == "__main__":
    test_debug()
