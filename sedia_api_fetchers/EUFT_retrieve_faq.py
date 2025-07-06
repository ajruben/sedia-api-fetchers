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
from typing import Any, List, Union
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

class SEDIA_GET_FAQ(SEDIAPaginatedFetcher):
    """
    A class to fetch FAQ data from the SEDIA API.
    
    This class fetches FAQ index and detailed FAQ information from the Funding & Tenders Portal.
    """
    
    # Endpoint-specific configuration
    API_KEY = "SEDIA_FAQ"
    
    # FAQ type codes
    FAQ_TYPES = {
        'active': ['0'],
        'archived': ['1'],
        'all': ['0', '1']
    }
    
    # FAQ status codes
    FAQ_STATUS = {
        'active': ['0'],
        'archived': ['1'],
        'all': ['0', '1']
    }
    
    def __init__(self, flatten_metadata: bool = True):
        """
        Initializes the fetcher with an API key.
        Args:
            flatten_metadata (bool): Whether to flatten complex metadata structures. Default True.
        """
        super().__init__(flatten_metadata=flatten_metadata)

    def fetch_faq_index(self, programmes=None, faq_type: str = 'all', status: str = 'all') -> pd.DataFrame:
        """
        Fetches FAQ index using base class partitioning logic.
        
        Args:
            programmes: Programme names or IDs. Can be:
                - Single string: 'h2020'
                - Single int: 31045243
                - List of strings: ['h2020', 'horizon']
                - List of ints: [31045243, 43108390]
                - Mixed list: ['h2020', 43108390]
                - None: Fetch all programmes
            faq_type (str): Type of FAQ ('all', 'active', 'archived')
            status (str): Status filter ('all', 'active', 'archived')
        
        Returns:
            pd.DataFrame: FAQ index data
        """
        print(f"Starting fetch for FAQ index...")
        print(f"FAQ type: {faq_type}, Status: {status}")
        
        # Build base query
        base_query = {"bool": {"must": []}}
        
        # Add type filter
        if faq_type in self.FAQ_TYPES:
            base_query["bool"]["must"].append({
                "terms": {"type": self.FAQ_TYPES[faq_type]}
            })
        
        # Add status filter
        if status in self.FAQ_STATUS:
            base_query["bool"]["must"].append({
                "terms": {"status": self.FAQ_STATUS[status]}
            })
        
        # Add programme filter if specified
        if programmes is not None:
            program_ids = self._normalize_programme_input(programmes)
            print(f"Filtering by programme IDs: {program_ids}")
            base_query["bool"]["must"].append({
                "terms": {"programme": [str(pid) for pid in program_ids]}
            })

        sort = {"field": "lastModified", "order": "DESC"}

        # Use base class method - it will handle partitioning if needed
        final_df = self.fetch_all_records_with_partitioning(base_query, sort)
        
        if not final_df.empty:
            print(f"Successfully retrieved {len(final_df)} FAQ records.")
            final_df = self._apply_metadata_flattening(final_df)

        return final_df

    def fetch_faq_details(self, nid_list: Union[str, List[str]]) -> pd.DataFrame:
        """
        Fetches detailed FAQ information for given NIDs.
        
        Args:
            nid_list: NID(s) to fetch details for. Can be:
                - Single string: '755'
                - List of strings: ['755', '12350']
        
        Returns:
            pd.DataFrame: Detailed FAQ data
        """
        if isinstance(nid_list, str):
            nid_list = [nid_list]
        elif isinstance(nid_list, (int, float)):
            nid_list = [str(nid_list)]
        elif isinstance(nid_list, list):
            nid_list = [str(nid) for nid in nid_list]
        else:
            raise ValueError(f"NID list must be string, number, or list, got {type(nid_list)}: {nid_list}")

        print(f"Starting fetch for {len(nid_list)} FAQ detail(s)...")
        
        all_records = []
        
        for nid in tqdm(nid_list, desc="Fetching FAQ details", unit="faq"):
            print(f"Fetching details for FAQ NID: {nid}")
            
            # Build query for specific NID
            query = {
                "bool": {
                    "must": [
                        {"terms": {"nid": [nid]}}
                    ]
                }
            }
            sort = {"field": "lastModified", "order": "DESC"}
            
            data = self.query_api(query, sort, page_size=10)
            
            if data and "results" in data and data["results"]:
                results = data["results"]
                # Add the queried NID to each result for reference
                for result in results:
                    result['queried_nid'] = nid
                all_records.extend(results)
                print(f"  → Found {len(results)} record(s) for NID {nid}")
            else:
                print(f"  → No results found for NID: {nid}")
                # Add an empty record with the NID for tracking
                all_records.append({
                    'queried_nid': nid,
                    'status': 'not_found'
                })

        print(f"\n--- Fetch Complete ---")
        print(f"Successfully retrieved {len(all_records)} FAQ detail records.")

        df = pd.DataFrame(all_records)
        if not df.empty:
            df = self._apply_unwrapping_to_chunk(df)

        df = self._apply_metadata_flattening(df)

        return df

    def get(self, programmes=None, faq_type: str = 'all', status: str = 'all', 
            fetch_details: bool = False, nid_list: Union[str, List[str]] = None, 
            save: bool = False) -> pd.DataFrame:
        """
        Comprehensive method that fetches FAQ data.

        Args:
            programmes: Programme names or IDs. Can be:
                - Single string: 'h2020'
                - Single int: 31045243
                - List of strings: ['h2020', 'horizon']
                - List of ints: [31045243, 43108390]
                - Mixed list: ['h2020', 43108390]
                - None: Fetch all programmes
            faq_type (str): Type of FAQ ('all', 'active', 'archived')
            status (str): Status filter ('all', 'active', 'archived')
            fetch_details (bool): Whether to fetch detailed FAQ content
            nid_list: Specific NIDs to fetch details for (overrides other filters if provided)
            save (bool): Whether to save the final result to file

        Returns:
            pd.DataFrame: Fully processed FAQ data
        """
        if nid_list is not None:
            # Fetch specific FAQ details
            print(f"Starting comprehensive fetch for specific FAQ details...")
            
            # Temporarily disable flattening to get raw records first
            original_flatten_setting = self.flatten_metadata
            self.flatten_metadata = False

            try:
                initial_df = self.fetch_faq_details(nid_list)
                
                if initial_df.empty:
                    print("No initial records found.")
                    return pd.DataFrame()

                print(f"Retrieved {len(initial_df)} initial FAQ detail records.")

                # Apply flattening if requested
                if original_flatten_setting:
                    print("Applying comprehensive flattening to FAQ records...")
                    final_df = self._apply_metadata_flattening(initial_df)
                else:
                    final_df = initial_df

                final_df = self._clean_final_data(final_df)

                print(f"Comprehensive processing complete! Final dataset: {len(final_df)} records, {len(final_df.columns) if not final_df.empty else 0} columns")

                # Save the final processed data
                if not final_df.empty and save:
                    try:
                        self._save_data(final_df, "faq_details")
                    except Exception as e:
                        print(f"[ERROR] Could not save final output: {e}")

                return final_df

            finally:
                # Restore original settings
                self.flatten_metadata = original_flatten_setting
        
        else:
            # Fetch FAQ index
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
                initial_df = self.fetch_faq_index(programmes, faq_type, status)

                if initial_df.empty:
                    print("No initial records found.")
                    return pd.DataFrame()

                print(f"Retrieved {len(initial_df)} initial FAQ records.")

                # If fetch_details is True, extract NIDs and fetch details
                if fetch_details and 'nid' in initial_df.columns:
                    print("Fetching detailed FAQ content...")
                    nids = initial_df['nid'].dropna().unique().tolist()
                    if nids:
                        details_df = self.fetch_faq_details(nids)
                        if not details_df.empty:
                            # Merge index with details
                            initial_df = pd.merge(initial_df, details_df, on='nid', how='left', suffixes=('', '_detail'))

                # Apply flattening if requested
                if original_flatten_setting:
                    print("Applying comprehensive flattening to FAQ records...")
                    final_df = self._apply_metadata_flattening(initial_df)
                else:
                    final_df = initial_df

                final_df = self._clean_final_data(final_df)

                print(f"Comprehensive processing complete! Final dataset: {len(final_df)} records, {len(final_df.columns) if not final_df.empty else 0} columns")

                # Save the final processed data
                if not final_df.empty and save:
                    try:
                        prog_suffix = '_'.join(map(str, program_ids)) if program_ids else 'all'
                        self._save_data(final_df, "faq_data", 
                                      programmes=prog_suffix, 
                                      faq_type=faq_type, 
                                      status=status)
                    except Exception as e:
                        print(f"[ERROR] Could not save final output: {e}")

                return final_df

            finally:
                # Restore original settings
                self.flatten_metadata = original_flatten_setting


# --- Example Usage ---
if __name__ == '__main__':
    # Create fetcher for FAQ data
    fetcher = SEDIA_GET_FAQ(
        flatten_metadata=True
    )
    
    # Example 1: Get FAQ index for H2020
    faq_index = fetcher.get('h2020', faq_type='all', status='all', save=True)
    
    # Example 2: Get specific FAQ details
    faq_details = fetcher.get(nid_list=['755'], save=True)
    
    print('') 