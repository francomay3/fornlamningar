#!/usr/bin/env python3
"""
Main entry point for the fornlamningar project.
Demonstrates usage of the geospatial data handling module.
"""

from geodata import FornlamningarData


def main():
    """Main function demonstrating geopackage data handling."""
    print("Hello, Fornlamningar!")
    print("Welcome to your geospatial data processing project!")
    
    # Initialize the data handler
    print("\nInitializing data handler...")
    data_handler = FornlamningarData()
    
    try:
        # Get available layers in the geopackage
        print("\nDiscovering available layers...")
        layers = data_handler.get_layers()
        print(f"Found {len(layers)} layer(s): {layers}")
        
        # Load the first layer
        print("\nLoading data...")
        gdf = data_handler.load_data()
        print(f"Successfully loaded data with shape: {gdf.shape}")
        
        # Explore the data structure
        print("\nExploring data structure...")
        info = data_handler.explore_data()
        print(f"Data shape: {info['shape']}")
        print(f"Columns: {info['columns']}")
        print(f"Geometry types: {info['geometry_type']}")
        print(f"Coordinate system: {info['crs']}")
        
        # Get statistical information
        print("\nCalculating statistics...")
        stats = data_handler.get_statistics()
        print(f"Total features: {stats['total_features']}")
        print(f"Geometry type distribution: {stats['geometry_types']}")
        
        if stats['area_km2']:
            print(f"Total area: {stats['area_km2']:.2f} km²")
        
        print("\nColumn information:")
        for col, col_info in stats['columns_info'].items():
            print(f"  {col}: {col_info['type']}")
            if col_info['type'] == 'categorical':
                print(f"    Unique values: {col_info['unique_values']}")
            else:
                if col_info['min'] is not None:
                    print(f"    Range: {col_info['min']:.2f} - {col_info['max']:.2f}")
        
        print("\nData exploration completed successfully!")
        
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Make sure the geopackage file is in the correct location: src/data/fornlamningar_full.gpkg")
    except Exception as e:
        print(f"Error during data processing: {e}")


if __name__ == "__main__":
    main()
