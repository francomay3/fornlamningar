# Fornlamningar

A Python geospatial data processing project for handling fornlamningar (ancient remains) data stored in GeoPackage format.

## Features

- **Geospatial Data Handling**: Load, explore, and manipulate GeoPackage files
- **Data Analysis**: Statistical analysis and filtering capabilities
- **Visualization**: Basic mapping and plotting functionality
- **Flexible API**: Easy-to-use `FornlamningarData` class for data operations

## Setup

1. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Project Structure

- `src/` - Source code
  - `geodata.py` - Main geospatial data handling module
  - `main.py` - Entry point with example usage
  - `example_usage.py` - Comprehensive usage examples
  - `data/` - Geospatial data files
- `tests/` - Test files
- `docs/` - Documentation
- `requirements.txt` - Python dependencies

## Usage

### Basic Usage

```python
from geodata import FornlamningarData

# Initialize data handler
data_handler = FornlamningarData()

# Load data
gdf = data_handler.load_data()

# Explore data
info = data_handler.explore_data()
stats = data_handler.get_statistics()
```

### Running Examples

```bash
# Run main example
python src/main.py

# Run comprehensive examples
python src/example_usage.py
```

## Data

The project includes a GeoPackage file (`src/data/fornlamningar_full.gpkg`) containing spatial data with geometry and attribute information for ancient remains.

## Dependencies

- `geopandas` - Geospatial data manipulation
- `fiona` - Geospatial data I/O
- `shapely` - Geometric operations
- `pyproj` - Coordinate system transformations
- `pandas` - Data manipulation
- `numpy` - Numerical computing
- `matplotlib` - Plotting and visualization
- `folium` - Interactive mapping
