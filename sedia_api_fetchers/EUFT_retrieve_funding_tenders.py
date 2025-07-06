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
from typing import Any
try:
    from helpers.functions import Functions
except ImportError:
    # Fallback for when running as script
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent))
    from helpers.functions import Functions
try:
    from . import SEDIAPaginatedFetcher
except ImportError:
    # Fallback for when running as script
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent))
    from __init__ import SEDIAPaginatedFetcher

class SEDIA_GET_FUNDING_TENDERS(SEDIAPaginatedFetcher):
    """
    A class to fetch funding & tenders data (calls for proposals and tenders) from the SEDIA API.
    
    This class fetches grant opportunities, tenders, and related metadata from specified programmes.
    """
    
    # Endpoint-specific configuration
    API_KEY = "SEDIA"
    
    # Status codes for funding & tenders
    STATUS_CODES = {
        'open': ['31094501', '31094502'],
        'closed': ['31094503'],
        'all': ['31094501', '31094502', '31094503']
    }
    
    # Type codes for funding & tenders
    TYPE_CODES = {
        'tenders': ['0'],
        'grants': ['1', '2', '8'],
        'all': ['0', '1', '2', '8']
    }
    
    def __init__(self, flatten_metadata: bool = True):
        """
        Initializes the fetcher with an API key.
        Args:
            flatten_metadata (bool): Whether to flatten complex metadata structures. Default True.
        """
        super().__init__(flatten_metadata=flatten_metadata)
        
        # Additional endpoint-specific setup
        self.FACET_API_BASE = f"{self.SCHEME}{self.HOST}/search-api/prod/rest/facet"

    def fetch_all_records(self, programmes=None, funding_type: str = 'all', status: str = 'all', **kwargs) -> pd.DataFrame:
        """
        Fetches all funding & tenders records using base class partitioning logic.
        
        Args:
            programmes: Programme names or IDs. Can be:
                - Single string: 'h2020'
                - Single int: 31045243
                - List of strings: ['h2020', 'horizon']
                - List of ints: [31045243, 43108390]
                - Mixed list: ['h2020', 43108390]
                - None: Fetch all programmes
            funding_type (str): Type of funding ('all', 'grants', 'tenders')
            status (str): Status filter ('all', 'open', 'closed')
            **kwargs: Additional query parameters
        """
        print(f"Starting fetch for funding & tenders...")
        print(f"Funding type: {funding_type}, Status: {status}")
        
        # Build base query
        base_query = {"bool": {"must": []}}
        
        # Add type filter
        if funding_type in self.TYPE_CODES:
            base_query["bool"]["must"].append({
                "terms": {"type": self.TYPE_CODES[funding_type]}
            })
        
        # Add status filter
        if status in self.STATUS_CODES:
            base_query["bool"]["must"].append({
                "terms": {"status": self.STATUS_CODES[status]}
            })
        
        # Add programme filter if specified
        if programmes is not None:
            program_ids = self._normalize_programme_input(programmes)
            print(f"Filtering by programme IDs: {program_ids}")
            base_query["bool"]["must"].append({
                "terms": {"frameworkProgramme": [str(pid) for pid in program_ids]}
            })
        
        # Add any additional filters from kwargs
        for key, value in kwargs.items():
            if isinstance(value, list):
                base_query["bool"]["must"].append({"terms": {key: value}})
            else:
                base_query["bool"]["must"].append({"term": {key: value}})

        sort = {"field": "lastModified", "order": "DESC"}

        # Use base class method - it will handle partitioning if needed
        final_df = self.fetch_all_records_with_partitioning(base_query, sort)
        
        if not final_df.empty:
            print(f"Successfully retrieved {len(final_df)} funding & tenders records.")
            final_df = self._apply_metadata_flattening(final_df)

        return final_df

    def get(self, programmes=None, funding_type: str = 'all', status: str = 'all', save: bool = False, **kwargs) -> pd.DataFrame:
        """
        Comprehensive method that fetches all funding & tenders records.

        Args:
            programmes: Programme names or IDs. Can be:
                - Single string: 'h2020'
                - Single int: 31045243
                - List of strings: ['h2020', 'horizon']
                - List of ints: [31045243, 43108390]
                - Mixed list: ['h2020', 43108390]
                - None: Fetch all programmes
            funding_type (str): Type of funding ('all', 'grants', 'tenders')
            status (str): Status filter ('all', 'open', 'closed')
            save (bool): Whether to save the final result to file
            **kwargs: Additional query parameters

        Returns:
            pd.DataFrame: Fully processed funding & tenders data
        """
        if programmes is not None:
            program_ids = self._normalize_programme_input(programmes)
            print(f"Starting comprehensive fetch for programme IDs: {program_ids}...")
        else:
            program_ids = None
            print("Starting comprehensive fetch for all programmes...")

        # Temporarily disable flattening to get raw records first
        original_flatten_setting = self.flatten_metadata
        self.flatten_metadata = False

        try:
            initial_df = self.fetch_all_records(programmes, funding_type, status, **kwargs)

            if initial_df.empty:
                print("No initial records found.")
                return pd.DataFrame()

            print(f"Retrieved {len(initial_df)} initial funding & tenders records.")

            # Apply flattening if requested
            if original_flatten_setting:
                print("Applying comprehensive flattening to funding & tenders records...")
                final_df = self._apply_metadata_flattening(initial_df)
            else:
                final_df = initial_df

            final_df = self._clean_final_data(final_df)

            print(f"Comprehensive processing complete! Final dataset: {len(final_df)} records, {len(final_df.columns) if not final_df.empty else 0} columns")

            # Save the final processed data
            if not final_df.empty and save:
                try:
                    prog_suffix = '_'.join(map(str, program_ids)) if program_ids else 'all'
                    self._save_data(final_df, "funding_tenders_data", 
                                  programmes=prog_suffix, 
                                  funding_type=funding_type, 
                                  status=status)
                except Exception as e:
                    print(f"[ERROR] Could not save final output: {e}")

            return final_df

        finally:
            # Restore original settings
            self.flatten_metadata = original_flatten_setting


# --- Example Usage ---
if __name__ == '__main__':
    # Create fetcher for funding & tenders data
    fetcher = SEDIA_GET_FUNDING_TENDERS(
        flatten_metadata=True
    )
    
    # Example: Get all open grants for Horizon Europe
    data = fetcher.get('horizon', funding_type='grants', status='open', save=True)
    print('') 