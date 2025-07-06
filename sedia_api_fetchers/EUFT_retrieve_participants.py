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

class SEDIA_GET_PARTICIPANTS(SEDIAPaginatedFetcher):
    """
    A class to fetch participant/organization data from the SEDIA API, handling pagination limits
    by using the same robust approach as the projects fetcher.

    This class fetches ORGANISATION and PERSON type records from specified programmes.
    """
    
    # Endpoint-specific configuration
    API_KEY = "SEDIA_PERSON"
    
    def __init__(self, flatten_metadata: bool = True):
        """
        Initializes the fetcher with an API key.
        Args:
            flatten_metadata (bool): Whether to flatten complex metadata structures. Default True.
        """
        super().__init__(flatten_metadata=flatten_metadata)
        
        # Additional endpoint-specific setup can go here
        self.FACET_API_BASE = f"{self.SCHEME}{self.HOST}/search-api/prod/rest/facet"



    def fetch_all_records(self, programmes) -> pd.DataFrame:
        """
        Fetches all participant records for given programmes using base class logic.
        
        Args:
            programmes: Programme names or IDs. Can be:
                - Single string: 'h2020'
                - Single int: 31045243
                - List of strings: ['h2020', 'horizon']
                - List of ints: [31045243, 43108390]
                - Mixed list: ['h2020', 43108390]
        """
        program_ids = self._normalize_programme_input(programmes)
        print(f"Starting fetch for programme IDs: {program_ids}...")
        
        # Build query for ORGANISATION and PERSON types
        base_query = {
            "bool": {
                "must": [
                    {"terms": {"type": ["ORGANISATION", "PERSON"]}},
                    {"terms": {"programmes": [str(pid) for pid in program_ids]}}
                ]
            }
        }
        sort = {"field": "lastModified", "order": "DESC"}

        # Use base class method - it will handle partitioning if needed
        # For participants without es_SortDate, it will fall back to basic pagination
        final_df = self.fetch_all_records_with_partitioning(base_query, sort)
        
        if not final_df.empty:
            print(f"Successfully retrieved {len(final_df)} participant records.")
            final_df = self._apply_metadata_flattening(final_df)

        return final_df

    def get(self, programmes, save: bool = False) -> pd.DataFrame:
        """
        Comprehensive method that fetches all participant records for programme(s).

        Args:
            programmes: Programme names or IDs. Can be:
                - Single string: 'h2020'
                - Single int: 31045243
                - List of strings: ['h2020', 'horizon']
                - List of ints: [31045243, 43108390]
                - Mixed list: ['h2020', 43108390]
            save (bool): Whether to save the final result to file

        Returns:
            pd.DataFrame: Fully processed participant data
        """
        program_ids = self._normalize_programme_input(programmes)
        print(f"Starting comprehensive fetch and processing for programme IDs: {program_ids}...")
        print(f"🔍 DEBUG: Programme IDs being processed: {program_ids}")
        print(f"🔍 DEBUG: Number of programmes: {len(program_ids)}")

        # Temporarily disable flattening to get raw records first
        original_flatten_setting = self.flatten_metadata
        self.flatten_metadata = False

        try:
            initial_df = self.fetch_all_records(programmes)

            if initial_df.empty:
                print("No initial records found.")
                return pd.DataFrame()

            print(f"Retrieved {len(initial_df)} initial participant records.")

            # Debug: Check programme distribution
            if not initial_df.empty and 'programmes' in initial_df.columns:
                program_distribution = {}
                for _, row in initial_df.iterrows():
                    progs = row.get('programmes', [])
                    if isinstance(progs, list):
                        for pid in progs:
                            program_distribution[str(pid)] = program_distribution.get(str(pid), 0) + 1
                    else:
                        program_distribution[str(progs)] = program_distribution.get(str(progs), 0) + 1
                print(f"Initial programme distribution: {program_distribution}")

            # Apply flattening if requested
            if original_flatten_setting:
                print("Applying comprehensive flattening to participant records...")
                final_df = self._apply_metadata_flattening(initial_df)
            else:
                final_df = initial_df

            final_df = self._clean_final_data(final_df)

            print(f"Comprehensive processing complete! Final dataset: {len(final_df)} records, {len(final_df.columns) if not final_df.empty else 0} columns")

            # Save the final processed data
            if not final_df.empty and save:
                try:
                    prog_suffix = '_'.join(map(str, program_ids))
                    self._save_data(final_df, "participant_data", programmes=prog_suffix)
                except Exception as e:
                    print(f"[ERROR] Could not save final output: {e}")

            return final_df

        finally:
            # Restore original settings
            self.flatten_metadata = original_flatten_setting


# --- Example Usage ---
if __name__ == '__main__':
    # Create fetcher for participant data
    fetcher = SEDIA_GET_PARTICIPANTS(
        flatten_metadata=True
    )
    data = fetcher.get('edf', save=True)
    print('')
