#!/usr/bin/env python3
"""
Example usage script for fornlamningar geopackage data.
Demonstrates various operations and data manipulation techniques.
"""

import geopandas as gpd
import matplotlib.pyplot as plt
from geodata import FornlamningarData


def example_basic_operations():
    """Demonstrate basic operations with the data."""
    print("=== Basic Operations Example ===")
    
    # Initialize data handler
    data_handler = FornlamningarData()
    
    # Load data
    gdf = data_handler.load_data()
    print(f"Loaded {len(gdf)} features")
    
    # Get basic info
    info = data_handler.explore_data()
    print(f"Data has {info['shape'][1]} columns")
    print(f"Geometry types: {info['geometry_type']}")
    
    return gdf, data_handler


def example_filtering():
    """Demonstrate filtering operations."""
    print("\n=== Filtering Example ===")
    
    gdf, data_handler = example_basic_operations()
    
    # Filter by geometry type (example)
    if 'Point' in gdf.geometry.geom_type.unique():
        points = data_handler.filter_by_geometry_type('Point')
        print(f"Found {len(points)} point features")
    
    if 'Polygon' in gdf.geometry.geom_type.unique():
        polygons = data_handler.filter_by_geometry_type('Polygon')
        print(f"Found {len(polygons)} polygon features")
    
    # Example: filter by attribute (if available)
    # This is just an example - adjust based on your actual data columns
    if 'name' in gdf.columns:
        # Filter features with non-null names
        named_features = gdf[gdf['name'].notna()]
        print(f"Found {len(named_features)} features with names")
    
    return gdf


def example_statistics():
    """Demonstrate statistical analysis."""
    print("\n=== Statistics Example ===")
    
    gdf, data_handler = example_basic_operations()
    
    # Get comprehensive statistics
    stats = data_handler.get_statistics()
    
    print(f"Total features: {stats['total_features']}")
    print(f"Geometry distribution: {stats['geometry_types']}")
    
    if stats['area_km2']:
        print(f"Total area: {stats['area_km2']:.2f} km²")
    
    # Show column information
    print("\nColumn details:")
    for col, info in stats['columns_info'].items():
        print(f"  {col}:")
        if info['type'] == 'categorical':
            print(f"    Type: Categorical ({info['unique_values']} unique values)")
            print(f"    Most common: {list(info['most_common'].keys())[:3]}")
        else:
            print(f"    Type: Numerical")
            if info['min'] is not None:
                print(f"    Range: {info['min']:.2f} - {info['max']:.2f}")
                print(f"    Mean: {info['mean']:.2f}")


def example_saving_data():
    """Demonstrate saving modified data."""
    print("\n=== Saving Data Example ===")
    
    gdf, data_handler = example_basic_operations()
    
    # Example: create a subset of the data
    # Take first 100 features as an example
    subset = gdf.head(100)
    
    # Save as a new layer
    try:
        data_handler.save_layer(subset, "example_subset")
        print("Saved subset as new layer 'example_subset'")
    except Exception as e:
        print(f"Error saving data: {e}")
    
    # You can also save to a different file
    # subset.to_file("src/data/subset.gpkg", driver='GPKG')


def example_visualization():
    """Demonstrate basic visualization."""
    print("\n=== Visualization Example ===")
    
    gdf, _ = example_basic_operations()
    
    try:
        # Create a simple map
        fig, ax = plt.subplots(1, 1, figsize=(12, 8))
        
        # Plot the data
        gdf.plot(ax=ax, alpha=0.7, markersize=1)
        
        # Add title
        ax.set_title('Fornlamningar Data Overview')
        ax.set_xlabel('Longitude')
        ax.set_ylabel('Latitude')
        
        # Save the plot
        plt.savefig('src/data/overview_map.png', dpi=300, bbox_inches='tight')
        print("Saved overview map to src/data/overview_map.png")
        
        plt.close()
        
    except Exception as e:
        print(f"Error creating visualization: {e}")


def main():
    """Run all examples."""
    print("Fornlamningar Data Processing Examples")
    print("=" * 50)
    
    try:
        # Run examples
        example_basic_operations()
        example_filtering()
        example_statistics()
        example_saving_data()
        example_visualization()
        
        print("\n" + "=" * 50)
        print("All examples completed successfully!")
        
    except Exception as e:
        print(f"Error running examples: {e}")


if __name__ == "__main__":
    main()
