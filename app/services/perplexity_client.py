"""
app/services/perplexity_client.py — Perplexity API client with search grounding & multi-key pool.
"""
import json
import asyncio
import itertools
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

import httpx

from app.utils.logging import get_logger

log = get_logger(__name__)

project_root = Path(__file__).resolve().parent.parent.parent

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"


def load_industries() -> List[str]:
    industries_path = project_root / "Industries list (1).txt"
    try:
        with open(industries_path, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except Exception as e:
        log.warning("Could not load Industries list, falling back to 'Other'", error=str(e))
        return ["Other"]


INDUSTRY_LIST = load_industries()


def construct_company_prompt(data: Dict[str, str], missing_fields: List[str]) -> str:
    company = data.get("Company Name", "Unknown Company")
    prompt = (
        f"You are an expert data researcher. Search the web for verified contact and company information for this company.\n\n"
        f"Company: {company}\n"
    )

    prompt += "\nCRITICAL STRICT RULES:\n"
    prompt += "1. You MUST use your real-time web search to find accurate, up-to-date information.\n"
    prompt += "2. DO NOT hallucinate a phone number. If a real company phone number is not found in search results, return null.\n"
    prompt += (
        f"3. For Industry, you must pick EXACTLY one from this list: {', '.join(INDUSTRY_LIST)}. "
        "If none fit perfectly, return 'Other'.\n\n"
    )

    prompt += "Fields to find:\n"
    for field in missing_fields:
        prompt += f"- {field}\n"

    prompt += (
        "\nReturn the result ONLY as a valid JSON object with the exact keys representing the fields you were asked for.\n"
        "Do not wrap the response in markdown blocks like ```json. Return pure JSON only.\n"
    )

    return prompt.strip()


def parse_json_response(content: str) -> Optional[Dict[str, Any]]:
    """Clean markdown markers and parse JSON safely."""
    text = content.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try extracting JSON between first '{' and last '}'
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                pass
        return None


async def process_company_with_perplexity(
    client: httpx.AsyncClient,
    api_key: str,
    model_name: str,
    data: Dict[str, str],
    missing_fields: List[str],
    max_retries: int = 3,
) -> Tuple[Optional[Dict[str, Any]], List[str], bool]:
    """
    Query Perplexity Sonar for company details with real-time web grounding.
    Returns: (parsed_data_dict, citations_list, success_bool)
    """
    prompt = construct_company_prompt(data, missing_fields)
    company_name = data.get("Company Name", "Unknown")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a professional B2B company research assistant with live web search capabilities. "
                    "Always conduct real-time web search to verify company facts and return ONLY valid JSON."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.1,
        "max_tokens": 1000,
        "return_citations": True,
    }

    for attempt in range(max_retries):
        try:
            response = await client.post(
                PERPLEXITY_API_URL,
                headers=headers,
                json=payload,
                timeout=30.0,
            )

            if response.status_code == 429:
                wait_time = 2 * (attempt + 1)
                log.warning("Perplexity rate limit (429), backing off", company=company_name, wait=wait_time)
                await asyncio.sleep(wait_time)
                continue

            response.raise_for_status()
            res_json = response.json()

            # Extract message content & citations
            choices = res_json.get("choices", [])
            if not choices:
                continue

            content = choices[0].get("message", {}).get("content", "")
            citations = res_json.get("citations", [])

            parsed = parse_json_response(content)
            if parsed:
                # Include citations inside parsed dictionary if helpful
                parsed["_citations"] = citations
                return parsed, citations, True

        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(2 * (attempt + 1))
                continue
            log.warning("Perplexity query failed after retries", company=company_name, error=str(e))
            return None, [], False

    return None, [], False


async def bulk_enrich_companies_async(
    companies_to_enrich: List[Tuple[str, Dict[str, Any], List[str]]],
    api_keys: List[str],
    model_name: str = "sonar",
    concurrency_per_key: int = 5,
) -> Dict[str, Any]:
    """
    Asynchronously enrich unique companies using Perplexity Sonar search grounding
    with a pool of Perplexity API keys rotated round-robin.
    """
    if not api_keys or not companies_to_enrich:
        return {}

    key_cycle = itertools.cycle(api_keys)
    results_cache: Dict[str, Any] = {}
    total_concurrency = len(api_keys) * concurrency_per_key
    semaphore = asyncio.Semaphore(total_concurrency)

    log.info(
        "Starting Perplexity batch grounding",
        total_companies=len(companies_to_enrich),
        key_count=len(api_keys),
        model=model_name,
        max_concurrency=total_concurrency,
    )

    async with httpx.AsyncClient(
        limits=httpx.Limits(max_keepalive_connections=total_concurrency, max_connections=total_concurrency + 10),
        timeout=35.0,
    ) as client:

        async def worker(comp_info: Tuple[str, Dict[str, Any], List[str]]):
            comp, data, missing = comp_info
            api_key = next(key_cycle)
            async with semaphore:
                parsed_res, citations, success = await process_company_with_perplexity(
                    client=client,
                    api_key=api_key,
                    model_name=model_name,
                    data=data,
                    missing_fields=missing,
                )
                if success and parsed_res:
                    return comp, parsed_res
                return comp, None

        tasks = [worker(info) for info in companies_to_enrich]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for item in results:
            if isinstance(item, tuple) and item[1]:
                comp, res = item
                results_cache[comp] = res

    log.info("Perplexity batch grounding completed", enriched_count=len(results_cache))
    return results_cache


def bulk_enrich_companies(
    companies_to_enrich: List[Tuple[str, Dict[str, Any], List[str]]],
    api_keys: List[str],
    model_name: str = "sonar",
) -> Dict[str, Any]:
    """
    Synchronous wrapper for bulk_enrich_companies_async.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Running inside an active loop (e.g. FastAPI / asyncio event loop)
        # Use an executor or nested runner if necessary, or call async directly
        import nest_asyncio  # in case needed
        try:
            nest_asyncio.apply()
            return loop.run_until_complete(
                bulk_enrich_companies_async(companies_to_enrich, api_keys, model_name)
            )
        except Exception:
            # Create a thread to run the loop
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    asyncio.run,
                    bulk_enrich_companies_async(companies_to_enrich, api_keys, model_name),
                )
                return future.result()
    else:
        return asyncio.run(
            bulk_enrich_companies_async(companies_to_enrich, api_keys, model_name)
        )
