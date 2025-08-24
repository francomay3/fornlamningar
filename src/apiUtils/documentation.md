# K-samsök API Documentation

This document provides information about the K-samsök API for accessing Swedish cultural heritage data, based on successful enrichment of 1,491 archaeological sites.

## API Endpoints

### Base URL
- **Base URL**: `https://kulturarvsdata.se`

### Main API Endpoint
- **API Endpoint**: `/ksamsok/api`
- **Method**: GET
- **Parameters**: Various search and retrieval parameters

### Direct Site Access
- **Direct Site Endpoint**: `/raa/lamning/{UUID}`
- **Method**: GET
- **Description**: Direct access to archaeological site data using UUID

### Direct Documentation Access
- **Direct Documentation Endpoint**: `/raa/dokumentation/{doc_id}`
- **Method**: GET
- **Description**: Direct access to documentation records

## Search Methods

### 1. Direct UUID Access (Recommended)
- **Endpoint**: `https://kulturarvsdata.se/raa/lamning/{UUID}`
- **Method**: GET
- **Description**: Most reliable method for archaeological sites
- **Success Rate**: 100% for valid UUIDs
- **Example**: `https://kulturarvsdata.se/raa/lamning/173cca58-cfc5-4420-ae32-9acfdfc42543`

### 2. Get Relations (Fallback Method)
- **Parameter**: `method=getRelations`
- **Parameters**:
  - `relation`: Type of relation to search for (use "isDescribedBy")
  - `objectId`: The object to find relations for (format: "raa/lamning/{UUID}")
  - `maxCount`: Maximum number of results (recommend 5)
  - `inferSameAs`: Whether to infer same-as relations (use "yes")
- **Description**: Used when direct access fails, finds related documentation
- **Example**: `objectId=raa/lamning/173cca58-cfc5-4420-ae32-9acfdfc42543&relation=isDescribedBy`

### 3. Search by Text (Limited Use)
- **Parameter**: `text`
- **Example**: `text=fornlämning`
- **Description**: Less reliable for specific site identification

### 4. Search by Item ID (Not Recommended)
- **Parameter**: `itemId`
- **Example**: `itemId=*L1966:5300-1*`
- **Description**: Often returns 0 results for archaeological sites

## Response Format

The API returns JSON-LD format responses containing structured data within an `@graph` array.

### Response Structure
```json
{
  "@context": {...},
  "@graph": [
    {
      "@id": "http://kulturarvsdata.se/raa/lamning/{UUID}",
      "@type": "EntityType#monument",
      "itemLabel": "Human-readable site name",
      "itemType": "EntityType#monument",
      "itemKeyword": [
        {"@value": "Keyword1"},
        {"@value": "Keyword2"}
      ],
      "itemTitle": "Official site title",
      "dataQuality": "quality_indicator"
    }
  ]
}
```

### Key Findings from Enrichment
- **Main Entity**: The primary archaeological site is always the first entity in `@graph` with `@id` starting with `http://kulturarvsdata.se/raa/lamning/`
- **Documentation Entity**: When using getRelations, the documentation entity has `@id` starting with `http://kulturarvsdata.se/raa/dokumentation/`
- **Keywords**: Often stored as objects with `@value` property rather than plain strings
- **Data Coverage**: 100% success rate for core fields (itemLabel, itemType, itemTitle, dataQuality)
- **Keyword Coverage**: Only 7.6% of sites have keywords (114 out of 1,491 sites)

## Usage Examples

### Direct Site Access
```bash
curl "https://kulturarvsdata.se/raa/lamning/173cca58-cfc5-4420-ae32-9acfdfc42543"
```

### Get Relations (Fallback)
```bash
curl "https://kulturarvsdata.se/ksamsok/api?method=getRelations&relation=isDescribedBy&objectId=raa/lamning/173cca58-cfc5-4420-ae32-9acfdfc42543&maxCount=5&inferSameAs=yes"
```

### Direct Documentation Access
```bash
curl "https://kulturarvsdata.se/raa/dokumentation/{doc_id}"
```

## Rate Limiting

Based on successful enrichment of 1,491 sites:
- **Recommended Rate**: 5 requests per second
- **Delay Between Requests**: 0.2 seconds minimum
- **Total Processing Time**: ~6-7 minutes for 1,491 sites
- **Success Rate**: 100% with proper rate limiting

## Error Handling

Common HTTP status codes:
- **200**: Success
- **400**: Bad Request (common with invalid search parameters)
- **404**: Not Found (site doesn't exist or access denied)
- **429**: Too Many Requests (rate limit exceeded)
- **500**: Internal Server Error

### Recommended Error Handling Strategy
1. Try direct UUID access first
2. If 404, use getRelations to find documentation
3. If getRelations succeeds, fetch documentation details
4. Implement exponential backoff for rate limit errors
5. Log failed requests for analysis

## Data Quality Insights

From the enrichment process:
- **itemLabel**: Available for 100% of sites
- **itemType**: Available for 100% of sites (typically "EntityType#monument")
- **itemKeyword**: Available for 7.6% of sites
- **itemTitle**: Available for 100% of sites
- **dataQuality**: Available for 100% of sites
- **thumbnail**: Not available (0% coverage)
- **placeName**: Not available (0% coverage)

## Best Practices

1. **Use UUIDs**: Always use UUIDs from the database for reliable access
2. **Implement Fallback**: Use getRelations when direct access fails
3. **Parse @graph**: Always look for the main entity in the `@graph` array
4. **Handle Keywords**: Keywords may be objects with `@value` property
5. **Rate Limiting**: Use conservative rate limiting (5 req/sec)
6. **Error Recovery**: Implement retry logic with exponential backoff

## Code Examples

### Python Example with Direct UUID Access
```python
import requests
import json
import time

def get_site_data(uuid):
    """Get archaeological site data using direct UUID access."""
    url = f"https://kulturarvsdata.se/raa/lamning/{uuid}"
    
    try:
        response = requests.get(url, headers={"Accept": "application/json"})
        response.raise_for_status()
        
        data = response.json()
        
        # Find the main entity in @graph
        main_entity = None
        for entity in data.get("@graph", []):
            if entity.get("@id", "").startswith("http://kulturarvsdata.se/raa/lamning/"):
                main_entity = entity
                break
        
        if main_entity:
            return {
                "itemLabel": main_entity.get("itemLabel", "No label"),
                "itemType": main_entity.get("itemType", "No type"),
                "itemTitle": main_entity.get("itemTitle", "No title"),
                "dataQuality": main_entity.get("dataQuality", "No quality"),
                "itemKeyword": main_entity.get("itemKeyword", [])
            }
        
        return None
        
    except requests.exceptions.RequestException as e:
        print(f"Error accessing {uuid}: {e}")
        return None

def get_site_data_with_fallback(uuid):
    """Get site data with fallback to getRelations."""
    # Try direct access first
    data = get_site_data(uuid)
    if data:
        return data
    
    # Fallback to getRelations
    url = "https://kulturarvsdata.se/ksamsok/api"
    params = {
        "method": "getRelations",
        "relation": "isDescribedBy",
        "objectId": f"raa/lamning/{uuid}",
        "maxCount": 5,
        "inferSameAs": "yes"
    }
    
    try:
        response = requests.get(url, params=params, headers={"Accept": "application/json"})
        response.raise_for_status()
        
        relations_data = response.json()
        relations = relations_data.get("result", {}).get("relations", {}).get("relation", [])
        
        if relations:
            # Get the first documentation URI
            doc_uri = relations[0]["content"]
            doc_id = doc_uri.split("/")[-1]
            
            # Fetch documentation details
            doc_url = f"https://kulturarvsdata.se/raa/dokumentation/{doc_id}"
            doc_response = requests.get(doc_url, headers={"Accept": "application/json"})
            doc_response.raise_for_status()
            
            doc_data = doc_response.json()
            
            # Find the documentation entity
            doc_entity = None
            for entity in doc_data.get("@graph", []):
                if entity.get("@id", "").startswith("http://kulturarvsdata.se/raa/dokumentation/"):
                    doc_entity = entity
                    break
            
            if doc_entity:
                return {
                    "itemLabel": doc_entity.get("itemLabel", "No label"),
                    "itemType": doc_entity.get("itemType", "No type"),
                    "itemTitle": doc_entity.get("itemTitle", "No title"),
                    "dataQuality": doc_entity.get("dataQuality", "No quality"),
                    "itemKeyword": doc_entity.get("itemKeyword", [])
                }
        
        return None
        
    except requests.exceptions.RequestException as e:
        print(f"Error in fallback for {uuid}: {e}")
        return None

# Example usage with rate limiting
def enrich_sites(uuid_list, delay=0.2):
    """Enrich multiple sites with rate limiting."""
    results = []
    
    for i, uuid in enumerate(uuid_list):
        print(f"Processing {i+1}/{len(uuid_list)}: {uuid}")
        
        data = get_site_data_with_fallback(uuid)
        if data:
            results.append({"uuid": uuid, "data": data})
        
        # Rate limiting
        time.sleep(delay)
    
    return results
```

### Rate-Limited API Client
```python
import requests
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any

@dataclass
class APIConfig:
    base_url: str = "https://kulturarvsdata.se"
    rate_limit: int = 5  # requests per second
    headers: Dict[str, str] = None
    
    def __post_init__(self):
        if self.headers is None:
            self.headers = {
                'User-Agent': 'Fornlamningar-Enrichment/1.0',
                'Accept': 'application/json'
            }

class RateLimitedAPI:
    def __init__(self, config: APIConfig):
        self.config = config
        self.last_request_time = 0
    
    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        """Make a rate-limited GET request."""
        # Rate limiting
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        min_interval = 1.0 / self.config.rate_limit
        
        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            time.sleep(sleep_time)
        
        url = f"{self.config.base_url}{endpoint}"
        response = requests.get(url, params=params, headers=self.config.headers)
        
        self.last_request_time = time.time()
        return response
```

## Legacy Information

The original K-samsök API documentation included many features that are less relevant for archaeological site enrichment:

- **Text Search**: Less reliable for specific site identification
- **Geographic Search**: Useful for finding sites in specific areas
- **Image Search**: Limited availability for archaeological sites
- **UGC Links**: User-generated content links
- **Complex Queries**: CQL-based advanced searches

For archaeological site enrichment, the direct UUID access method is the most reliable and efficient approach.