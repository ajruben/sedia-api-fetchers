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
    from . import SEDIASimpleFetcher
except ImportError:
    # Fallback for when running as script
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent))
    from __init__ import SEDIASimpleFetcher

class SEDIA_GET_TOPICS(SEDIASimpleFetcher):
    """
    A class to fetch topic details from the SEDIA API.
    
    This class fetches detailed information about specific topics using their identifiers.
    """
    
    # Endpoint-specific configuration
    API_KEY = "SEDIA"
    
    def __init__(self, flatten_metadata: bool = True):
        """
        Initializes the fetcher with an API key.
        Args:
            flatten_metadata (bool): Whether to flatten complex metadata structures. Default True.
        """
        super().__init__(flatten_metadata=flatten_metadata)



    def _normalize_topic_input(self, topics) -> List[str]:
        """
        Normalize topic input to a list of topic identifiers.
        
        Args:
            topics: Can be:
                - Single string: 'HORIZON-CL3-2022-BM-01-01'
                - List of strings: ['HORIZON-CL3-2022-BM-01-01', 'HORIZON-CL4-2022-RESILIENCE-01-08']
                
        Returns:
            List[str]: List of topic identifiers
        """
        if isinstance(topics, str):
            return [topics]
        elif isinstance(topics, list):
            return [str(topic) for topic in topics]
        else:
            raise ValueError(f"Topics must be string or list of strings, got {type(topics)}: {topics}")

    def query_api(self, query: dict, sort: dict = None, page_num: int = 1, page_size: int = 100) -> dict:
        """
        Override the base query_api method for topic-specific API calls.
        
        Args:
            query: For topics, this should contain the topic identifier
            sort: Not used for topic API
            page_num: Not used for topic API
            page_size: Not used for topic API
            
        Returns:
            dict: JSON response from the search API
        """
        # Extract topic identifier from query
        topic_identifier = query.get('topic_identifier', '')
        
        params = {
            "apiKey": self.API_KEY,
            "text": f'"{topic_identifier}"'
        }
        
        try:
            response = self.session.get(self.SEARCH_API_BASE, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"An API error occurred for topic {topic_identifier}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response content: {e.response.text}")
            return {}
    
    def query_topic_api(self, topic_identifier: str) -> dict:
        """
        Convenience method for topic queries - delegates to query_api.
        
        Args:
            topic_identifier (str): The topic identifier to search for
            
        Returns:
            dict: JSON response from the search API
        """
        return self.query_api({'topic_identifier': topic_identifier})



    def fetch_topic_details(self, topic_identifiers: Union[str, List[str]]) -> pd.DataFrame:
        """
        Fetches detailed information for given topic identifiers.
        
        Args:
            topic_identifiers: Topic identifier(s). Can be:
                - Single string: 'HORIZON-CL3-2022-BM-01-01'
                - List of strings: ['HORIZON-CL3-2022-BM-01-01', 'HORIZON-CL4-2022-RESILIENCE-01-08']
        
        Returns:
            pd.DataFrame: Topic details data
        """
        topic_list = self._normalize_topic_input(topic_identifiers)
        print(f"Starting fetch for {len(topic_list)} topic(s)...")
        
        all_records = []
        
        for topic_id in tqdm(topic_list, desc="Fetching topic details", unit="topic"):
            print(f"Fetching details for topic: {topic_id}")
            
            data = self.query_topic_api(topic_id)
            
            if data and "results" in data and data["results"]:
                results = data["results"]
                # Add the queried topic identifier to each result for reference
                for result in results:
                    result['queried_topic_identifier'] = topic_id
                all_records.extend(results)
                print(f"  → Found {len(results)} record(s) for {topic_id}")
            else:
                print(f"  → No results found for topic: {topic_id}")
                # Add an empty record with the topic identifier for tracking
                all_records.append({
                    'queried_topic_identifier': topic_id,
                    'status': 'not_found'
                })

        print(f"\n--- Fetch Complete ---")
        print(f"Successfully retrieved {len(all_records)} topic detail records.")

        df = pd.DataFrame(all_records)
        if not df.empty:
            df = self._apply_unwrapping_to_chunk(df)

        df = self._apply_metadata_flattening(df)

        return df

    def get(self, topic_identifiers: Union[str, List[str]], save: bool = False) -> pd.DataFrame:
        """
        Comprehensive method that fetches topic details.

        Args:
            topic_identifiers: Topic identifier(s). Can be:
                - Single string: 'HORIZON-CL3-2022-BM-01-01'
                - List of strings: ['HORIZON-CL3-2022-BM-01-01', 'HORIZON-CL4-2022-RESILIENCE-01-08']
            save (bool): Whether to save the final result to file

        Returns:
            pd.DataFrame: Fully processed topic details data
        """
        topic_list = self._normalize_topic_input(topic_identifiers)
        print(f"Starting comprehensive fetch for {len(topic_list)} topic(s)...")

        # Temporarily disable flattening to get raw records first
        original_flatten_setting = self.flatten_metadata
        self.flatten_metadata = False

        try:
            initial_df = self.fetch_topic_details(topic_identifiers)

            if initial_df.empty:
                print("No initial records found.")
                return pd.DataFrame()

            print(f"Retrieved {len(initial_df)} initial topic detail records.")

            # Apply flattening if requested
            if original_flatten_setting:
                print("Applying comprehensive flattening to topic records...")
                final_df = self._apply_metadata_flattening(initial_df)
            else:
                final_df = initial_df

            final_df = self._clean_final_data(final_df)

            print(f"Comprehensive processing complete! Final dataset: {len(final_df)} records, {len(final_df.columns) if not final_df.empty else 0} columns")

            # Save the final processed data
            if not final_df.empty and save:
                try:
                    topic_suffix = '_'.join(topic_list[:3])  # Use first 3 topics for filename
                    if len(topic_list) > 3:
                        topic_suffix += f"_and_{len(topic_list)-3}_more"
                    self._save_data(final_df, "topic_details", topics=topic_suffix)
                except Exception as e:
                    print(f"[ERROR] Could not save final output: {e}")

            return final_df

        finally:
            # Restore original settings
            self.flatten_metadata = original_flatten_setting


# --- Example Usage ---
if __name__ == '__main__':
    # Create fetcher for topic details
    fetcher = SEDIA_GET_TOPICS(
        flatten_metadata=True
    )
    
    # Example: Get details for specific topics
    topics = [
        'HORIZON-CL3-2022-BM-01-01',
        'HORIZON-CL4-2022-RESILIENCE-01-08'
    ]
    data = fetcher.get(topics, save=True)
    print('') 