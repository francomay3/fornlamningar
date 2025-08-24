#!/usr/bin/env python3
"""
Script to enrich the filtered archaeological sites database with additional metadata
from the K-samsök API.

This script will:
1. Read the filtered database
2. For each site, query the K-samsök API using the inspireid
3. Extract the planned enrichment fields
4. Add new columns to the database with the enriched data
"""

import sqlite3
import time
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import json
import os
from urllib.parse import quote

# Import our API utilities
from src.apiUtils.api_utils import APIConfig, RateLimitedAPI

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('enrichment.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class EnrichmentData:
    """Data structure for enrichment fields."""
    itemLabel: Optional[str] = None
    itemType: Optional[str] = None
    itemKeyword: Optional[str] = None  # Will be stored as JSON string
    itemTitle: Optional[str] = None
    dataQuality: Optional[str] = None


class DatabaseEnricher:
    """Class to handle database enrichment with K-samsök API data."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.api_config = APIConfig(
            base_url="https://kulturarvsdata.se",
            rate_limit=5,  # Conservative rate limit
            headers={
                'User-Agent': 'Fornlamningar-Enrichment/1.0',
                'Accept': 'application/json'
            }
        )
        self.api = RateLimitedAPI(self.api_config)
        
    def setup_database(self):
        """Add new columns to the database for enrichment data."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Add new columns for enrichment data
        new_columns = [
            "itemLabel TEXT",
            "itemType TEXT", 
            "itemKeyword TEXT",  # JSON string of keywords
            "itemTitle TEXT",
            "dataQuality TEXT"
        ]
        
        for column_def in new_columns:
            column_name = column_def.split()[0]
            try:
                cursor.execute(f"ALTER TABLE fornlamningar ADD COLUMN {column_def}")
                logger.info(f"Added column: {column_name}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e):
                    logger.info(f"Column {column_name} already exists")
                else:
                    logger.error(f"Error adding column {column_name}: {e}")
        
        # Add enrichment metadata
        cursor.execute("""
            INSERT OR REPLACE INTO metadata (key, value) VALUES 
            ('enrichment_date', datetime('now')),
            ('enrichment_source', 'K-samsök API'),
            ('enrichment_fields', 'itemLabel,itemType,itemKeyword,itemTitle,dataQuality')
        """)
        
        conn.commit()
        conn.close()
        logger.info("Database setup completed")
    
    def extract_inspireid_from_uri(self, inspireid: str) -> str:
        """Extract the inspireid part from the full URI or ID."""
        # Handle different formats:
        # - L1966:5300-1 (direct inspireid)
        # - http://kulturarvsdata.se/raa/fmi/L1966:5300-1 (full URI)
        
        if inspireid.startswith('http'):
            # Extract the last part after the last slash
            return inspireid.split('/')[-1]
        else:
            return inspireid
    
    def query_ksamsok_api(self, inspireid: str, uuid: str) -> Optional[Dict[str, Any]]:
        """Query the K-samsök API for a specific archaeological site using UUID."""
        try:
            # First, try to get the archaeological site directly
            site_uri = f"http://kulturarvsdata.se/raa/lamning/{uuid}"
            
            logger.debug(f"Querying direct site URI: {site_uri}")
            response = self.api.get(f"/raa/lamning/{uuid}")
            
            if response.status_code == 200:
                # We got the archaeological site directly
                site_data = response.json()
                logger.debug(f"Found archaeological site directly for UUID: {uuid}")
                return {"type": "site", "data": site_data}
            
            # If direct access fails, try getRelations to find documentation
            logger.debug(f"Direct access failed, trying getRelations for UUID: {uuid}")
            
            params = {
                "method": "getRelations",
                "version": "1.1",
                "relation": "isDescribedBy",  # Look for documentation that describes this site
                "maxCount": "5",
                "inferSameAs": "yes",
                "objectId": f"raa/lamning/{uuid}"
            }
            
            response = self.api.get("/ksamsok/api", params=params)
            
            if response.status_code == 200:
                relations_data = response.json()
                relations_count = relations_data.get("result", {}).get("relations", {}).get("count", 0)
                
                if relations_count > 0:
                    # Get the first documentation URI
                    relations = relations_data["result"]["relations"]["relation"]
                    for relation in relations:
                        if relation.get("type") == "isDescribedBy":
                            doc_uri = relation.get("content")
                            if doc_uri:
                                # Extract the documentation ID from the URI
                                doc_id = doc_uri.split("/")[-1]
                                
                                # Now get the documentation details
                                logger.debug(f"Found documentation: {doc_id}")
                                doc_response = self.api.get(f"/raa/dokumentation/{doc_id}")
                                
                                if doc_response.status_code == 200:
                                    doc_data = doc_response.json()
                                    return {"type": "documentation", "data": doc_data}
                    
                    logger.debug(f"No valid documentation found for UUID: {uuid}")
                    return None
                else:
                    logger.debug(f"No relations found for UUID: {uuid}")
                    return None
            else:
                logger.warning(f"getRelations failed for {uuid}: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error querying API for {inspireid} (UUID: {uuid}): {e}")
            return None
    
    def extract_enrichment_data(self, api_response: Dict[str, Any]) -> EnrichmentData:
        """Extract enrichment data from API response."""
        try:
            response_type = api_response.get("type")
            data = api_response.get("data", {})
            
            # Extract enrichment fields
            enrichment = EnrichmentData()
            
            if response_type == "site":
                # Handle archaeological site data
                # Find the main entity in the @graph array
                graph = data.get("@graph", [])
                main_entity = None
                
                for entity in graph:
                    if isinstance(entity, dict) and entity.get("@id", "").startswith("http://kulturarvsdata.se/raa/lamning/"):
                        main_entity = entity
                        break
                
                if not main_entity:
                    logger.warning("Could not find main entity in site data")
                    return enrichment
                
                # itemLabel
                item_label = main_entity.get("ksam:itemLabel", {})
                if isinstance(item_label, dict):
                    enrichment.itemLabel = item_label.get("@value")
                elif isinstance(item_label, str):
                    enrichment.itemLabel = item_label
                
                # itemType
                item_type = main_entity.get("ksam:itemType", {})
                if isinstance(item_type, dict):
                    type_id = item_type.get("@id", "")
                    # Extract the type name from the URI
                    if "/" in type_id:
                        enrichment.itemType = type_id.split("/")[-1]
                    else:
                        enrichment.itemType = type_id
                elif isinstance(item_type, str):
                    enrichment.itemType = item_type
                
                # itemKeyword (array of keywords)
                item_keywords = main_entity.get("ksam:itemKeyword", [])
                if item_keywords:
                    if isinstance(item_keywords, list):
                        enrichment.itemKeyword = json.dumps(item_keywords, ensure_ascii=False)
                    else:
                        enrichment.itemKeyword = json.dumps([item_keywords], ensure_ascii=False)
                
                # itemTitle (might be the same as itemLabel)
                enrichment.itemTitle = main_entity.get("ksam:itemTitle") or enrichment.itemLabel
                
                # dataQuality
                data_quality = main_entity.get("ksam:dataQuality", {})
                if isinstance(data_quality, dict):
                    quality_id = data_quality.get("@id", "")
                    if "/" in quality_id:
                        enrichment.dataQuality = quality_id.split("/")[-1]
                    else:
                        enrichment.dataQuality = quality_id
                elif isinstance(data_quality, str):
                    enrichment.dataQuality = data_quality
            
            elif response_type == "documentation":
                # Handle documentation data
                # Find the main entity in the @graph array
                graph = data.get("@graph", [])
                main_entity = None
                
                for entity in graph:
                    if isinstance(entity, dict) and entity.get("@id", "").startswith("http://kulturarvsdata.se/raa/dokumentation/"):
                        main_entity = entity
                        break
                
                if not main_entity:
                    logger.warning("Could not find main entity in documentation data")
                    return enrichment
                
                # itemLabel
                item_label = main_entity.get("ksam:itemLabel", {})
                if isinstance(item_label, dict):
                    enrichment.itemLabel = item_label.get("@value")
                elif isinstance(item_label, str):
                    enrichment.itemLabel = item_label
                
                # itemType
                item_type = main_entity.get("ksam:itemType", {})
                if isinstance(item_type, dict):
                    type_id = item_type.get("@id", "")
                    # Extract the type name from the URI
                    if "/" in type_id:
                        enrichment.itemType = type_id.split("/")[-1]
                    else:
                        enrichment.itemType = type_id
                elif isinstance(item_type, str):
                    enrichment.itemType = item_type
                
                # itemKeyword (array of keywords)
                item_keywords = main_entity.get("ksam:itemKeyword", [])
                if item_keywords:
                    if isinstance(item_keywords, list):
                        enrichment.itemKeyword = json.dumps(item_keywords, ensure_ascii=False)
                    else:
                        enrichment.itemKeyword = json.dumps([item_keywords], ensure_ascii=False)
                
                # itemTitle (might be the same as itemLabel)
                enrichment.itemTitle = main_entity.get("ksam:itemTitle") or enrichment.itemLabel
                
                # dataQuality
                data_quality = main_entity.get("ksam:dataQuality", {})
                if isinstance(data_quality, dict):
                    quality_id = data_quality.get("@id", "")
                    if "/" in quality_id:
                        enrichment.dataQuality = quality_id.split("/")[-1]
                    else:
                        enrichment.dataQuality = quality_id
                elif isinstance(data_quality, str):
                    enrichment.dataQuality = data_quality
            
            return enrichment
            
        except Exception as e:
            logger.error(f"Error extracting enrichment data: {e}")
            return EnrichmentData()
    
    def update_site_enrichment(self, inspireid: str, enrichment: EnrichmentData):
        """Update a single site with enrichment data."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE fornlamningar 
                SET itemLabel = ?, itemType = ?, itemKeyword = ?, 
                    itemTitle = ?, dataQuality = ?
                WHERE inspireid = ?
            """, (
                enrichment.itemLabel,
                enrichment.itemType,
                enrichment.itemKeyword,
                enrichment.itemTitle,
                enrichment.dataQuality,
                inspireid
            ))
            
            conn.commit()
            logger.debug(f"Updated enrichment for {inspireid}")
            
        except Exception as e:
            logger.error(f"Error updating {inspireid}: {e}")
        finally:
            conn.close()
    
    def enrich_database(self, limit: Optional[int] = None):
        """Enrich the entire database with API data."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get all inspireids and UUIDs
        if limit:
            cursor.execute("SELECT inspireid, uuid FROM fornlamningar LIMIT ?", (limit,))
        else:
            cursor.execute("SELECT inspireid, uuid FROM fornlamningar")
        
        sites = cursor.fetchall()
        conn.close()
        
        total_sites = len(sites)
        logger.info(f"Starting enrichment for {total_sites} sites")
        
        successful_updates = 0
        failed_updates = 0
        
        for i, (inspireid, uuid) in enumerate(sites, 1):
            try:
                logger.info(f"Processing {i}/{total_sites}: {inspireid} (UUID: {uuid})")
                
                # Query the API
                api_response = self.query_ksamsok_api(inspireid, uuid)
                
                if api_response:
                    # Extract enrichment data
                    enrichment = self.extract_enrichment_data(api_response)
                    
                    # Update the database
                    self.update_site_enrichment(inspireid, enrichment)
                    successful_updates += 1
                    
                    # Log some details for the first few successful updates
                    if successful_updates <= 5:
                        logger.info(f"  Enriched: {enrichment.itemLabel or 'No label'} ({enrichment.itemType or 'No type'})")
                else:
                    failed_updates += 1
                    logger.warning(f"  No API data found for {inspireid}")
                
                # Rate limiting - small delay between requests
                time.sleep(0.2)
                
            except Exception as e:
                failed_updates += 1
                logger.error(f"Error processing {inspireid}: {e}")
            
            # Progress update every 10 sites
            if i % 10 == 0:
                logger.info(f"Progress: {i}/{total_sites} ({i/total_sites*100:.1f}%) - "
                          f"Success: {successful_updates}, Failed: {failed_updates}")
        
        logger.info(f"Enrichment completed!")
        logger.info(f"Total processed: {total_sites}")
        logger.info(f"Successful updates: {successful_updates}")
        logger.info(f"Failed updates: {failed_updates}")
        logger.info(f"Success rate: {successful_updates/total_sites*100:.1f}%")
    
    def get_enrichment_stats(self):
        """Get statistics about the enrichment data."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        stats = {}
        
        # Total sites
        cursor.execute("SELECT COUNT(*) FROM fornlamningar")
        stats['total_sites'] = cursor.fetchone()[0]
        
        # Sites with each enrichment field
        enrichment_fields = ['itemLabel', 'itemType', 'itemKeyword', 'itemTitle', 'dataQuality']
        
        for field in enrichment_fields:
            cursor.execute(f"SELECT COUNT(*) FROM fornlamningar WHERE {field} IS NOT NULL")
            stats[f'{field}_count'] = cursor.fetchone()[0]
        
        # Sample enriched sites
        cursor.execute("""
            SELECT inspireid, itemLabel, itemType, itemKeyword 
            FROM fornlamningar 
            WHERE itemLabel IS NOT NULL 
            LIMIT 5
        """)
        stats['sample_sites'] = cursor.fetchall()
        
        conn.close()
        return stats


def main():
    """Main function to run the enrichment process."""
    # Configuration
    db_path = "src/data/fornlamningar_filtered_20km.sqlite"
    
    # Check if database exists
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        return
    
    # Initialize enricher
    enricher = DatabaseEnricher(db_path)
    
    # Setup database (add new columns)
    logger.info("Setting up database...")
    enricher.setup_database()
    
    # Run enrichment for all sites
    logger.info("Starting enrichment process...")
    enricher.enrich_database()  # Process all 1,491 sites
    
    # Get and display statistics
    logger.info("Getting enrichment statistics...")
    stats = enricher.get_enrichment_stats()
    
    print("\n=== Enrichment Statistics ===")
    print(f"Total sites: {stats['total_sites']}")
    print(f"Sites with itemLabel: {stats['itemLabel_count']}")
    print(f"Sites with itemType: {stats['itemType_count']}")
    print(f"Sites with itemKeyword: {stats['itemKeyword_count']}")
    print(f"Sites with itemTitle: {stats['itemTitle_count']}")
    print(f"Sites with dataQuality: {stats['dataQuality_count']}")
    
    print("\n=== Sample Enriched Sites ===")
    for site in stats['sample_sites']:
        inspireid, item_label, item_type, item_keywords = site
        print(f"  {inspireid}: {item_label or 'No label'} ({item_type or 'No type'})")
        if item_keywords:
            try:
                keywords = json.loads(item_keywords)
                if isinstance(keywords, list):
                    # Handle list of keywords
                    keyword_strings = []
                    for kw in keywords:
                        if isinstance(kw, dict):
                            keyword_strings.append(kw.get('@value', str(kw)))
                        else:
                            keyword_strings.append(str(kw))
                    print(f"    Keywords: {', '.join(keyword_strings)}")
                else:
                    print(f"    Keywords: {keywords}")
            except Exception as e:
                print(f"    Keywords: {item_keywords} (parse error: {e})")


if __name__ == "__main__":
    main()
