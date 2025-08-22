#!/usr/bin/env python3
"""
Visualize archaeological points data from the fornlamningar geopackage.
Creates a map of individual archaeological sites across Sweden.
"""

import geopandas as gpd
import matplotlib.pyplot as plt
from src.geodata import FornlamningarData

def visualize_points():
    """Create a map of individual archaeological sites."""
    print('Loading archaeological point data...')
    data_handler = FornlamningarData()
    points_gdf = data_handler.load_data(layer='PS_NationalMonuments_point')

    print(f'Loaded {len(points_gdf):,} individual archaeological sites!')

    # Convert to WGS84 for web-compatible coordinates
    points_wgs84 = points_gdf.to_crs('EPSG:4326')

    # Create a map with the points
    print('Creating point distribution map...')
    fig, ax = plt.subplots(1, 1, figsize=(15, 10))

    # Plot points with better styling
    points_wgs84.plot(ax=ax, color='darkred', markersize=0.3, alpha=0.6)

    ax.set_title('Individual Archaeological Sites in Sweden\n(219,639 sites)', fontsize=16, fontweight='bold')
    ax.set_xlabel('Longitude', fontsize=12)
    ax.set_ylabel('Latitude', fontsize=12)

    # Add a text box with statistics
    stats_text = f'Total Sites: {len(points_wgs84):,}\nNamed Sites: {points_wgs84["sitename"].notna().sum():,}\nPercentage Named: {points_wgs84["sitename"].notna().sum()/len(points_wgs84)*100:.1f}%'
    ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=10, 
            verticalalignment='top', bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    plt.tight_layout()
    plt.savefig('archaeological_points_map.png', dpi=300, bbox_inches='tight')
    print('Point map saved as archaeological_points_map.png')

    # Show some statistics
    print(f'\nPoint data statistics:')
    print(f'- Total sites: {len(points_wgs84):,}')
    print(f'- Sites with names: {points_wgs84["sitename"].notna().sum():,}')
    print(f'- Percentage with names: {points_wgs84["sitename"].notna().sum()/len(points_wgs84)*100:.1f}%')
    print(f'- Geographic bounds: {points_wgs84.total_bounds}')

    # Show some named sites
    named_sites = points_wgs84[points_wgs84['sitename'].notna()]
    if len(named_sites) > 0:
        print(f'\nSample named sites:')
        for name in named_sites['sitename'].head(10):
            print(f'- {name}')

if __name__ == "__main__":
    visualize_points()
