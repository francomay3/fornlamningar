# Fornlamningar

A Python geospatial data processing project for handling fornlamningar (ancient remains) data stored in GeoPackage format.

## Features

- **Geospatial Data Handling**: Load, explore, and manipulate GeoPackage files
- **Data Analysis**: Statistical analysis and filtering capabilities
- **Advanced Visualization**: Multiple visualization scripts for different data types and regions
- **Interactive Mapping**: Folium-based interactive web maps
- **Regional Analysis**: Focused analysis of specific Swedish regions
- **Comprehensive Documentation**: Detailed geopackage structure documentation
- **API Utilities**: Rate-limited HTTP clients with retry logic and error handling
- **Flexible Data API**: Easy-to-use `FornlamningarData` class for data operations

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
  - `api_utils.py` - Rate-limited API utilities with retry logic
  - `main.py` - Entry point with example usage
  - `example_usage.py` - Comprehensive usage examples
  - `data/` - Geospatial data files
- `visualize_points.py` - Point data visualization script
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
python regional_analysis.py
python explore_data.py
```

### Visualization Scripts

- **`visualize_points.py`**: Creates static maps of individual archaeological sites
- **`regional_analysis.py`**: Analyzes and maps archaeological sites in specific regions
- **`explore_data.py`**: Provides detailed data exploration and quality analysis

### API Utilities

The project includes rate-limited API utilities in `src/api_utils.py`:

```python
from src.api_utils import APIConfig, RateLimitedAPI

# Configure API client
config = APIConfig(
    base_url="https://api.example.com",
    rate_limit=5,  # requests per second
    headers={'User-Agent': 'Fornlamningar-API-Client/1.0'}
)

# Make rate-limited requests
api = RateLimitedAPI(config)
response = api.get("/endpoint", params={"param": "value"})
```

## Data

The project includes multiple data formats for Swedish archaeological heritage data:

### Primary Data Sources

- **`src/data/fornlamningar_full.gpkg`** - Complete GeoPackage database
  - **342,879 total features** across 4 layers
  - **Point sites**: 219,639 individual archaeological locations
  - **Protected areas**: 92,939 polygon boundaries  
  - **Linear features**: 30,301 linear archaeological structures
  - **File size**: ~183MB
  - **Complete documentation**: See `GEOPACKAGE_STRUCTURE.md` for detailed schema

### Optimized Data Formats

- **`src/data/fornlamningar_points.gpkg`** - Points-only GeoPackage
  - **210,312 point features** (deduplicated from full database)
  - **Simplified schema**: 4 columns vs 8 in full database
  - **File size**: ~30MB (6.1x smaller than full database)
  - **Optimized for**: Point-based analysis and visualization

- **`src/data/fornlamningar_points.sqlite`** - Standard SQLite database
  - **210,312 archaeological sites** with extracted coordinates
  - **Standard SQLite format**: No special GIS dependencies required
  - **File size**: 26.7MB
  - **Perfect for**: Web applications, mobile apps, standard database operations
  - **Columns**: `inspireid`, `sitename`, `uuid`, `longitude`, `latitude`
  - **Indexed**: Fast queries on coordinates and identifiers

### Data Pipeline

The project implements a **three-stage data optimization pipeline**:

1. **Full Database** (`fornlamningar_full.gpkg`)
   - Complete archaeological dataset with all geometry types
   - 8 columns per feature including metadata and legal documents
   - Suitable for comprehensive GIS analysis

2. **Points Extraction** (`fornlamningar_points.gpkg`)
   - **Filtering**: Kept only point features (removed polygons and lines)
   - **Column Reduction**: Removed redundant columns:
     - `designationschemevalue` (always "INSPIRE")
     - `designationvalue` (always "archaeological") 
     - `protectionclassificationvalue` (always "archaeological")
     - `protectionclassificationvalue2` (mostly NULL)
   - **Column Transformation**: 
     - `legalfoundationdocument` → `uuid` (extracted UUID from URL format)
   - **Deduplication**: Removed duplicate point features
   - **Result**: 210,312 unique point sites with essential metadata

3. **SQLite Conversion** (`fornlamningar_points.sqlite`)
   - **Coordinate Extraction**: Converted geometry BLOB to `longitude`/`latitude` columns
   - **Standard Format**: Regular SQLite database (no spatial extensions)
   - **Performance Optimization**: Added indexes for fast queries
   - **Metadata Preservation**: Included conversion info and spatial bounds
   - **App-Ready**: Compatible with any SQLite-compatible framework

### Usage Examples

```python
# Load full GeoPackage for GIS analysis
from src.geodata import FornlamningarData
data_handler = FornlamningarData("src/data/fornlamningar_full.gpkg")
full_data = data_handler.load_data()

# Load points-only for visualization
points_handler = FornlamningarData("src/data/fornlamningar_points.gpkg")
points_data = points_handler.load_data()

# Use SQLite for web/mobile apps
import sqlite3
conn = sqlite3.connect("src/data/fornlamningar_points.sqlite")
sites = conn.execute("SELECT * FROM fornlamningar LIMIT 10").fetchall()
```

## Dependencies

- `geopandas` - Geospatial data manipulation
- `requests`, `aiohttp` - HTTP client libraries
- `tenacity`, `backoff`, `ratelimit` - Retry and rate limiting utilities
- `fiona` - Geospatial data I/O
- `shapely` - Geometric operations
- `pyproj` - Coordinate system transformations
- `pandas` - Data manipulation
- `numpy` - Numerical computing
- `matplotlib` - Plotting and visualization
- `folium` - Interactive mapping
