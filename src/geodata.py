#!/usr/bin/env python3
"""
Geospatial data handling module for fornlamningar project.
Handles reading, exploring, and modifying geopackage files.
"""

import os
import geopandas as gpd
import pandas as pd
from pathlib import Path
from typing import Optional, List, Dict, Any
import fiona


class FornlamningarData:
    """Class to handle fornlamningar geopackage data."""
    
    def __init__(self, data_path: Optional[str] = None):
        """
        Initialize the data handler.
        
        Args:
            data_path: Path to the geopackage file. If None, uses default location.
        """
        if data_path is None:
            # Default path relative to this module
            current_dir = Path(__file__).parent
            data_path = current_dir / "data" / "fornlamningar_full.gpkg"
        
        self.data_path = Path(data_path)
        self.gdf = None
        self.layers = None
        
    def load_data(self, layer: Optional[str] = None) -> gpd.GeoDataFrame:
        """
        Load data from the geopackage file.
        
        Args:
            layer: Specific layer name to load. If None, loads the first layer.
            
        Returns:
            GeoDataFrame containing the spatial data
        """
        if not self.data_path.exists():
            raise FileNotFoundError(f"Geopackage file not found: {self.data_path}")
        
        if layer is None:
            # Load the first layer
            self.gdf = gpd.read_file(self.data_path)
        else:
            # Load specific layer
            self.gdf = gpd.read_file(self.data_path, layer=layer)
        
        return self.gdf
    
    def get_layers(self) -> List[str]:
        """
        Get list of available layers in the geopackage.
        
        Returns:
            List of layer names
        """
        if not self.data_path.exists():
            raise FileNotFoundError(f"Geopackage file not found: {self.data_path}")
        
        self.layers = fiona.listlayers(str(self.data_path))
        return self.layers
    
    def explore_data(self) -> Dict[str, Any]:
        """
        Explore the loaded data and return basic information.
        
        Returns:
            Dictionary with data exploration results
        """
        if self.gdf is None:
            raise ValueError("No data loaded. Call load_data() first.")
        
        info = {
            'shape': self.gdf.shape,
            'columns': list(self.gdf.columns),
            'geometry_type': self.gdf.geometry.geom_type.unique().tolist(),
            'crs': str(self.gdf.crs),
            'bounds': self.gdf.total_bounds.tolist(),
            'sample_data': self.gdf.head(3).to_dict('records')
        }
        
        return info
    
    def filter_by_geometry_type(self, geom_type: str) -> gpd.GeoDataFrame:
        """
        Filter data by geometry type.
        
        Args:
            geom_type: Geometry type to filter by (e.g., 'Point', 'Polygon', 'LineString')
            
        Returns:
            Filtered GeoDataFrame
        """
        if self.gdf is None:
            raise ValueError("No data loaded. Call load_data() first.")
        
        return self.gdf[self.gdf.geometry.geom_type == geom_type]
    
    def save_layer(self, gdf: gpd.GeoDataFrame, layer_name: str, 
                  output_path: Optional[str] = None) -> None:
        """
        Save a GeoDataFrame as a new layer in the geopackage.
        
        Args:
            gdf: GeoDataFrame to save
            layer_name: Name for the new layer
            output_path: Output path. If None, uses the original file.
        """
        if output_path is None:
            output_path = self.data_path
        
        gdf.to_file(output_path, layer=layer_name, driver='GPKG')
        print(f"Saved layer '{layer_name}' to {output_path}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistical information about the data.
        
        Returns:
            Dictionary with statistical information
        """
        if self.gdf is None:
            raise ValueError("No data loaded. Call load_data() first.")
        
        stats = {
            'total_features': len(self.gdf),
            'geometry_types': self.gdf.geometry.geom_type.value_counts().to_dict(),
            'area_km2': self.gdf.geometry.area.sum() / 1e6 if 'Polygon' in self.gdf.geometry.geom_type.unique() else None,
            'columns_info': {}
        }
        
        # Add column statistics for non-geometry columns
        for col in self.gdf.columns:
            if col != 'geometry':
                if self.gdf[col].dtype in ['object', 'string']:
                    stats['columns_info'][col] = {
                        'type': 'categorical',
                        'unique_values': self.gdf[col].nunique(),
                        'most_common': self.gdf[col].value_counts().head(3).to_dict()
                    }
                else:
                    stats['columns_info'][col] = {
                        'type': 'numerical',
                        'min': float(self.gdf[col].min()) if not self.gdf[col].isna().all() else None,
                        'max': float(self.gdf[col].max()) if not self.gdf[col].isna().all() else None,
                        'mean': float(self.gdf[col].mean()) if not self.gdf[col].isna().all() else None
                    }
        
        return stats


def main():
    """Example usage of the FornlamningarData class."""
    # Initialize data handler
    data_handler = FornlamningarData()
    
    # Get available layers
    try:
        layers = data_handler.get_layers()
        print(f"Available layers: {layers}")
        
        # Load the first layer
        gdf = data_handler.load_data()
        print(f"Loaded data with shape: {gdf.shape}")
        
        # Explore the data
        info = data_handler.explore_data()
        print(f"Data info: {info}")
        
        # Get statistics
        stats = data_handler.get_statistics()
        print(f"Statistics: {stats}")
        
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
