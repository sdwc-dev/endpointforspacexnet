import streamlit as st
import pandas as pd
import asyncio
import io
import sys
import os
import time
import json
import itertools
from pathlib import Path
import httpx

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from app.services.salesql.client import bulk_research_leads
from app.services.perplexity_client import (
    load_industries,
    process_company_with_perplexity,
    INDUSTRY_LIST,
)
from dotenv import load_dotenv

load_dotenv(override=True)


async def process_leads(
    df: pd.DataFrame,
    industry_list: list[str],
    mode: str,
    api_keys: list[str],
    model_name: str,
    progress_bar=None,
    status_text=None,
):
    # Ensure target columns exist and are object type
    for col in ["Email", "Phone Number", "Company Name", "Country", "City", "Industry", "Designation"]:
        if col not in df.columns:
            df[col] = pd.NA
        df[col] = df[col].astype(object)

    # ----------------------------
    # Phase 1: SalesQL for Email & Designation
    # ----------------------------
    queries = []
    for _, row in df.iterrows():
        query = {
            "first_name": row.get("First Name", ""),
            "last_name": row.get("Last Name", ""),
            "company_name": row.get("Company Name", ""),
            "email": row.get("Email", ""),
        }
        query = {k: ("" if pd.isna(v) else str(v)) for k, v in query.items()}
        queries.append(query)

    results = []
    if mode == "Bulk Enrichment":
        if status_text:
            status_text.text(f"Querying SalesQL in bulk for {len(queries)} leads...")
        results = await bulk_research_leads(queries)
        if progress_bar:
            progress_bar.progress(0.5)
    else:
        total = len(queries)
        for i, query in enumerate(queries):
            if status_text:
                status_text.text(f"Querying SalesQL lead {i+1} of {total}...")
            res = await bulk_research_leads([query])
            results.extend(res)
            if progress_bar:
                progress_bar.progress(0.5 * (i + 1) / total)

    # Update DataFrame with SalesQL results
    for i, result in enumerate(results):
        if not result:
            continue

        # Email
        emails = result.get("emails", [])
        valid_email = next(
            (
                em.get("email")
                for em in emails
                if em.get("type", "").lower() == "work" and em.get("status", "").lower() != "invalid"
            ),
            None,
        )
        if not valid_email and emails:
            valid_email = emails[0].get("email")
        if valid_email:
            df.at[i, "Email"] = valid_email

        # Phone (Fallback mapping if available in SalesQL, but Perplexity will search if missing)
        phones = result.get("phones", [])
        if phones and phones[0].get("phone"):
            df.at[i, "Phone Number"] = phones[0].get("phone")

        # Designation
        job_title = result.get("job_title") or result.get("headline")
        if job_title:
            df.at[i, "Designation"] = job_title

    # ----------------------------
    # Phase 2: Perplexity Grounding for Company Info
    # ----------------------------
    if not api_keys:
        if status_text:
            status_text.text("No Perplexity API keys found. Skipping company enrichment...")
        return df

    if status_text:
        status_text.text("Preparing Perplexity search grounding for unique companies...")

    unique_companies = {}
    for index, row in df.iterrows():
        comp = str(row.get("Company Name", "")).strip()
        if pd.isna(row.get("Company Name")) or not comp or comp.lower() == "nan":
            continue

        if comp not in unique_companies:
            unique_companies[comp] = {
                "Company Name": comp,
                "missing_fields": set(),
            }

        # Determine what is missing for this company
        if pd.isna(row.get("City")) or str(row.get("City")).strip() == "":
            unique_companies[comp]["missing_fields"].add("City")
        if pd.isna(row.get("Country")) or str(row.get("Country")).strip() == "":
            unique_companies[comp]["missing_fields"].add("Country")
        if pd.isna(row.get("Industry")) or str(row.get("Industry")).strip() == "":
            unique_companies[comp]["missing_fields"].add("Industry")
        if pd.isna(row.get("Phone Number")) or str(row.get("Phone Number")).strip() == "":
            unique_companies[comp]["missing_fields"].add("Contact Phone Number")

    companies_to_enrich = []
    for comp, data in unique_companies.items():
        if data["missing_fields"]:
            companies_to_enrich.append((comp, data, list(data["missing_fields"])))

    if not companies_to_enrich:
        if status_text:
            status_text.text("No companies need Perplexity enrichment.")
        return df

    key_iterator = itertools.cycle(api_keys)
    results_cache = {}
    total_companies = len(companies_to_enrich)
    completed = 0

    if status_text:
        status_text.text(f"Perplexity grounding {total_companies} companies concurrently using {len(api_keys)} keys...")

    semaphore = asyncio.Semaphore(len(api_keys) * 4)

    async with httpx.AsyncClient(timeout=35.0) as client:

        async def worker(comp_info):
            nonlocal completed
            comp, data, missing = comp_info
            api_key = next(key_iterator)
            async with semaphore:
                result, citations, success = await process_company_with_perplexity(
                    client=client,
                    api_key=api_key,
                    model_name=model_name,
                    data=data,
                    missing_fields=missing,
                )
                completed += 1
                if progress_bar:
                    progress_bar.progress(0.5 + (0.5 * completed / total_companies))
                return comp, result, success

        tasks = [worker(info) for info in companies_to_enrich]
        batch_res = await asyncio.gather(*tasks, return_exceptions=True)

        for item in batch_res:
            if isinstance(item, tuple) and item[1]:
                comp, res, success = item
                if success and res:
                    results_cache[comp] = res

    if status_text:
        status_text.text("Applying Perplexity results to dataset...")

    # ----------------------------
    # Phase 3: Merge Perplexity Results
    # ----------------------------
    for index, row in df.iterrows():
        comp = str(row.get("Company Name", "")).strip()
        if comp in results_cache:
            c_data = results_cache[comp]

            if pd.isna(row.get("City")) and c_data.get("City"):
                df.at[index, "City"] = c_data.get("City")
            if pd.isna(row.get("Country")) and c_data.get("Country"):
                df.at[index, "Country"] = c_data.get("Country")
            if pd.isna(row.get("Industry")) and c_data.get("Industry"):
                df.at[index, "Industry"] = c_data.get("Industry")
            if pd.isna(row.get("Phone Number")) and c_data.get("Contact Phone Number"):
                df.at[index, "Phone Number"] = c_data.get("Contact Phone Number")

    return df


st.set_page_config(page_title="AI Lead Enrichment Tool (Perplexity Sonar)", layout="wide")

# Sidebar Configuration
with st.sidebar:
    st.header("Configuration")
    api_keys = []
    for k, v in os.environ.items():
        if k.upper().startswith("PERPLEXITY_API_KEY") and v.strip():
            api_keys.append(v.strip())

    api_keys = list(dict.fromkeys(api_keys))
    if api_keys:
        st.success(f"Detected {len(api_keys)} Perplexity API Key(s) for Parallel Processing")
    else:
        st.error("No PERPLEXITY_API_KEY found in .env file.")

    model_options = [
        "sonar",
        "sonar-pro",
        "sonar-reasoning",
    ]
    selected_model = st.selectbox("Select Perplexity Model", model_options, index=0)

st.title("AI Lead Enrichment Tool")
st.write(
    "Upload the `market_lead_sample_format.xlsx` file. Missing personal info (Email, Designation) will be enriched via **SalesQL**, "
    "and company info (City, Country, Industry, Phone) will be enriched via **Perplexity Sonar Search Grounding**."
)

uploaded_file = st.file_uploader("Upload Excel File", type=["xlsx"])

if uploaded_file is not None:
    try:
        df = pd.read_excel(uploaded_file)
        st.subheader("Original Data Preview")
        st.dataframe(df.head())

        enrichment_mode = st.radio(
            "SalesQL Enrichment Mode:",
            ["Bulk Enrichment", "Single Enrichment"],
            help="Bulk is faster. Single processes one by one.",
        )

        if st.button("Enrich Data"):
            industry_list = load_industries()

            with st.spinner("Enriching leads with SalesQL & Perplexity Sonar... Please wait."):
                progress_bar = st.progress(0)
                status_text = st.empty()
                enriched_df = asyncio.run(
                    process_leads(
                        df.copy(),
                        industry_list,
                        enrichment_mode,
                        api_keys,
                        selected_model,
                        progress_bar,
                        status_text,
                    )
                )

            st.success("Enrichment complete!")
            st.subheader("Enriched Data Preview")
            st.dataframe(enriched_df.head())

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                enriched_df.to_excel(writer, index=False)
            output.seek(0)

            st.download_button(
                label="📥 Download Enriched Excel",
                data=output,
                file_name="enriched_leads.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    except Exception as e:
        st.error(f"Error processing file: {e}")
