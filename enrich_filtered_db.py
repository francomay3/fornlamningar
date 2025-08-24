#!/usr/bin/env python3
"""
Final enhanced script to enrich the filtered archaeological sites database with detailed descriptions
from the K-samsök API using the improved extraction method.

This script will:
1. Read the filtered database
2. For each site, query the K-samsök API using the UUID
3. Extract detailed descriptions using enhanced entity reference following
4. Update the database with rich archaeological descriptions
"""

import sqlite3
import time
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import json
import os

# Import our API utilities
from src.apiUtils.api_utils import APIConfig, RateLimitedAPI

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('enrichment_enhanced_final.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class EnrichmentData:
    """Data structure for enrichment fields."""
    itemKeyword: Optional[str] = None  # Will be stored as JSON string
    itemTitle: Optional[str] = None
    description: Optional[str] = None  # Comprehensive description from all fields


class DatabaseEnricher:
    """Class to handle database enrichment with detailed K-samsök API data."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.api_config = APIConfig(
            base_url="https://kulturarvsdata.se",
            rate_limit=5,  # Conservative rate limit
            headers={
                'User-Agent': 'Fornlamningar-Enrichment-Enhanced-Final/1.0',
                'Accept': 'application/json'
            }
        )
        self.api = RateLimitedAPI(self.api_config)
        
        # Ensure the description column exists
        self.ensure_description_column()
        
        # Track field extraction statistics
        self.field_stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'fields_found': {},
            'fields_missing': set(),
            'extraction_errors': []
        }
    
    def ensure_description_column(self):
        """Ensure the description column exists in the database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Check if description column exists
            cursor.execute("PRAGMA table_info(fornlamningar)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'description' not in columns:
                logger.info("Adding description column to database...")
                cursor.execute("ALTER TABLE fornlamningar ADD COLUMN description TEXT")
                conn.commit()
                logger.info("Description column added successfully")
            else:
                logger.info("Description column already exists")
                
        except Exception as e:
            logger.error(f"Error ensuring description column: {e}")
        finally:
            conn.close()
        
    def extract_enhanced_description(self, api_data: Dict[str, Any]) -> str:
        """Extract enhanced description by following entity references."""
        
        if not api_data or "@graph" not in api_data:
            return "No data available"
        
        # Create a lookup dictionary for all entities
        entities = {}
        for entity in api_data["@graph"]:
            if "@id" in entity:
                entities[entity["@id"]] = entity
        
        # Find the main archaeological site entity
        main_entity = None
        for entity in api_data["@graph"]:
            if (isinstance(entity.get("@id"), str) and 
                entity.get("@id").startswith("http://kulturarvsdata.se/raa/lamning/")):
                main_entity = entity
                break
        
        if not main_entity:
            return "Main entity not found"
        
        description_parts = []
        
        # Extract basic info
        item_title = main_entity.get("ksam:itemTitle")
        if item_title:
            description_parts.append(f"Title: {item_title}")
        
        item_class = main_entity.get("ksam:itemClassName", {}).get("@value")
        if item_class:
            description_parts.append(f"Class: {item_class}")
        
        # Extract descriptions by following references
        item_descriptions = main_entity.get("ksam:itemDescription", [])
        if isinstance(item_descriptions, list):
            for desc_ref in item_descriptions:
                if isinstance(desc_ref, dict) and "@id" in desc_ref:
                    desc_entity = entities.get(desc_ref["@id"])
                    if desc_entity:
                        desc_type = desc_entity.get("ksam:type", {}).get("@value", "Unknown")
                        desc_content = desc_entity.get("ksam:desc", {}).get("@value", "")
                        if desc_content:
                            description_parts.append(f"{desc_type}: {desc_content}")
                            self.field_stats['fields_found'][desc_type] = self.field_stats['fields_found'].get(desc_type, 0) + 1
        
        # Extract geographic context
        context_ref = main_entity.get("ksam:context")
        if context_ref and isinstance(context_ref, dict) and "@id" in context_ref:
            context_entity = entities.get(context_ref["@id"])
            if context_entity:
                geographic_info = []
                
                province = context_entity.get("ksam:provinceName", {}).get("@value")
                county = context_entity.get("ksam:countyName", {}).get("@value")
                municipality = context_entity.get("ksam:municipalityName", {}).get("@value")
                parish = context_entity.get("ksam:parishName", {}).get("@value")
                
                if province:
                    geographic_info.append(f"Province: {province}")
                if county:
                    geographic_info.append(f"County: {county}")
                if municipality:
                    geographic_info.append(f"Municipality: {municipality}")
                if parish:
                    geographic_info.append(f"Parish: {parish}")
                
                if geographic_info:
                    description_parts.append(" | ".join(geographic_info))
                    self.field_stats['fields_found']['geographic'] = self.field_stats['fields_found'].get('geographic', 0) + 1
        
        # Extract specifications
        item_specs = main_entity.get("ksam:itemSpecification", [])
        if isinstance(item_specs, list):
            for spec_ref in item_specs:
                if isinstance(spec_ref, dict) and "@id" in spec_ref:
                    spec_entity = entities.get(spec_ref["@id"])
                    if spec_entity:
                        spec_type = spec_entity.get("ksam:type", {}).get("@value", "Unknown")
                        spec_content = spec_entity.get("ksam:spec", {}).get("@value", "")
                        if spec_content:
                            description_parts.append(f"{spec_type}: {spec_content}")
                            self.field_stats['fields_found'][spec_type] = self.field_stats['fields_found'].get(spec_type, 0) + 1
        
        # Extract item numbers
        item_numbers = main_entity.get("ksam:itemNumber", [])
        if isinstance(item_numbers, list):
            for num_ref in item_numbers:
                if isinstance(num_ref, dict) and "@id" in num_ref:
                    num_entity = entities.get(num_ref["@id"])
                    if num_entity:
                        num_type = num_entity.get("ksam:type", {}).get("@value", "Unknown")
                        num_content = num_entity.get("ksam:number", {}).get("@value", "")
                        if num_content:
                            description_parts.append(f"{num_type}: {num_content}")
                            self.field_stats['fields_found'][num_type] = self.field_stats['fields_found'].get(num_type, 0) + 1
        
        # Add basic metadata
        organization = main_entity.get("ksam:serviceOrganization", {}).get("@value")
        if organization:
            description_parts.append(f"Organization: {organization}")
            self.field_stats['fields_found']['organization'] = self.field_stats['fields_found'].get('organization', 0) + 1
        
        build_date = main_entity.get("ksam:buildDate")
        if build_date:
            description_parts.append(f"Build Date: {build_date}")
            self.field_stats['fields_found']['buildDate'] = self.field_stats['fields_found'].get('buildDate', 0) + 1
        
        last_changed = main_entity.get("ksam:lastChangedDate")
        if last_changed:
            description_parts.append(f"Last Changed: {last_changed}")
            self.field_stats['fields_found']['lastChanged'] = self.field_stats['fields_found'].get('lastChanged', 0) + 1
        
        url = main_entity.get("ksam:url")
        if url:
            description_parts.append(f"URL: {url}")
            self.field_stats['fields_found']['url'] = self.field_stats['fields_found'].get('url', 0) + 1
        
        # Join all parts
        return "\n\n".join(description_parts) if description_parts else "No description available"
    
    def extract_enrichment_data(self, api_response: Dict[str, Any]) -> EnrichmentData:
        """Extract enrichment data from API response."""
        try:
            # Extract enrichment fields
            enrichment = EnrichmentData()
            
            # Find the main entity in the @graph array
            graph = api_response.get("@graph", [])
            main_entity = None
            
            for entity in graph:
                if isinstance(entity, dict) and entity.get("@id", "").startswith("http://kulturarvsdata.se/raa/lamning/"):
                    main_entity = entity
                    break
            
            if not main_entity:
                logger.warning("Could not find main entity in API response")
                return enrichment
            
            # Extract enhanced description
            enrichment.description = self.extract_enhanced_description(api_response)
            
            # itemKeyword (array of keywords)
            item_keywords = main_entity.get("ksam:itemKeyword", [])
            if item_keywords:
                if isinstance(item_keywords, list):
                    enrichment.itemKeyword = json.dumps(item_keywords, ensure_ascii=False)
                else:
                    enrichment.itemKeyword = json.dumps([item_keywords], ensure_ascii=False)
            
            # itemTitle
            enrichment.itemTitle = main_entity.get("ksam:itemTitle")
            
            return enrichment
            
        except Exception as e:
            logger.error(f"Error extracting enrichment data: {e}")
            self.field_stats['extraction_errors'].append(f"Enrichment extraction error: {e}")
            return EnrichmentData()
    
    def query_ksamsok_api(self, inspireid: str, uuid: str) -> Optional[Dict[str, Any]]:
        """Query the K-samsök API for a specific archaeological site using UUID."""
        self.field_stats['total_requests'] += 1
        
        try:
            # Query the archaeological site directly
            logger.debug(f"Querying direct site URI for UUID: {uuid}")
            response = self.api.get(f"/raa/lamning/{uuid}")
            
            if response.status_code == 200:
                # We got the archaeological site directly
                site_data = response.json()
                logger.debug(f"Found archaeological site directly for UUID: {uuid}")
                self.field_stats['successful_requests'] += 1
                return site_data
            
            else:
                logger.warning(f"Direct access failed for {uuid}: {response.status_code}")
                self.field_stats['failed_requests'] += 1
                return None
                
        except Exception as e:
            logger.error(f"Error querying API for {inspireid} (UUID: {uuid}): {e}")
            self.field_stats['failed_requests'] += 1
            return None
    
    def update_site_enrichment(self, inspireid: str, enrichment: EnrichmentData):
        """Update a single site with enrichment data."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE fornlamningar 
                SET itemKeyword = ?, 
                    itemTitle = ?, description = ?
                WHERE inspireid = ?
            """, (
                enrichment.itemKeyword,
                enrichment.itemTitle,
                enrichment.description,
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
        logger.info(f"Starting enhanced enrichment for {total_sites} sites")
        
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
                        desc_preview = enrichment.description[:200] + "..." if enrichment.description and len(enrichment.description) > 200 else enrichment.description
                        logger.info(f"  Enriched: {enrichment.itemTitle or 'No title'}")
                        logger.info(f"    Description preview: {desc_preview}")
                        logger.info(f"    Description length: {len(enrichment.description) if enrichment.description else 0} chars")
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
        
        logger.info(f"Enhanced enrichment completed!")
        logger.info(f"Total processed: {total_sites}")
        logger.info(f"Successful updates: {successful_updates}")
        logger.info(f"Failed updates: {failed_updates}")
        logger.info(f"Success rate: {successful_updates/total_sites*100:.1f}%")
        
        # Log field extraction statistics
        self.log_field_statistics()
    
    def log_field_statistics(self):
        """Log detailed statistics about field extraction."""
        logger.info("\n=== FIELD EXTRACTION STATISTICS ===")
        logger.info(f"Total API requests: {self.field_stats['total_requests']}")
        logger.info(f"Successful requests: {self.field_stats['successful_requests']}")
        logger.info(f"Failed requests: {self.field_stats['failed_requests']}")
        
        logger.info("\nFields found in responses:")
        for field, count in sorted(self.field_stats['fields_found'].items(), key=lambda x: x[1], reverse=True):
            logger.info(f"  {field}: {count} sites")
        
        if self.field_stats['extraction_errors']:
            logger.info(f"\nExtraction errors ({len(self.field_stats['extraction_errors'])}):")
            for error in self.field_stats['extraction_errors'][:10]:  # Show first 10 errors
                logger.info(f"  {error}")
    
    def get_enrichment_stats(self):
        """Get statistics about the enrichment data."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        stats = {}
        
        # Total sites
        cursor.execute("SELECT COUNT(*) FROM fornlamningar")
        stats['total_sites'] = cursor.fetchone()[0]
        
        # Sites with each enrichment field
        enrichment_fields = ['itemKeyword', 'itemTitle', 'description']
        
        for field in enrichment_fields:
            cursor.execute(f"SELECT COUNT(*) FROM fornlamningar WHERE {field} IS NOT NULL")
            stats[f'{field}_count'] = cursor.fetchone()[0]
        
        # Description length statistics
        cursor.execute("""
            SELECT 
                MIN(LENGTH(description)) as min_length,
                MAX(LENGTH(description)) as max_length,
                AVG(LENGTH(description)) as avg_length
            FROM fornlamningar 
            WHERE description IS NOT NULL
        """)
        length_stats = cursor.fetchone()
        stats['description_lengths'] = {
            'min': length_stats[0],
            'max': length_stats[1],
            'avg': length_stats[2]
        }
        
        # Sample enriched sites
        cursor.execute("""
            SELECT inspireid, itemTitle, description 
            FROM fornlamningar 
            WHERE description IS NOT NULL 
            ORDER BY LENGTH(description) DESC
            LIMIT 5
        """)
        stats['sample_sites'] = cursor.fetchall()
        
        conn.close()
        return stats


def main():
    """Main function to run the enhanced enrichment process."""
    # Configuration
    db_path = "src/data/fornlamningar_filtered_20km.sqlite"  # Use main filtered database
    
    # Check if database exists
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        return
    
    # Initialize enricher
    enricher = DatabaseEnricher(db_path)
    
    # Run enrichment for all sites
    logger.info("Starting enhanced enrichment process...")
    enricher.enrich_database()  # Process all 1,491 sites
    
    # Get and display statistics
    logger.info("Getting enrichment statistics...")
    stats = enricher.get_enrichment_stats()
    
    print("\n=== Enhanced Enrichment Statistics ===")
    print(f"Total sites: {stats['total_sites']}")
    print(f"Sites with itemKeyword: {stats['itemKeyword_count']}")
    print(f"Sites with itemTitle: {stats['itemTitle_count']}")
    print(f"Sites with description: {stats['description_count']}")
    
    if stats['description_lengths']:
        print(f"\nDescription Length Statistics:")
        print(f"  Min length: {stats['description_lengths']['min']} chars")
        print(f"  Max length: {stats['description_lengths']['max']} chars")
        print(f"  Average length: {stats['description_lengths']['avg']:.1f} chars")
    
    print("\n=== Sample Enriched Sites (Longest Descriptions) ===")
    for site in stats['sample_sites']:
        inspireid, item_title, description = site
        print(f"\n{inspireid}: {item_title or 'No title'}")
        if description:
            desc_preview = description[:300] + "..." if len(description) > 300 else description
            print(f"  Description ({len(description)} chars): {desc_preview}")


if __name__ == "__main__":
    main()
