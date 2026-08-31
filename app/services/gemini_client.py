import json
import time
import itertools
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Any

from google import genai
from google.genai import types

from app.utils.logging import get_logger

log = get_logger(__name__)

project_root = Path(__file__).resolve().parent.parent.parent

def load_industries() -> List[str]:
    industries_path = project_root / "Industries list (1).txt"
    try:
        with open(industries_path, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except Exception as e:
        log.warning("Could not load Industries list, falling back to 'Other'")
        return ["Other"]

INDUSTRY_LIST = load_industries()

def construct_company_prompt(data: Dict[str, str], missing_fields: List[str]) -> str:
    company = data.get("Company Name", "Unknown Company")
    prompt = f"You are an expert data researcher. Search Google for contact information for this company.\n\n"
    prompt += f"Company: {company}\n"
    
    prompt += "\nCRITICAL STRICT RULES:\n"
    prompt += "1. You MUST use the Google Search tool to find this information.\n"
    prompt += "2. DO NOT hallucinate a phone number. If a real phone number is not found in search results, return null.\n"
    prompt += f"3. For Industry, you must pick EXACTLY one from this list: {', '.join(INDUSTRY_LIST)}. If none fit perfectly, return 'Other'.\n\n"
    
    prompt += "Fields to find:\n"
    for field in missing_fields:
        prompt += f"- {field}\n"
        
    prompt += "\nReturn the result ONLY as a valid JSON object with the exact keys representing the fields you were asked for.\n"
    prompt += "Do not wrap the response in markdown blocks like ```json. Return pure JSON.\n"
        
    return prompt.strip()

def process_company_with_gemini(client: genai.Client, model_name: str, data: Dict[str, str], missing_fields: List[str]):
    prompt = construct_company_prompt(data, missing_fields)
        
    config = types.GenerateContentConfig(
        tools=[{"google_search": {}}]
    )

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config
            )
            content = response.text.strip()
            
            if content.startswith("```json"): content = content[7:]
            if content.startswith("```"): content = content[3:]
            if content.endswith("```"): content = content[:-3]
                
            return json.loads(content.strip()), True
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            log.warning("Gemini failed after 3 attempts", error=str(e), company=data.get("Company Name"))
            return None, False
    return None, False

def bulk_enrich_companies(companies_to_enrich: List[tuple], api_keys: List[str], model_name: str = "gemini-2.5-flash") -> Dict[str, Any]:
    """
    Enrich unique companies using Google Search Grounding with a pool of Gemini API keys.
    companies_to_enrich should be a list of tuples: (company_name, data_dict, missing_fields_list)
    Returns a dict mapping company_name to the found data dict.
    """
    if not api_keys or not companies_to_enrich:
        return {}

    client_pool = [(genai.Client(api_key=key), f"{key[:5]}...{key[-5:]}") for key in api_keys]
    client_iterator = itertools.cycle(client_pool)
    lock = threading.Lock()
    
    def get_next_client():
        with lock:
            return next(client_iterator)
            
    results_cache = {}
    
    def worker(comp_info):
        comp, data, missing = comp_info
        client, key_mask = get_next_client()
        result, success = process_company_with_gemini(client, model_name, data, missing)
        return comp, result, success

    log.info("Starting Gemini batch grounding", total_companies=len(companies_to_enrich), key_count=len(api_keys))
    
    with ThreadPoolExecutor(max_workers=len(api_keys) * 4) as executor:
        futures = {executor.submit(worker, info): info for info in companies_to_enrich}
        for future in as_completed(futures):
            comp, result, success = future.result()
            if success and result:
                results_cache[comp] = result

    return results_cache
