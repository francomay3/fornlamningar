#!/usr/bin/env python3
"""
Create a comprehensive map showing all archaeological data types.
Shows polygons (protected areas), lines (linear features), and points (individual sites).
"""

import geopandas as gpd
import matplotlib.pyplot as plt
from src.geodata import FornlamningarData

def create_comprehensive_map():
    """Create a map showing polygons, lines, and points together."""
    print('Loading all archaeological data types...')
    data_handler = FornlamningarData()

    # Load each layer
    polygons = data_handler.load_data(layer='PS_NationalMonuments_poly')
    lines = data_handler.load_data(layer='PS_NationalMonuments_line')
    points = data_handler.load_data(layer='PS_NationalMonuments_point')

    # Convert to WGS84
    polygons_wgs84 = polygons.to_crs('EPSG:4326')
    lines_wgs84 = lines.to_crs('EPSG:4326')
    points_wgs84 = points.to_crs('EPSG:4326')

    print(f'Loaded:')
    print(f'- {len(polygons_wgs84):,} protected areas (polygons)')
    print(f'- {len(lines_wgs84):,} linear features (lines)')
    print(f'- {len(points_wgs84):,} individual sites (points)')

    # Create a comprehensive map
    print('Creating comprehensive archaeological heritage map...')
    fig, ax = plt.subplots(1, 1, figsize=(16, 12))

    # Plot polygons (protected areas) - use transparency
    polygons_wgs84.plot(ax=ax, color='red', alpha=0.2, edgecolor='darkred', linewidth=0.1)

    # Plot lines (linear features)
    lines_wgs84.plot(ax=ax, color='orange', alpha=0.5, linewidth=0.3)

    # Plot points (individual sites) - sample to avoid overwhelming
    sample_points = points_wgs84.sample(n=10000, random_state=42)
    sample_points.plot(ax=ax, color='blue', markersize=0.2, alpha=0.6)

    ax.set_title('Swedish Archaeological Heritage\nRed=Protected Areas, Orange=Linear Features, Blue=Individual Sites', 
                 fontsize=16, fontweight='bold')
    ax.set_xlabel('Longitude', fontsize=12)
    ax.set_ylabel('Latitude', fontsize=12)

    # Add legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='red', alpha=0.3, label=f'Protected Areas ({len(polygons_wgs84):,})'),
        Patch(facecolor='orange', alpha=0.5, label=f'Linear Features ({len(lines_wgs84):,})'),
        Patch(facecolor='blue', alpha=0.6, label=f'Individual Sites (sample of {len(sample_points):,})')
    ]
    ax.legend(handles=legend_elements, loc='upper right', fontsize=10)

    plt.tight_layout()
    plt.savefig('comprehensive_archaeological_map.png', dpi=300, bbox_inches='tight')
    print('Comprehensive map saved as comprehensive_archaeological_map.png')

    total_features = len(polygons_wgs84) + len(lines_wgs84) + len(points_wgs84)
    print(f'\nTotal archaeological features: {total_features:,}')

if __name__ == "__main__":
    create_comprehensive_map()
