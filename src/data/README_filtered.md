# Filtered Archaeological Sites Database

## Overview

This directory contains a filtered version of the archaeological sites database, containing only sites within 20km of the specified location.

## Files

- `fornlamningar_filtered_20km.sqlite` - Filtered SQLite database
  - File size: ~208KB
  - Format: SQLite (.sqlite)
  - Contains archaeological sites within 20km of target location
  - **Contains 2 tables**: `fornlamningar` (1,491 features) and `metadata`

## Filter Criteria

- **Target Location**: 57.482183, 12.154978 (WGS84 coordinates)
- **Filter Radius**: 20 kilometers
- **Source Database**: `fornlamningar_points.sqlite` (210,312 total sites)
- **Filter Date**: 2024-12-19

## Database Statistics

- **Total Sites**: 1,491 (0.7% of original database)
- **Size Reduction**: 99.3% smaller than original
- **Coverage Area**: ~1,257 km² (π × 20² km²)

## Database Schema

### Table: fornlamningar
- **Number of Features**: 1,491
- **Columns**:
  - `inspireid` (TEXT) - INSPIRE identifier (e.g., "L1966:5300-1")
  - `sitename` (TEXT) - Site name (e.g., "Råda sten", "Kungagraven")
  - `uuid` (TEXT) - Unique identifier
  - `longitude` (REAL) - X coordinate in EPSG:3006 (Swedish coordinate system)
  - `latitude` (REAL) - Y coordinate in EPSG:3006 (Swedish coordinate system)
     - `itemLabel` (TEXT) - Human-readable name/description from K-samsök API
   - `itemType` (TEXT) - Type of archaeological feature (e.g., "EntityType#monument")
   - `itemKeyword` (TEXT) - Descriptive tags/keywords (JSON format)
   - `itemTitle` (TEXT) - Official title of the site
   - `dataQuality` (TEXT) - Data quality indicator for filtering and prioritization

### Table: metadata
- **Filter Information**: Center coordinates, radius, date
- **Source Information**: Original database name
- **Statistics**: Total feature count

## Performance Features

- **Indexes**: Fast queries on `inspireid` and `(longitude, latitude)`
- **Optimized Size**: 208KB vs 26.7MB original (99.3% reduction)
- **Standard SQLite**: Compatible with any SQLite-compatible framework

## Usage Examples

### Basic Queries

```python
import sqlite3

# Connect to filtered database
conn = sqlite3.connect("src/data/fornlamningar_filtered_20km.sqlite")

# Get total count
total_sites = conn.execute("SELECT COUNT(*) FROM fornlamningar").fetchone()[0]
print(f"Total sites in filtered area: {total_sites}")

# Get sites with names
named_sites = conn.execute("SELECT COUNT(*) FROM fornlamningar WHERE sitename IS NOT NULL").fetchone()[0]
print(f"Sites with names: {named_sites}")

# Get metadata
metadata = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
print(f"Filter center: {metadata['filter_center_lat']}, {metadata['filter_center_lon']}")
print(f"Filter radius: {metadata['filter_radius_km']} km")

conn.close()
```

### Sample Sites

The filtered database includes notable archaeological sites such as:
- **Råda sten** (L1966:5300-1) - A standing stone
- **Kungagraven** (L1964:5422-1) - "King's grave" archaeological site

### Spatial Analysis

```python
import sqlite3
import pandas as pd

conn = sqlite3.connect("src/data/fornlamningar_filtered_20km.sqlite")

# Load all sites into pandas
df = pd.read_sql_query("SELECT * FROM fornlamningar", conn)

# Basic statistics
print(f"Coordinate range:")
print(f"  Longitude: {df['longitude'].min():.2f} to {df['longitude'].max():.2f}")
print(f"  Latitude: {df['latitude'].min():.2f} to {df['latitude'].max():.2f}")

# Sites with names
named_df = df[df['sitename'].notna()]
print(f"\nSites with names: {len(named_df)}")
for _, site in named_df.head().iterrows():
    print(f"  {site['inspireid']}: {site['sitename']}")

conn.close()
```

## Coordinate System

- **Database Coordinates**: EPSG:3006 (Swedish coordinate system)
- **Filter Coordinates**: WGS84 (latitude/longitude)
- **Distance Calculation**: Haversine formula for accurate geographic distances

## Benefits

1. **Performance**: 99.3% size reduction for faster queries
2. **Relevance**: Only sites relevant to the target area
3. **Efficiency**: Optimized for local archaeological research
4. **Portability**: Small file size for easy sharing and deployment

## Use Cases

- **Local Archaeological Research**: Focused study of sites in the target area
- **Mobile Applications**: Lightweight database for location-based apps
- **Web Mapping**: Fast loading for interactive maps of the local area
- **Field Work**: Offline database for archaeological surveys
- **Educational Tools**: Teaching resources focused on local archaeology

## Enhanced Metadata Integration

**✅ COMPLETED: API Data Enrichment**

The database has been enriched with comprehensive metadata from the K-samsök API, providing rich archaeological information for each site.

### Sample Enriched Data:
- **Råda sten, Grav markerad av sten/block** (grave marked by stone/block)
- **Kungagraven, Stenkammargrav** (King's grave, stone chamber grave)
- **Stensättning** (stone setting)
- **Ristning, medeltid/historisk tid** (carving, medieval/historical period)
- **Röse** (cairn)

### Enrichment Benefits:
- **Rich Descriptions**: Sites now have descriptive names and types instead of just coordinates
- **Archaeological Context**: Detailed information about site types and historical periods
- **Search & Filter**: Users can search and filter by type, keywords, and location
- **Data Quality**: Quality indicators help identify well-documented, interesting sites

### Implementation Details:
       - **API Integration**: Uses K-samsök API with UUID-based lookups for reliable data access
       - **Rate Limiting**: Implements proper API rate limiting and error handling
       - **Fallback Strategy**: Uses both direct site access and documentation relations for maximum coverage
       - **Data Coverage**: Successfully enriched 100% of sites with core metadata (itemLabel, itemType, itemTitle, dataQuality)
       - **Keyword Coverage**: 7.6% of sites have descriptive keywords (114 out of 1,491 sites)

## Technical Details

- **Distance Calculation**: Uses Haversine formula for accurate geographic distances
- **Coordinate Transformation**: Converts between WGS84 and EPSG:3006 coordinate systems
- **Data Integrity**: Preserves all original data fields and relationships
- **Indexing**: Optimized for common query patterns
- **API Enrichment**: K-samsök API integration for comprehensive metadata
