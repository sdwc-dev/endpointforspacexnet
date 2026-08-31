import requests
import sys

# 1. This hits your internal worker directly, bypassing Google Cloud Tasks
# (because Google Cloud cannot reach localhost)
URL = "http://localhost:8000/api/internal/process-lead"

# 2. Make sure this matches the internal_auth_token in your config.py
INTERNAL_AUTH_TOKEN = "super_secret_internal_token_123"

def simulate_worker():
    if len(sys.argv) < 2:
        print("Usage: python simulate_worker.py <job_id>")
        print("Example: python simulate_worker.py JOB-07AD53B62595")
        return
        
    job_id = sys.argv[1]
    print(f"Simulating Cloud Task hitting: {URL} for job: {job_id}")
    
    # 3. We use the webhook.site URL you generated!
    payload = {
        "job_id": job_id,
        "lead": {
            "id": "lead-001",
            "firstName": "Satya",
            "lastName": "Nadella",
            # Notice we are leaving out company_name, email, industry, etc. 
            # to force Perplexity and Gemini to do the research!
        },
        "callback_url": "https://webhook.site/9ade6183-a612-4b95-9d5b-e8f3dcf1b0a4",
        "auth_key": "test_auth_key",
        "file_key": "test_file_key"
    }
    
    headers = {
        "X-Internal-Auth": INTERNAL_AUTH_TOKEN,
        "Content-Type": "application/json"
    }
    
    response = requests.post(URL, json=payload, headers=headers)
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
    print("\nIf Status Code is 200, the worker is now running in the background!")
    print("Go check your webhook.site tab in your browser in about 10-20 seconds to see the results pop up!")

if __name__ == "__main__":
    simulate_worker()
