# Data Directory

This directory contains the geospatial data files for the fornlamningar project.

## Files

- `fornlamningar_full.gpkg` - Main geopackage database containing fornlamningar (ancient remains) data
  - File size: ~183MB
  - Format: GeoPackage (.gpkg)
  - Contains spatial data with geometry and attribute information

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
