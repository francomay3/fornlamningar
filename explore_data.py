#!/usr/bin/env python3
"""
Explore and analyze the fornlamningar archaeological data.
Provides detailed information about the structure and content of the geopackage.
"""

import geopandas as gpd
import pandas as pd
from src.geodata import FornlamningarData

def explore_data():
    """Explore the structure and content of the archaeological data."""
    print('Exploring fornlamningar archaeological data...')
    print('=' * 70)
    
    data_handler = FornlamningarData()
    
    # Get available layers
    layers = data_handler.get_layers()
    print(f'Available layers: {layers}')
    print()
    
    # Explore each layer
    for layer in layers:
        if layer != 'example_subset':  # Skip our test layer
            print(f'Layer: {layer}')
            print('-' * 50)
            
            # Load data
            gdf = data_handler.load_data(layer=layer)
            
            print(f'Features: {len(gdf):,}')
            print(f'Geometry types: {gdf.geometry.geom_type.unique()}')
            print(f'CRS: {gdf.crs}')
            print(f'Columns: {list(gdf.columns)}')
            
            # Show sample data
            if len(gdf) > 0:
                print('\nSample features:')
                sample = gdf.head(2)
                for idx, row in sample.iterrows():
                    print(f'  Feature {idx}:')
                    for col in gdf.columns:
                        if col != 'geometry':
                            value = row[col]
                            if pd.notna(value):
                                print(f'    {col}: {value}')
                    print()
            
            print('=' * 70)

def analyze_named_sites():
    """Analyze sites that have names."""
    print('\nAnalyzing named archaeological sites...')
    print('=' * 70)
    
    data_handler = FornlamningarData()
    
    # Check points layer for named sites
    points_gdf = data_handler.load_data(layer='PS_NationalMonuments_point')
    named_sites = points_gdf[points_gdf['sitename'].notna()]
    
    print(f'Total point sites: {len(points_gdf):,}')
    print(f'Sites with names: {len(named_sites):,}')
    print(f'Percentage with names: {len(named_sites)/len(points_gdf)*100:.1f}%')
    
    if len(named_sites) > 0:
        print('\nSample named sites:')
        for name in named_sites['sitename'].head(20):
            print(f'  - {name}')
    
    # Check polygons layer for named sites
    polygons_gdf = data_handler.load_data(layer='PS_NationalMonuments_poly')
    named_areas = polygons_gdf[polygons_gdf['sitename'].notna()]
    
    print(f'\nTotal protected areas: {len(polygons_gdf):,}')
    print(f'Areas with names: {len(named_areas):,}')
    print(f'Percentage with names: {len(named_areas)/len(polygons_gdf)*100:.1f}%')

def analyze_data_quality():
    """Analyze data quality and completeness."""
    print('\nData quality analysis...')
    print('=' * 70)
    
    data_handler = FornlamningarData()
    
    for layer in ['PS_NationalMonuments_point', 'PS_NationalMonuments_poly', 'PS_NationalMonuments_line']:
        print(f'\nLayer: {layer}')
        gdf = data_handler.load_data(layer=layer)
        
        print(f'Total features: {len(gdf):,}')
        print(f'Valid geometries: {gdf.geometry.is_valid.sum():,}')
        print(f'Invalid geometries: {(~gdf.geometry.is_valid).sum():,}')
        
        # Check for null values in each column
        for col in gdf.columns:
            if col != 'geometry':
                null_count = gdf[col].isna().sum()
                print(f'  {col}: {null_count:,} null values ({null_count/len(gdf)*100:.1f}%)')

if __name__ == "__main__":
    explore_data()
    analyze_named_sites()
    analyze_data_quality()
