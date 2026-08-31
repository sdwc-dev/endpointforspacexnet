"""
app/services/enrichment.py — Lead enrichment worker using SalesQL and Perplexity Grounding.

Processes a batch of leads from Google Cloud Tasks, updates Firestore atomically,
and handles progress/completion callbacks to the ERP.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from google.cloud import firestore

from app.api.schemas.requests import LeadRecord
from app.db.firebase import get_firestore
from app.services.salesql.client import bulk_research_leads
from app.services.perplexity_client import bulk_enrich_companies_async
from app.services.callback import (
    send_progress_callback,
    send_completion_callback,
    send_failure_callback,
)
from app.utils.logging import get_logger
from app.config import settings

log = get_logger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def process_batch_leads(
    job_id: str,
    leads: list[LeadRecord],
    callback_url: str,
    auth_key: str,
    file_key: str,
) -> None:
    """
    Process a batch of leads using SalesQL API and Perplexity Real-Time Web Search Grounding.
    """
    db = get_firestore()
    job_ref = db.collection("enrichment_jobs").document(job_id)

    log.info("Processing batch of leads", job_id=job_id, batch_size=len(leads))
    
    # ----------------------------
    # Phase 1: SalesQL for Email & Designation
    # ----------------------------
    salesql_results = await bulk_research_leads([lead.model_dump() for lead in leads])
    
    # Intermediate state tracking
    processed_leads_data = []
    unique_companies = {}
    
    for lead, result in zip(leads, salesql_results):
        original_dump = lead.model_dump()
        enriched_data = {}
        
        # Extract data from SalesQL response
        emails = result.get("emails", [])
        valid_email = None
        for em in emails:
            if em.get("type", "").lower() == "work" and em.get("status", "").lower() != "invalid":
                valid_email = em.get("email")
                break
        if not valid_email and emails:
            valid_email = emails[0].get("email")
            
        phones = result.get("phones", [])
        valid_phone = phones[0].get("phone") if phones else None
        
        if valid_email:
            enriched_data["email"] = valid_email
        if valid_phone:
            enriched_data["phone_number"] = valid_phone
            
        if result.get("headline") or result.get("job_title"):
            enriched_data["designation"] = result.get("job_title") or result.get("headline")
            
        # Add to intermediate list
        processed_leads_data.append({
            "lead": lead,
            "original_data": original_dump,
            "enriched_data": enriched_data
        })
        
        # Check what's missing for Perplexity
        comp_name = original_dump.get("company_name")
        if not comp_name or str(comp_name).strip() == "" or str(comp_name).lower() == "nan":
            continue
            
        comp_name = str(comp_name).strip()
        
        if comp_name not in unique_companies:
            unique_companies[comp_name] = {
                "Company Name": comp_name,
                "missing_fields": set()
            }
            
        unique_companies[comp_name]["missing_fields"].add("City")
        unique_companies[comp_name]["missing_fields"].add("Country")
        unique_companies[comp_name]["missing_fields"].add("Industry")
        if not valid_phone:
            unique_companies[comp_name]["missing_fields"].add("Contact Phone Number")
            
    # ----------------------------
    # Phase 2: Perplexity Grounding for Company Info
    # ----------------------------
    companies_to_enrich = []
    for comp, data in unique_companies.items():
        if data["missing_fields"]:
            companies_to_enrich.append((comp, data, list(data["missing_fields"])))
            
    perplexity_results = {}
    perplexity_keys = settings.perplexity_api_keys
    if companies_to_enrich and perplexity_keys:
        perplexity_results = await bulk_enrich_companies_async(
            companies_to_enrich=companies_to_enrich,
            api_keys=perplexity_keys,
            model_name=settings.perplexity_model,
        )
        
    # ----------------------------
    # Phase 3: Merge and Save to Firestore
    # ----------------------------
    success_count = 0
    failed_count = 0
    total_confidence = 0
    batch = db.batch()
    
    for item in processed_leads_data:
        lead = item["lead"]
        original = item["original_data"]
        enriched = item["enriched_data"]
        citations = []
        
        try:
            doc_id = f"{job_id}_{lead.id}"
            result_ref = db.collection("lead_result").document(doc_id)
            
            # Merge Perplexity data if available
            comp_name = str(original.get("company_name", "")).strip()
            if comp_name in perplexity_results:
                p_data = perplexity_results[comp_name]
                if p_data.get("City"):
                    enriched["city"] = p_data.get("City")
                if p_data.get("Country"):
                    enriched["country"] = p_data.get("Country")
                if p_data.get("Industry"):
                    enriched["industry"] = p_data.get("Industry")
                if not enriched.get("phone_number") and p_data.get("Contact Phone Number"):
                    enriched["phone_number"] = p_data.get("Contact Phone Number")
                citations = p_data.get("_citations", [])
                    
            # Calculate Dynamic Confidence Score
            confidence = 0
            if enriched.get("email"):
                confidence += 50
                if enriched.get("phone_number"):
                    confidence += 20
                if enriched.get("city") or enriched.get("country"):
                    confidence += 15
                if enriched.get("industry"):
                    confidence += 15
                    
            payload = {
                "job_id": job_id,
                "lead_id": lead.id,
                "original_data": original,
                "enriched_data": enriched,
                "confidence": confidence,
                "citations": citations,
                "status": "enriched",
                "processed_at": _utcnow_iso(),
            }
            batch.set(result_ref, payload)
            success_count += 1
            total_confidence += confidence
        except Exception as exc:
            log.warning("Failed to map lead", job_id=job_id, lead_id=lead.id, error=str(exc))
            failed_count += 1
            batch.set(db.collection("lead_result").document(f"{job_id}_{lead.id}"), {
                "job_id": job_id,
                "lead_id": lead.id,
                "original_data": original,
                "enriched_data": {},
                "confidence": 0,
                "citations": [],
                "status": "failed",
                "error": str(exc),
                "processed_at": _utcnow_iso(),
            })

    # Commit all result documents in a batch
    await batch.commit()

    # Atomically update the job document counters
    updates = {
        "processed_leads": firestore.Increment(len(leads)),
        "updated_leads": firestore.Increment(success_count),
        "failed_leads": firestore.Increment(failed_count),
        "status": "researching",  
    }
    await job_ref.update(updates)
    
    # Check progress/completion
    job_snap = await job_ref.get()
    if not job_snap.exists:
        return
        
    job_data = job_snap.to_dict()
    total = job_data.get("total_leads", 1)
    processed = job_data.get("processed_leads", 0)
    updated = job_data.get("updated_leads", 0)
    failed = job_data.get("failed_leads", 0)
    
    progress_pct = int((processed / total) * 100)
    last_callback_pct = job_data.get("last_callback_pct", 0)
    
    if progress_pct >= last_callback_pct + 10 and processed < total:
        await job_ref.update({"last_callback_pct": progress_pct})
        await send_progress_callback(
            callback_url=callback_url,
            auth_key=auth_key,
            file_key=file_key,
            progress=progress_pct,
            remarks=f"Processed {processed}/{total} leads",
        )
        
    if processed >= total:
        if job_data.get("status") != "completed":
            
            results_query = db.collection("lead_result").where("job_id", "==", job_id)
            results_docs = await results_query.get()
            
            enriched_leads = []
            overall_conf = 0
            for doc in results_docs:
                d = doc.to_dict()
                conf = d.get("confidence", 0)
                overall_conf += conf
                enriched_leads.append({
                    **d.get("original_data", {}),
                    **d.get("enriched_data", {}),
                    "_confidence": conf,
                    "_citations": d.get("citations", []),
                })
                
            avg_confidence = int(overall_conf / len(enriched_leads)) if enriched_leads else 0
            
            await job_ref.update({
                "status": "completed",
                "avg_confidence": avg_confidence, 
                "completed_at": _utcnow_iso(),
            })
                
            stats = {
                "total": total,
                "updated": updated,
                "failed": failed,
                "avg_confidence": avg_confidence,
            }
            
            log.info("Job fully completed, sending callback", job_id=job_id, stats=stats)
            await send_completion_callback(
                callback_url=callback_url,
                auth_key=auth_key,
                file_key=file_key,
                enriched_leads=enriched_leads,
                stats=stats,
            )
