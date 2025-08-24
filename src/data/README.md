# Data Directory

This directory contains the geospatial data files for the fornlamningar project.

## Files

- `fornlamningar_full.gpkg` - Main geopackage database containing fornlamningar (ancient remains) data
  - File size: ~183MB
  - Format: GeoPackage (.gpkg)
  - Contains spatial data with geometry and attribute information
  - **Contains 3 layers**: polygons, lines, and points

- `fornlamningar_points.gpkg` - Points-only geopackage database
  - File size: ~30MB
  - Format: GeoPackage (.gpkg)
  - Contains only point features with simplified metadata
  - **Contains 1 layer**: `fornlamningar` (210,312 features)
  - **Optimized structure**: Streamlined columns for efficient point-based analysis

- `fornlamningar_points.sqlite` - Standard SQLite database
  - File size: 26.7MB
  - Format: SQLite (.sqlite)
  - Contains archaeological sites with extracted coordinates
  - **Contains 2 tables**: `fornlamningar` (210,312 features) and `metadata`
  - **App-ready format**: No GIS dependencies required

## Database Schema

The `fornlamningar_full.gpkg` file contains **3 main data layers**, each representing different types of archaeological sites with different geometry types:

### Layer 1: PS_NationalMonuments_poly
- **Geometry Type**: Polygon
- **Number of Features**: 92,939
- **Columns**:
  - `id` (INTEGER, Primary Key) - Unique identifier
  - `geom` (GEOMETRY) - Polygon geometry
  - `designationschemevalue` (TEXT(200)) - INSPIRE designation scheme
  - `designationvalue` (TEXT(200)) - INSPIRE designation value
  - `protectionclassificationvalue` (TEXT(200)) - Protection classification (e.g., "archaeological")
  - `inspireid` (TEXT(200)) - INSPIRE identifier (e.g., "L1968:9269-1")
  - `sitename` (TEXT(200)) - Site name (mostly NULL in sample data)
  - `protectionclassificationvalue2` (TEXT(200)) - Secondary protection classification (mostly NULL)
  - `legalfoundationdocument` (TEXT(200)) - URL to legal foundation document

### Layer 2: PS_NationalMonuments_line
- **Geometry Type**: LineString
- **Number of Features**: 30,301
- **Columns**: Same as polygon layer
  - `id` (INTEGER, Primary Key) - Unique identifier
  - `geom` (GEOMETRY) - LineString geometry
  - `designationschemevalue` (TEXT(200)) - INSPIRE designation scheme
  - `designationvalue` (TEXT(200)) - INSPIRE designation value
  - `protectionclassificationvalue` (TEXT(200)) - Protection classification
  - `inspireid` (TEXT(200)) - INSPIRE identifier
  - `sitename` (TEXT(200)) - Site name (mostly NULL)
  - `protectionclassificationvalue2` (TEXT(200)) - Secondary protection classification (mostly NULL)
  - `legalfoundationdocument` (TEXT(200)) - URL to legal foundation document

### Layer 3: PS_NationalMonuments_point
- **Geometry Type**: Point
- **Number of Features**: 219,639
- **Columns**: Same as polygon layer
  - `id` (INTEGER, Primary Key) - Unique identifier
  - `geom` (GEOMETRY) - Point geometry
  - `designationschemevalue` (TEXT(200)) - INSPIRE designation scheme
  - `designationvalue` (TEXT(200)) - INSPIRE designation value
  - `protectionclassificationvalue` (TEXT(200)) - Protection classification
  - `inspireid` (TEXT(200)) - INSPIRE identifier
  - `sitename` (TEXT(200)) - Site name (mostly NULL)
  - `protectionclassificationvalue2` (TEXT(200)) - Secondary protection classification (mostly NULL)
  - `legalfoundationdocument` (TEXT(200)) - URL to legal foundation document

## Points Database Structure

The `fornlamningar_points.gpkg` file contains a streamlined version of the point data with simplified metadata:

### Layer: fornlamningar
- **Geometry Type**: Point
- **Number of Features**: 210,312
- **File Size**: ~30MB
- **Columns**:
  - `inspireid` (TEXT) - INSPIRE identifier (e.g., "L1966:4638-1")
  - `sitename` (TEXT) - Site name (mostly NULL)
  - `uuid` (TEXT) - Unique identifier (e.g., "d6e74db6-6351-4383-8dc6-682e84f16d30")
  - `geometry` (GEOMETRY) - Point geometry coordinates

### Key Differences from Full Database:
- **Simplified Schema**: Only 4 columns vs 8 columns in full database
- **Deduplicated**: Removes duplicate point features
- **Optimized Size**: 30MB vs 183MB (6.1x smaller)
- **Focused Purpose**: Designed for point-based analysis and visualization

### Use Cases:
- **Point Distribution Analysis**: Mapping individual archaeological sites
- **Quick Visualization**: Fast loading for interactive maps
- **Statistical Analysis**: Efficient processing of site locations
- **Web Applications**: Lightweight data for online mapping

## SQLite Database Structure

The `fornlamningar_points.sqlite` file provides a standard SQLite format optimized for application development:

### Table: fornlamningar
- **Number of Features**: 210,312
- **File Size**: 26.7MB
- **Columns**:
  - `inspireid` (TEXT) - INSPIRE identifier (e.g., "L1966:4638-1")
  - `sitename` (TEXT) - Site name (mostly NULL)
  - `uuid` (TEXT) - Unique identifier (e.g., "d6e74db6-6351-4383-8dc6-682e84f16d30")
  - `longitude` (REAL) - X coordinate in EPSG:3006 (Swedish coordinate system)
  - `latitude` (REAL) - Y coordinate in EPSG:3006 (Swedish coordinate system)

### Table: metadata
- **Conversion Information**: Source file, conversion date, coordinate system
- **Spatial Bounds**: Minimum and maximum coordinates
- **Data Statistics**: Total feature count and geometry type

### Performance Features:
- **Indexes**: Fast queries on `inspireid`, `sitename`, and `(longitude, latitude)`
- **Standard SQLite**: Compatible with any SQLite-compatible framework
- **No Dependencies**: No special GIS libraries required

### Use Cases:
- **Web Applications**: Easy integration with web frameworks
- **Mobile Apps**: Lightweight database for mobile applications
- **Standard Database Operations**: SQL queries, joins, filtering
- **Mapping Libraries**: Direct coordinate access for mapping APIs

## Data Pipeline Process

The project implements a **three-stage optimization pipeline** to create application-ready data:

### Stage 1: Full Database (`fornlamningar_full.gpkg`)
- **Source**: Complete archaeological dataset from Swedish National Heritage Board
- **Content**: 342,879 features across 4 layers (polygons, lines, points)
- **Schema**: 8 columns including metadata, legal documents, and spatial data
- **Purpose**: Comprehensive GIS analysis and research

### Stage 2: Points Extraction (`fornlamningar_points.gpkg`)
**Filtering Process:**
- **Geometry Filter**: Kept only point features (removed 123,240 polygon/line features)
- **Column Analysis**: Identified redundant columns with no informational value:
  - `designationschemevalue` → Always "INSPIRE" (constant value)
  - `designationvalue` → Always "archaeological" (constant value)
  - `protectionclassificationvalue` → Always "archaeological" (constant value)
  - `protectionclassificationvalue2` → 99.9% NULL values
  - `legalfoundationdocument` → URLs with UUIDs (replaced by new `uuid` column containing just the UUID)
- **Column Transformation**: 
  - `legalfoundationdocument` → `uuid` (extracted UUID from URL format)
- **Deduplication**: Removed duplicate UUID point features
- **Result**: 210,312 unique point sites with essential metadata

### Stage 3: SQLite Conversion (`fornlamningar_points.sqlite`)
**Conversion Process:**
- **Coordinate Extraction**: Converted geometry BLOB data to separate `longitude`/`latitude` columns
- **Format Standardization**: Regular SQLite database (no spatial extensions)
- **Performance Optimization**: Added strategic indexes for common query patterns
- **Metadata Preservation**: Included conversion tracking and spatial bounds
- **App Optimization**: Compatible with any SQLite-compatible framework

### Pipeline Benefits:
- **Size Reduction**: 183MB → 30MB → 26.7MB (85% reduction)
- **Complexity Reduction**: 8 columns → 4 columns → 5 columns (extracted coordinates)
- **Accessibility**: GIS format → Standard database format
- **Performance**: Optimized for application use cases

## Data Characteristics

- **Total Features**: 342,879 across all three layers (full database)
- **Point Features**: 210,312 (points-only database)
- **Coordinate System**: Based on INSPIRE standards
- **Data Source**: Swedish National Heritage Board (Riksantikvarieämbetet)
- **Coverage**: Sweden
- **Data Quality**: All features have consistent attribute structure
- **Missing Data**: `sitename` field is mostly NULL in both databases

## Usage

The geopackage file can be accessed using the `FornlamningarData` class in `../geodata.py`:

```python
from geodata import FornlamningarData

# Initialize data handler
data_handler = FornlamningarData()

# Get available layers
layers = data_handler.get_layers()

# Load data
gdf = data_handler.load_data()
```

### SQLite Database Usage

```python
import sqlite3
import pandas as pd

# Connect to SQLite database
conn = sqlite3.connect("fornlamningar_points.sqlite")

# Basic queries
total_sites = conn.execute("SELECT COUNT(*) FROM fornlamningar").fetchone()[0]
named_sites = conn.execute("SELECT COUNT(*) FROM fornlamningar WHERE sitename IS NOT NULL").fetchone()[0]

# Load data into pandas
df = pd.read_sql_query("SELECT * FROM fornlamningar", conn)

# Spatial queries (using coordinate bounds)
stockholm_area = conn.execute("""
    SELECT * FROM fornlamningar 
    WHERE longitude BETWEEN 300000 AND 400000 
    AND latitude BETWEEN 6500000 AND 6700000
""").fetchall()

# Get metadata
metadata = pd.read_sql_query("SELECT * FROM metadata", conn)

conn.close()
```

### Web Application Integration

```python
# Flask example
from flask import Flask, jsonify
import sqlite3

app = Flask(__name__)

@app.route('/api/sites')
def get_sites():
    conn = sqlite3.connect("fornlamningar_points.sqlite")
    sites = conn.execute("SELECT * FROM fornlamningar LIMIT 100").fetchall()
    conn.close()
    return jsonify(sites)

@app.route('/api/sites/<inspireid>')
def get_site(inspireid):
    conn = sqlite3.connect("fornlamningar_points.sqlite")
    site = conn.execute("SELECT * FROM fornlamningar WHERE inspireid = ?", (inspireid,)).fetchone()
    conn.close()
    return jsonify(site)
```

## Dependencies

Make sure you have the required dependencies installed:
```bash
pip install -r ../../requirements.txt
```

## TODO: Enhanced Metadata Integration

**Planned API Data Enrichment**

The current SQLite database contains only basic spatial coordinates. We plan to enrich it with valuable metadata from the K-samsök API to create a more user-friendly archaeological sites database.

### Target Fields to Add to the sqlite DB: (check the api documentation for details)
1. **`itemKeyword`** - Descriptive tags/keywords (e.g., ["Fornlämningar", "Arkeologi", "Järnålder"])
2. **`itemTitle`** - Official title of the site

### Benefits:
- **User Experience**: Sites will have names, descriptions, and images instead of just coordinates
- **Discovery**: Users can search and filter by type, keywords, and location
- **Prioritization**: Data quality indicators help identify well-documented, interesting sites
- **Visual Appeal**: Thumbnail images make the database much more engaging

### Implementation Notes:
- These fields will be fetched from the K-samsök API using the existing `inspireid` as the lookup key
- The enrichment process will maintain the current database structure while adding new columns
- Data quality filtering can help prioritize sites for recommendations and featured content

## Notes

- The geopackage file is large (183MB) and contains comprehensive spatial data
- Use the provided Python modules to explore and manipulate the data
- The data can be read, filtered, analyzed, and modified using the `FornlamningarData` class
- All three layers share the same attribute schema, making them easy to combine or analyze together
- The data follows INSPIRE standards for archaeological monument records
