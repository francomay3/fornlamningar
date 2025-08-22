#!/usr/bin/env python3
"""
Create an interactive map of archaeological sites.
Generates an HTML file that can be opened in a web browser.
"""

import geopandas as gpd
import pandas as pd
import folium
from src.geodata import FornlamningarData

def create_interactive_map():
    """Create an interactive map with archaeological points."""
    print('Creating interactive archaeological site map...')
    data_handler = FornlamningarData()
    points_gdf = data_handler.load_data(layer='PS_NationalMonuments_point')

    # Convert to WGS84
    points_wgs84 = points_gdf.to_crs('EPSG:4326')

    # Get the center of Sweden
    center_lat = 62.0
    center_lon = 15.0

    # Create a folium map with better styling
    m = folium.Map(location=[center_lat, center_lon], zoom_start=5, 
                   tiles='OpenStreetMap', control_scale=True)

    # Sample points from across Sweden (take every 500th point for better distribution)
    sample_indices = list(range(0, len(points_wgs84), 500))[:800]
    sample_points = points_wgs84.iloc[sample_indices]

    print(f'Adding {len(sample_points)} archaeological sites to the map...')

    # Add points to the map
    for idx, row in sample_points.iterrows():
        if pd.notna(row['sitename']) and row['sitename']:
            # Add marker for named sites
            folium.Marker(
                location=[row.geometry.y, row.geometry.x],
                popup=f"<b>{row['sitename']}</b><br>Type: {row['protectionclassificationvalue']}<br>ID: {row['inspireid']}",
                tooltip=row['sitename'],
                icon=folium.Icon(color='red', icon='info-sign')
            ).add_to(m)
        else:
            # Add small circle for unnamed sites
            folium.CircleMarker(
                location=[row.geometry.y, row.geometry.x],
                radius=2,
                popup=f"ID: {row['inspireid']}<br>Type: {row['protectionclassificationvalue']}",
                color='blue',
                fill=True,
                fillColor='blue',
                fillOpacity=0.6
            ).add_to(m)

    # Add a title
    title_html = '''
    <h3 align="center" style="font-size:16px"><b>Swedish Archaeological Sites</b></h3>
    <p align="center" style="font-size:12px">Red markers = Named sites, Blue dots = Unnamed sites</p>
    '''
    m.get_root().html.add_child(folium.Element(title_html))

    # Save the interactive map
    m.save('archaeological_sites_interactive.html')
    print('Interactive map saved as archaeological_sites_interactive.html')
    print('Open the HTML file in your browser to explore!')

if __name__ == "__main__":
    create_interactive_map()
