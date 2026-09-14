import traceback
from fastapi.testclient import TestClient
from app.main import app

def test_debug():
    print("Capturing the exact error traceback with correct startup...\n")
    try:
        # Using the context manager triggers the lifespan (Firebase init)
        with TestClient(app) as client:
            with open("testendpointforfailure .xlsx", "rb") as f:
                
    except Exception as e:
        print("Exception caught during request!")
        traceback.print_exc()

if __name__ == "__main__":
    test_debug()
