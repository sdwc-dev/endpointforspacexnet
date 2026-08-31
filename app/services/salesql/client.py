"""
app/services/salesql/client.py — SalesQL API Client.
"""
from __future__ import annotations

import httpx
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings
from app.utils.logging import get_logger

log = get_logger(__name__)

SALESQL_API_BASE = "https://api-public.salesql.com/v1"

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError))
)
async def bulk_research_leads(leads: list[dict]) -> list[dict]:
    """
    Call SalesQL enrichment API for a batch of leads concurrently.
    """
    if not settings.saleql_api_key:
        log.warning("SaleQL API Key not configured. Returning empty results.")
        return [{} for _ in leads]

    headers = {
        "Authorization": f"Bearer {settings.saleql_api_key}",
        "Content-Type": "application/json"
    }
    
    queries = []
    for lead in leads:
        query = {}
        if lead.get("email"):
            query["email"] = lead["email"]
        elif lead.get("first_name") and lead.get("last_name") and lead.get("company_name"):
            query["first_name"] = lead["first_name"]
            query["last_name"] = lead["last_name"]
            query["organization_name"] = lead["company_name"]
        queries.append(query)
    
    results = []
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Rate Limiting: 180 requests/min (max 3/sec)
        # We process concurrently with a semaphore to respect rate limits.
        semaphore = asyncio.Semaphore(3) # Max 3 concurrent requests
        
        async def fetch_person(query):
            if not query:
                return {}
            async with semaphore:
                try:
                    response = await client.get(
                        f"{SALESQL_API_BASE}/persons/enrich",
                        headers=headers,
                        params=query
                    )
                    if response.status_code == 429:
                        raise httpx.HTTPStatusError("Rate limit exceeded", request=response.request, response=response)
                    elif response.status_code == 404:
                        log.warning(f"SalesQL returned 404 for query {query} - person not found.")
                        return {}

                    
                    response.raise_for_status()
                    return response.json()
                except Exception as e:
                    log.warning(f"SalesQL request failed for query {query}: {e}")
                    return {}
                finally:
                    # Enforce the ~333ms delay between calls globally by holding the semaphore
                    await asyncio.sleep(0.35)
                    
        tasks = [fetch_person(q) for q in queries]
        results = await asyncio.gather(*tasks)

    return results
