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

## Dependencies

Make sure you have the required dependencies installed:
```bash
pip install -r ../../requirements.txt
```

## Notes

- The geopackage file is large (183MB) and contains comprehensive spatial data
- Use the provided Python modules to explore and manipulate the data
- The data can be read, filtered, analyzed, and modified using the `FornlamningarData` class
- All three layers share the same attribute schema, making them easy to combine or analyze together
- The data follows INSPIRE standards for archaeological monument records
