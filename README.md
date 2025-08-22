# Fornlamningar

A Python geospatial data processing project for handling fornlamningar (ancient remains) data stored in GeoPackage format.

## Features

- **Geospatial Data Handling**: Load, explore, and manipulate GeoPackage files
- **Data Analysis**: Statistical analysis and filtering capabilities
- **Advanced Visualization**: Multiple visualization scripts for different data types and regions
- **Interactive Mapping**: Folium-based interactive web maps
- **Regional Analysis**: Focused analysis of specific Swedish regions
- **Comprehensive Documentation**: Detailed geopackage structure documentation
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
- `visualize_points.py` - Point data visualization script
- `create_interactive_map.py` - Interactive web map generation
- `comprehensive_map.py` - Multi-geometry type visualization
- `explore_data.py` - Data exploration and analysis script
- `regional_analysis.py` - Regional archaeological site analysis
- `tests/` - Test files
- `docs/` - Documentation
- `GEOPACKAGE_STRUCTURE.md` - Detailed data structure documentation
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

# Generate visualizations
python visualize_points.py
python create_interactive_map.py
python comprehensive_map.py
python regional_analysis.py
python explore_data.py
```

### Visualization Scripts

- **`visualize_points.py`**: Creates static maps of individual archaeological sites
- **`create_interactive_map.py`**: Generates interactive HTML maps with site information
- **`comprehensive_map.py`**: Shows all data types (polygons, lines, points) together
- **`regional_analysis.py`**: Analyzes and maps archaeological sites in specific regions
- **`explore_data.py`**: Provides detailed data exploration and quality analysis

## Data

The project includes a GeoPackage file (`src/data/fornlamningar_full.gpkg`) containing comprehensive Swedish archaeological data with:

- **342,879 total features** across 4 layers
- **Point sites**: 219,639 individual archaeological locations
- **Protected areas**: 92,939 polygon boundaries
- **Linear features**: 30,301 linear archaeological structures
- **Complete documentation**: See `GEOPACKAGE_STRUCTURE.md` for detailed schema

## Dependencies

- `geopandas` - Geospatial data manipulation
- `fiona` - Geospatial data I/O
- `shapely` - Geometric operations
- `pyproj` - Coordinate system transformations
- `pandas` - Data manipulation
- `numpy` - Numerical computing
- `matplotlib` - Plotting and visualization
- `folium` - Interactive mapping
