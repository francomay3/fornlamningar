# Fornlamningar Geopackage Structure

This document describes the structure and content of the Swedish archaeological heritage data stored in the `fornlamningar_full.gpkg` geopackage file.

## Overview

The geopackage contains comprehensive archaeological data from the Swedish National Heritage Board (Riksantikvarieämbetet), covering all legally protected archaeological sites and features in Sweden.

## Data Layers

The geopackage contains **4 layers** with a total of **342,879 archaeological features**:

### 1. PS_NationalMonuments_poly (92,939 features)
- **Geometry Type**: Polygons
- **Description**: Legally protected archaeological zones and areas
- **Purpose**: These represent the official boundaries of protected archaeological sites
- **CRS**: EPSG:3006 (Swedish coordinate system)
- **Named Features**: 6,610 (7.1% of total)

### 2. PS_NationalMonuments_line (30,301 features)
- **Geometry Type**: LineStrings
- **Description**: Linear archaeological features
- **Purpose**: Ancient roads, boundaries, walls, and other linear structures
- **CRS**: EPSG:3006 (Swedish coordinate system)
- **Named Features**: Very few (most are unnamed)

### 3. PS_NationalMonuments_point (219,639 features)
- **Geometry Type**: Points
- **Description**: Individual archaeological sites
- **Purpose**: Precise locations of archaeological finds and sites
- **CRS**: EPSG:3006 (Swedish coordinate system)
- **Named Features**: 3,321 (1.5% of total)

### 4. example_subset (100 features)
- **Geometry Type**: Polygons
- **Description**: Test subset created during development
- **Purpose**: Sample data for testing and development

## Data Schema

All layers share the same attribute schema:

| Column | Type | Description |
|--------|------|-------------|
| `designationschemevalue` | String | INSPIRE designation scheme identifier |
| `designationvalue` | String | INSPIRE designation value |
| `protectionclassificationvalue` | String | Type of archaeological feature (usually "archaeological") |
| `inspireid` | String | Unique INSPIRE identifier for each feature |
| `sitename` | String | Name of the archaeological site (if available) |
| `protectionclassificationvalue2` | String | Secondary protection classification (mostly null) |
| `legalfoundationdocument` | String | URL to legal foundation document in RAA database |
| `geometry` | Geometry | Spatial geometry (Point, LineString, or Polygon) |

## Coordinate Reference System

- **Source CRS**: EPSG:3006 (Swedish coordinate system)
- **Recommended for visualization**: EPSG:4326 (WGS84) for web mapping
- **Coverage**: All of Sweden (approximately 55°N to 69°N, 11°E to 24°E)

## Data Quality

### Completeness
- **Point sites**: 219,639 total, 3,321 named (1.5%)
- **Protected areas**: 92,939 total, 6,610 named (7.1%)
- **Linear features**: 30,301 total, mostly unnamed

### Geometry Quality
- All geometries are valid
- No duplicate features detected
- Consistent coordinate system across all layers

## Usage Examples

### Loading Data
```python
from src.geodata import FornlamningarData

# Load all point sites
data_handler = FornlamningarData()
points = data_handler.load_data(layer='PS_NationalMonuments_point')

# Load protected areas
polygons = data_handler.load_data(layer='PS_NationalMonuments_poly')

# Load linear features
lines = data_handler.load_data(layer='PS_NationalMonuments_line')
```

### Converting Coordinates
```python
# Convert to WGS84 for web mapping
points_wgs84 = points.to_crs('EPSG:4326')
```

### Filtering Named Sites
```python
# Get only named sites
named_sites = points[points['sitename'].notna()]
```

## Data Source

- **Provider**: Swedish National Heritage Board (Riksantikvarieämbetet)
- **Format**: GeoPackage (.gpkg)
- **Update Frequency**: Regular updates from RAA database
- **License**: Open data, available for research and public use

## Related Resources

- **RAA Database**: https://pub.raa.se/ (Swedish archaeological database)
- **INSPIRE**: European spatial data infrastructure standards
- **Swedish Heritage Board**: https://www.raa.se/

## File Information

- **File**: `src/data/fornlamningar_full.gpkg`
- **Size**: ~183 MB
- **Last Updated**: Based on RAA database export
- **Total Features**: 342,879 archaeological features
