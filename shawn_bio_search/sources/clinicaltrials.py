"""ClinicalTrials.gov source module (no API key required)."""

from __future__ import annotations

import urllib.parse
import urllib.request
from typing import Any, Dict, List


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return __import__("json").loads(resp.read().decode("utf-8"))


def fetch_clinicaltrials(query: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch clinical trials from ClinicalTrials.gov."""
    params = {
        "query.term": query,
        "pageSize": str(max(1, min(limit, 100))),
        "fields": "NCTId,ProtocolSection,DerivedSection",
    }
    url = "https://clinicaltrials.gov/api/v2/studies?" + urllib.parse.urlencode(params)
    
    try:
        data = _get_json(url)
    except Exception:
        return []
    
    studies = data.get("studies", [])
    out = []
    
    for study in studies[:limit]:
        protocol = study.get("protocolSection", {})
        identification = protocol.get("identificationModule", {})
        description = protocol.get("descriptionModule", {})
        status = protocol.get("statusModule", {})
        sponsor = protocol.get("sponsorCollaboratorsModule", {})
        
        nct_id = identification.get("nctId", "")
        title = identification.get("briefTitle", "")
        
        brief_summary = description.get("briefSummary", "")
        detailed = description.get("detailedDescription", "")
        abstract = brief_summary or detailed or ""
        
        start_date = status.get("startDateStruct", {}).get("date", "")
        year = int((start_date or "0000")[:4] or 0) if start_date else 0
        
        lead_sponsor = sponsor.get("leadSponsor", {}).get("name", "")
        
        out.append({
            "source": "clinicaltrials",
            "id": nct_id,
            "title": title,
            "authors": [lead_sponsor] if lead_sponsor else [],
            "year": year,
            "doi": None,
            "url": f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else "",
            "abstract": abstract,
            "citations": 0,
        })
    
    return out
