"""
app/api/schemas/requests.py — Pydantic request models for incoming ERP payloads.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class LeadRecord(BaseModel):
    """A single market lead record as received from the Specxnet ERP."""

    id: str = Field(..., description="Unique lead ID from the ERP")
    first_name: str = Field(..., alias="firstName")
    last_name: str = Field(..., alias="lastName")
    phone_number: Optional[str] = Field(default=None, alias="phoneNumber")
    designation: Optional[str] = Field(default=None)
    company_name: Optional[str] = Field(default=None, alias="companyName")   # Optional — inferred from email domain if missing
    parent_company: Optional[str] = Field(default=None, alias="parentCompany")
    company_type: Optional[str] = Field(default=None, alias="companyType")
    email: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    source: Optional[str] = None
    opportunity_type: Optional[str] = Field(default=None, alias="opportunityType")
    comments: Optional[str] = None
    project_type: Optional[str] = Field(default=None, alias="projectType")

    class Config:
        populate_by_name = True


class LeadsData(BaseModel):
    leads: List[LeadRecord]


class EnrichRequest(BaseModel):
    """Top-level ERP request body for lead enrichment."""
    data: LeadsData
    callback_url: str = Field(..., description="URL the ERP expects callbacks on")
    auth_key: str = Field(..., description="Auth key echoed back in every callback")
    file_key: str = Field(..., description="File key echoed back in every callback")
    request_id: str = Field(..., description="Unique request ID from the ERP")
    expires_at: datetime = Field(..., description="ISO 8601 expiry — rejected if already past")
