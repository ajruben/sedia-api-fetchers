import requests
import pandas as pd
import json
import os
import time
import pathlib
import glob
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import math
from tqdm.auto import tqdm
from datetime import datetime, timedelta
import numpy as np
import re
from typing import Any, List, Union, Dict
try:
    from helpers.functions import Functions
except ImportError:
    # Fallback for when running as script
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent))
    from helpers.functions import Functions
try:
    from . import SEDIABaseFetcher
except ImportError:
    # Fallback for when running as script
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent))
    from __init__ import SEDIABaseFetcher

class SEDIA_GET_FACETS(SEDIABaseFetcher):
    """
    A class to fetch facet data from the SEDIA Facet API.
    
    This class fetches facet information which provides aggregated statistics
    and categorizations across the SEDIA database.
    """
    
    # Endpoint-specific configuration
    API_KEY = "SEDIA_NONH2020_PROD"
    
    def __init__(self, flatten_metadata: bool = False):
        """
        Initializes the fetcher with an API key.
        Args:
            flatten_metadata (bool): Whether to flatten complex metadata structures. Default False for facets.
        """
        super().__init__(flatten_metadata=flatten_metadata)
        
        # Set up facet API URL
        self.FACET_API_BASE = f"{self.SCHEME}{self.HOST}/search-api/prod/rest/facet"

    def query_api(self, query: dict, sort: dict = None, page_num: int = 1, page_size: int = 100) -> dict:
        """
        Override for facet-specific API calls.
        
        Args:
            query: Facet query parameters
            sort: Not used for facet API (uses sort parameter in headers)
            page_num: Not used for facet API
            page_size: Not used for facet API
            
        Returns:
            dict: JSON response from the facet API
        """
        # Facet API uses different headers structure
        headers = {
            "apiKey": self.API_KEY,
            "text": "***",
            "sort": "REVERSE_DOCUMENT_COUNT"
        }
        
        # Form data for facet API
        form_data = {
            "query": ("blob", json.dumps(query), "application/json"),
            "languages": ("blob", json.dumps(["en"]), "application/json"),
        }
        
        try:
            response = self.session.post(self.FACET_API_BASE, params=headers, files=form_data)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"An API error occurred for facets: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response content: {e.response.text}")
            return {}

    def fetch_facets(self, query: dict = None, programmes: list = None) -> dict:
        """
        Fetches facet data for given query and programmes.
        
        Args:
            query (dict): Custom query parameters. If None, uses default empty query.
            programmes: Programme names or IDs to filter by. Can be:
                - Single string: 'h2020'
                - List of strings: ['h2020', 'horizon']
                - None: Fetch all programmes
        
        Returns:
            dict: Raw facet data from API
        """
        print("Starting facet data retrieval...")
        
        # Build base query
        if query is None:
            base_query = {"bool": {"must": []}}
        else:
            base_query = query.copy()
        
        # Add programme filter if specified
        if programmes is not None:
            program_ids = self._normalize_programme_input(programmes)
            print(f"Filtering by programme IDs: {program_ids}")
            
            # Ensure we have a proper bool/must structure
            if "bool" not in base_query:
                base_query = {"bool": {"must": []}}
            if "must" not in base_query["bool"]:
                base_query["bool"]["must"] = []
            
            base_query["bool"]["must"].append({
                "terms": {"programId": [str(pid) for pid in program_ids]}
            })
        else:
            print("Fetching facets for all programmes")

        print(f"Query: {json.dumps(base_query, indent=2)}")
        
        # Fetch facet data
        facet_data = self.query_api(base_query)
        
        if facet_data:
            print(f"✅ Successfully retrieved facet data")
            # Add metadata about the query
            facet_data['_query_metadata'] = {
                'query_used': base_query,
                'programmes_filtered': programmes,
                'fetch_timestamp': datetime.now().isoformat(),
                'api_endpoint': 'facet'
            }
        else:
            print("❌ No facet data retrieved")
        
        return facet_data

    def _save_facet_data(self, facet_data: dict, filename_prefix: str = "facet_data", **kwargs) -> str:
        """
        Save facet data to JSON file with timestamped filename.
        
        Args:
            facet_data (dict): Facet data to save
            filename_prefix (str): Prefix for the filename
            **kwargs: Additional parameters for filename construction
            
        Returns:
            str: Path to saved file
        """
        if not facet_data:
            raise ValueError("Cannot save empty facet data")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Construct filename with parameters
        filename_parts = [filename_prefix]
        for key, value in kwargs.items():
            if value is not None:
                if isinstance(value, list):
                    filename_parts.append('_'.join(map(str, value)))
                else:
                    filename_parts.append(str(value))
        
        filename_parts.append(timestamp)
        final_filename = '_'.join(filename_parts) + '.json'
        
        output_file = str(self.DATA_DIR / final_filename)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(facet_data, f, indent=2, ensure_ascii=False)
        
        file_size = os.path.getsize(output_file) / (1024*1024)
        print(f"Facet data size: {file_size:.1f} MB")
        print(f"[SUCCESS] facet data saved to {output_file}")
        
        return output_file

    def get(self, programmes=None, query: dict = None, save: bool = False) -> dict:
        """
        Comprehensive method that fetches facet data.

        Args:
            programmes: Programme names or IDs. Can be:
                - Single string: 'h2020'
                - List of strings: ['h2020', 'horizon']
                - None: Fetch all programmes
            query (dict): Custom query parameters
            save (bool): Whether to save the result to file

        Returns:
            dict: Facet data
        """
        if programmes is not None:
            program_ids = self._normalize_programme_input(programmes)
            print(f"Starting facet fetch for programme IDs: {program_ids}...")
        else:
            program_ids = None
            print("Starting facet fetch for all programmes...")

        try:
            facet_data = self.fetch_facets(query=query, programmes=programmes)

            if not facet_data:
                print("No facet data retrieved.")
                return {}

            print("Facet data retrieval complete!")

            # Save the facet data
            if save:
                try:
                    if program_ids:
                        prog_suffix = '_'.join(map(str, program_ids))
                        self._save_facet_data(facet_data, programmes=prog_suffix)
                    else:
                        self._save_facet_data(facet_data, programmes='all')
                except Exception as e:
                    print(f"[ERROR] Could not save facet data: {e}")

            return facet_data

        except Exception as e:
            print(f"❌ Facet fetch failed: {e}")
            return {}


# --- Example Usage ---
if __name__ == '__main__':
    # Create fetcher for facet data
    fetcher = SEDIA_GET_FACETS(flatten_metadata=False)
    
    # Example 1: Get facets for all programmes
    all_facets = fetcher.get(save=True)
