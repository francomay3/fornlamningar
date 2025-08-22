#!/usr/bin/env python3
"""
Regional analysis of archaeological sites in Sweden.
Analyzes and visualizes archaeological sites by different regions.
"""

import geopandas as gpd
import matplotlib.pyplot as plt
from src.geodata import FornlamningarData

def analyze_regions():
    """Analyze archaeological sites by region."""
    print('Analyzing archaeological sites by region...')
    
    data_handler = FornlamningarData()
    
    # Load point data
    points_gdf = data_handler.load_data(layer='PS_NationalMonuments_point')
    points_wgs84 = points_gdf.to_crs('EPSG:4326')
    
    # Define regions (approximate bounds)
    regions = {
        'Stockholm': [17.5, 59.0, 18.5, 60.0],
        'Gothenburg': [11.5, 57.5, 12.5, 58.5],
        'Malmö': [12.8, 55.3, 13.2, 55.8],
        'Uppsala': [17.0, 59.7, 18.0, 60.2],
        'Västerås': [16.0, 59.5, 16.8, 59.8],
        'Örebro': [15.0, 59.2, 15.4, 59.4],
        'Linköping': [15.4, 58.3, 15.8, 58.5]
    }
    
    print('\nRegional analysis:')
    print('=' * 60)
    
    for region_name, bounds in regions.items():
        # Filter data for region
        region_gdf = points_wgs84.cx[bounds[0]:bounds[2], bounds[1]:bounds[3]]
        
        print(f'{region_name}:')
        print(f'  Total sites: {len(region_gdf):,}')
        print(f'  Named sites: {region_gdf["sitename"].notna().sum():,}')
        
        # Show some named sites
        named_sites = region_gdf[region_gdf['sitename'].notna()]
        if len(named_sites) > 0:
            print(f'  Sample sites:')
            for name in named_sites['sitename'].head(3):
                print(f'    - {name}')
        print()

def create_regional_maps():
    """Create maps for different regions."""
    print('Creating regional maps...')
    
    data_handler = FornlamningarData()
    points_gdf = data_handler.load_data(layer='PS_NationalMonuments_point')
    points_wgs84 = points_gdf.to_crs('EPSG:4326')
    
    # Stockholm area
    stockholm_bounds = [17.5, 59.0, 18.5, 60.0]
    stockholm_gdf = points_wgs84.cx[stockholm_bounds[0]:stockholm_bounds[2], 
                                   stockholm_bounds[1]:stockholm_bounds[3]]
    
    fig, ax = plt.subplots(1, 1, figsize=(12, 10))
    stockholm_gdf.plot(ax=ax, color='darkred', markersize=1.5, alpha=0.7)
    ax.set_title('Archaeological Sites in Stockholm Area', fontsize=14, fontweight='bold')
    ax.set_xlabel('Longitude')
    ax.set_ylabel('Latitude')
    
    # Add statistics
    stats_text = f'Total Sites: {len(stockholm_gdf):,}\nNamed Sites: {stockholm_gdf["sitename"].notna().sum():,}'
    ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=10, 
            verticalalignment='top', bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    
    plt.tight_layout()
    plt.savefig('stockholm_archaeological_sites.png', dpi=300, bbox_inches='tight')
    print('Stockholm map saved as stockholm_archaeological_sites.png')
    
    # Gothenburg area
    gothenburg_bounds = [11.5, 57.5, 12.5, 58.5]
    gothenburg_gdf = points_wgs84.cx[gothenburg_bounds[0]:gothenburg_bounds[2], 
                                    gothenburg_bounds[1]:gothenburg_bounds[3]]
    
    fig, ax = plt.subplots(1, 1, figsize=(12, 10))
    gothenburg_gdf.plot(ax=ax, color='darkblue', markersize=1.5, alpha=0.7)
    ax.set_title('Archaeological Sites in Gothenburg Area', fontsize=14, fontweight='bold')
    ax.set_xlabel('Longitude')
    ax.set_ylabel('Latitude')
    
    # Add statistics
    stats_text = f'Total Sites: {len(gothenburg_gdf):,}\nNamed Sites: {gothenburg_gdf["sitename"].notna().sum():,}'
    ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=10, 
            verticalalignment='top', bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    
    plt.tight_layout()
    plt.savefig('gothenburg_archaeological_sites.png', dpi=300, bbox_inches='tight')
    print('Gothenburg map saved as gothenburg_archaeological_sites.png')

if __name__ == "__main__":
    analyze_regions()
    create_regional_maps()
