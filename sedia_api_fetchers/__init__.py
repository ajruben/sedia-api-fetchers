"""
SEDIA API Fetchers - Base Classes and Common Functionality

This module provides base classes and shared functionality for all SEDIA API fetchers.
"""

import requests
import pandas as pd
import json
import os
import time
import pathlib
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import math
from tqdm.auto import tqdm
from datetime import datetime, timedelta
import numpy as np
from typing import Any, List, Union
from abc import ABC, abstractmethod

class SEDIABaseFetcher(ABC):
    """
    Abstract base class for all SEDIA API fetchers.
    
    Provides common functionality like session management, programme ID handling,
    data processing, and file operations while allowing endpoint-specific implementations.
    """
    
    # Common base URLs and configuration
    SCHEME = "https://"
    HOST = "api.tech.ec.europa.eu"
    
    # Common programme IDs mapping (shared across all fetchers)
    PROGRAMME_IDS = {
        # Common short names for major programmes
        'h2020': 31045243,
        'horizon': 43108390,
        'digital': 43152860,
        'edf': 44181033,
        'erasmus': 43353764,
        'crea': 43251814,
        'cerv': 43251589,
        'smp': 43252476,
        'life': 43252405,
        'cosme': 31059643,
        'cef': 43251567,
        'rec': 31076817,
        
        # Complete list from facet data
        '1st_health_programme_1hp': 111109,
        '2nd_health_programme_2hp': 111110,
        '3rd_health_programme_3hp_2014_2020': 31061266,
        'asylum_migration_and_integration_fund_amif': 43251447,
        'asylum_migration_and_integration_fund_amif_2014_2020': 31077795,
        'border_management_and_visa_policy_instrument_bmvi': 43251530,
        'cef_cef': 31065524,
        'citizens_equality_rights_and_values_programme_cerv': 43251589,
        'connecting_europe_facility_cef': 43251567,
        'creative_europe_crea_2014_2020': 31059083,
        'creative_europe_programme_crea': 43251814,
        'customs_control_equipment_instrument_ccei': 43251534,
        'customs_programme_cust': 43253979,
        'digital_europe_programme_digital': 43152860,
        'erasmus_plus_erasmus_plus': 43353764,
        'erasmus_plus_programme_eplus_2014_2020': 31059093,
        'eu4health_programme_eu4h': 43332642,
        'euratom_research_and_training_programme_euratom': 43298916,
        'european_defence_fund_edf': 44181033,
        'european_maritime_and_fisheries_fund_emff_2014_2020': 31098847,
        'european_maritime_fisheries_and_aquaculture_fund_emfaf': 43392145,
        'european_social_fund_plus_esf': 43254019,
        'european_solidarity_corps_esc': 43254037,
        'fiscalis_programme_fisc': 43253995,
        'hercule_iii_herc_2014_2020': 31084392,
        'horizon_2020_framework_programme_h2020_2014_2020': 31045243,
        'horizon_europe_horizon': 43108390,
        'information_measures_for_the_eu_cohesion_policy_imreg': 44773133,
        'innovation_fund_innovfund': 43089234,
        'internal_security_fund_borders_and_visa_isfb_2014_2020': 31077833,
        'internal_security_fund_isf': 43252368,
        'internal_security_fund_police_isfp_2014_2020': 31077817,
        'interregional_innovation_investments_instrument_i3': 44416173,
        'just_transition_mechanism_jtm': 44773066,
        'justice_programme_just': 43252386,
        'justice_programme_just_2014_2020': 31070247,
        'neighbourhood_development_and_international_cooperation_instrument_global_europe_ndici': 45876777,
        'programme_for_the_competitiveness_of_enterprises_and_small_and_medium_sized_enterprises_cosme_2014_2020': 31059643,
        'programme_for_the_environment_and_climate_action_life': 43252405,
        'programme_for_the_environment_and_climate_action_life_2014_2020': 31107710,
        'programme_for_the_protection_of_the_euro_against_counterfeiting_pericles_iv': 43252433,
        'promotion_of_agricultural_products_agrip': 43298664,
        'promotion_of_agricultural_products_agrip_2014_2020': 31072773,
        'renewable_energy_financing_mechanism_renewfm': 43253967,
        'research_fund_for_coal_and_steel_rfcs': 43252449,
        'research_fund_for_coal_and_steel_rfcs_2014_2020': 31061225,
        'rights_equality_and_citizenship_programme_rec_2014_2020': 31076817,
        'single_market_programme_smp': 43252476,
        'social_prerogative_and_specific_competencies_lines_socpl': 43252517,
        'structural_reform_support_programme_srsp_2014_2020': 42905358,
        'support_for_information_measures_relating_to_the_common_agricultural_policy_imcap': 43251882,
        'support_for_information_measures_relating_to_the_common_agricultural_policy_imcap_2014_2020': 42198993,
        'technical_assistance_for_erdf_cf_and_jtf_erdf_ta': 46324255,
        'technical_support_instrument_tsi': 43253706,
        'union_anti_fraud_programme_euaf': 43251842,
        'union_civil_protection_mechanism_ucpm': 43298203,
        'union_civil_protection_mechanism_ucpm_2014_2020': 31082527
    }
    
    # Common API configuration
    API_FETCH_LIMIT = 10000
    
    def __init__(self, flatten_metadata: bool = True, **kwargs):
        """
        Initialize the base fetcher.
        
        Args:
            flatten_metadata (bool): Whether to flatten complex metadata structures
            **kwargs: Additional configuration options for specific fetchers
        """
        self.flatten_metadata = flatten_metadata
        self.session = self._setup_session()
        self.pbar = None
        
        # Data directory setup
        self.current_working_directory = pathlib.Path.cwd()
        self.DATA_DIR = self.current_working_directory / "data"
        
        # Ensure data directory exists
        self.DATA_DIR.mkdir(exist_ok=True)
        
        # Endpoint-specific configuration must be set by subclasses
        if not hasattr(self, 'API_KEY'):
            raise NotImplementedError("Subclasses must define API_KEY")
    
    def _setup_session(self) -> requests.Session:
        """Configure a requests session with automatic retries for server errors."""
        retry_setup = Retry(
            total=5,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_setup)
        session = requests.Session()
        session.mount(self.SCHEME, adapter)
        return session
    
    def _normalize_programme_input(self, programmes) -> list[int]:
        """
        Normalize programme input to a list of programme IDs.
        
        Args:
            programmes: Can be:
                - Single string (programme name): 'h2020'
                - Single int (programme ID): 31045243
                - List of strings: ['h2020', 'horizon']
                - List of ints: [31045243, 43108390]
                - Mixed list: ['h2020', 43108390]
                
        Returns:
            list[int]: List of programme IDs
            
        Raises:
            ValueError: If programme name is not found in PROGRAMME_IDS
        """
        # Convert single values to list
        if isinstance(programmes, (str, int)):
            programmes = [programmes]
        
        programme_ids = []
        for prog in programmes:
            if isinstance(prog, str):
                # Handle string input (programme name)
                prog_lower = prog.lower()
                if prog_lower in self.PROGRAMME_IDS:
                    programme_ids.append(self.PROGRAMME_IDS[prog_lower])
                else:
                    available_names = list(self.PROGRAMME_IDS.keys())
                    raise ValueError(f"Programme name '{prog}' not found. Available names: {available_names}")
            elif isinstance(prog, int):
                # Handle integer input (programme ID)
                if prog in self.PROGRAMME_IDS.values():
                    programme_ids.append(prog)
                else:
                    available_ids = list(self.PROGRAMME_IDS.values())
                    raise ValueError(f"Programme ID {prog} not found. Available IDs: {available_ids}")
            else:
                raise ValueError(f"Programme must be string or int, got {type(prog)}: {prog}")
        
        return programme_ids
    
    def _apply_unwrapping_to_chunk(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply basic unwrapping and cleaning to a data chunk during fetching.
        This ensures consistent data processing throughout the retrieval process.
        """
        if df.empty:
            return df

        # Import Functions here to avoid circular imports
        try:
            from .helpers.functions import Functions
        except ImportError:
            # Fallback for when running as script
            import sys
            from pathlib import Path
            sys.path.append(str(Path(__file__).parent))
            from helpers.functions import Functions

        for col in df.columns:
            def safe_unwrap(x):
                try:
                    if x is None or x is np.nan:
                        return x
                    elif isinstance(x, str) and x.lower() in ['nan', 'none', 'null', '']:
                        return np.nan
                    elif isinstance(x, (list, np.ndarray)) and len(x) == 0:
                        return np.nan
                    else:
                        return Functions._unwrap(x)
                except (ValueError, TypeError):
                    return x

            df[col] = df[col].apply(safe_unwrap)

        df = Functions.clean_empty_containers(df)
        return df
    
    def _save_data(self, df: pd.DataFrame, filename_prefix: str, **kwargs) -> str:
        """
        Save DataFrame to CSV with timestamped filename.
        
        Args:
            df (pd.DataFrame): DataFrame to save
            filename_prefix (str): Prefix for the filename
            **kwargs: Additional parameters for filename construction
            
        Returns:
            str: Path to saved file
        """
        if df.empty:
            raise ValueError("Cannot save empty DataFrame")
        
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
        final_filename = '_'.join(filename_parts) + '.csv'
        
        output_file = str(self.DATA_DIR / final_filename)
        df.to_csv(output_file, index=False)
        
        file_size = os.path.getsize(output_file) / (1024*1024)
        print(f"Total records: {len(df)}")
        print(f"File size: {file_size:.1f} MB")
        print(f"[SUCCESS] data saved to {output_file}")
        
        return output_file
    
    def _get_basic_metadata(self, query: dict, sort: dict) -> tuple[int, str | None, str | None]:
        """
        Get basic metadata (total results) for a query.
        Default implementation - can be overridden by subclasses.
        """
        data_desc = self.query_api(query, sort, page_size=1)

        if not data_desc or 'results' not in data_desc or not data_desc['results']:
            return 0, None, None

        total_results = data_desc.get("totalResults", 0)
        return total_results, None, None
    
    def _apply_metadata_flattening(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply metadata flattening if enabled."""
        if self.flatten_metadata and not df.empty:
            print("\n--- Applying Metadata Flattening ---")
            try:
                from .helpers.functions import Functions
            except ImportError:
                # Fallback for when running as script
                import sys
                from pathlib import Path
                sys.path.append(str(Path(__file__).parent))
                from helpers.functions import Functions
            df = Functions.flatten_dataframe_metadata(df)
        return df
    
    def _clean_final_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply final cleaning to the dataset."""
        if not df.empty:
            try:
                from .helpers.functions import Functions
            except ImportError:
                # Fallback for when running as script
                import sys
                from pathlib import Path
                sys.path.append(str(Path(__file__).parent))
                from helpers.functions import Functions
            df = Functions.clean_empty_containers(df)
        return df
    
    @abstractmethod
    def query_api(self, query: dict, sort: dict, page_num: int = 1, page_size: int = 100) -> dict:
        """
        Execute a query against the specific API endpoint.
        
        This method must be implemented by each subclass as different endpoints
        have different request formats (POST vs GET, different parameters, etc.).
        
        Args:
            query (dict): The search query parameters
            sort (dict): The sorting parameters
            page_num (int): Page number for pagination
            page_size (int): Number of results per page
            
        Returns:
            dict: JSON response from the API
        """
        pass
    
    @abstractmethod
    def get(self, *args, **kwargs) -> pd.DataFrame:
        """
        Main method to fetch and process data.
        
        This method must be implemented by each subclass as the parameters
        and processing logic vary by endpoint.
        
        Returns:
            pd.DataFrame: Processed data
        """
        pass


class SEDIAPaginatedFetcher(SEDIABaseFetcher):
    """
    Base class for fetchers that use standard pagination with POST requests.
    
    This covers most SEDIA endpoints that use the search API with form data.
    Includes automatic date range partitioning for datasets larger than API_FETCH_LIMIT.
    """
    
    def __init__(self, flatten_metadata: bool = True, **kwargs):
        super().__init__(flatten_metadata=flatten_metadata, **kwargs)
        
        # Set up search API URL - subclasses can override if needed
        self.SEARCH_API_BASE = f"{self.SCHEME}{self.HOST}/search-api/prod/rest/search"
    
    def query_api(self, query: dict, sort: dict, page_num: int = 1, page_size: int = 100) -> dict:
        """
        Standard implementation for POST-based search API queries.
        
        This works for most SEDIA endpoints that use form data submission.
        """
        headers = {
            "apiKey": self.API_KEY,
            "text": "***", 
            "pageSize": str(page_size),
            "pageNumber": str(page_num),
        }
        form_data = {
            "query": ("blob", json.dumps(query), "application/json"),
            "sort": ("blob", json.dumps(sort), "application/json"),
            "languages": ("blob", json.dumps(["en"]), "application/json"),
        }
        
        try:
            response = self.session.post(self.SEARCH_API_BASE, params=headers, files=form_data)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"An API error occurred: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response content: {e.response.text}")
            return {}
    
    def _get_metadata_with_date_range(self, query: dict) -> tuple[int, str | None, str | None]:
        """
        Gets total results, the earliest date, and the latest date for a given query.
        Uses es_SortDate field for date-based partitioning.
        """
        sort_desc = {"field": "es_SortDate", "order": "DESC"}
        data_desc = self.query_api(query, sort_desc, page_size=1)

        if not data_desc or 'results' not in data_desc or not data_desc['results']:
            return 0, None, None

        total_results = data_desc.get("totalResults", 0)
        if total_results == 0:
            return 0, None, None

        def get_date_from_record(record):
            """Extract es_SortDate from a record."""
            if (isinstance(record, dict) and 'metadata' in record and
                isinstance(record['metadata'], dict) and 'es_SortDate' in record['metadata'] and
                record['metadata']['es_SortDate']):
                return record['metadata']['es_SortDate'][0]
            return None

        # Get newest record date
        newest_record = data_desc["results"][0]
        max_date_str = get_date_from_record(newest_record)
        if not max_date_str:
            print(f"Warning: Could not find 'es_SortDate' in the newest record's metadata. Falling back to basic metadata.")
            return self._get_basic_metadata(query, sort_desc)

        # Get oldest record date
        sort_asc = {"field": "es_SortDate", "order": "ASC"}
        data_asc = self.query_api(query, sort_asc, page_size=1)

        if not data_asc or 'results' not in data_asc or not data_asc['results']:
            print("Warning: Could not retrieve the oldest record to determine the date range. Falling back to basic metadata.")
            return self._get_basic_metadata(query, sort_desc)
             
        oldest_record = data_asc["results"][0]
        min_date_str = get_date_from_record(oldest_record)
        if not min_date_str:
            print(f"Warning: Could not find 'es_SortDate' in the oldest record's metadata. Falling back to basic metadata.")
            return self._get_basic_metadata(query, sort_desc)

        return total_results, min_date_str, max_date_str
    
    def fetch_all_records_with_partitioning(self, query: dict, sort: dict = None) -> pd.DataFrame:
        """
        Fetches all records for a given query. Automatically detects if
        the dataset is larger than API_FETCH_LIMIT and partitions the request by
        date range if necessary.
        
        Args:
            query (dict): The search query
            sort (dict): Sort parameters (defaults to es_SortDate DESC)
            
        Returns:
            pd.DataFrame: All records for the query
        """
        if sort is None:
            sort = {"field": "es_SortDate", "order": "DESC"}
        
        print(f"Starting fetch with partitioning support...")
        
        # Try to get metadata with date range for partitioning
        total_records, min_date_str, max_date_str = self._get_metadata_with_date_range(query)

        if total_records == 0:
            print("No records found for query.")
            return pd.DataFrame()

        print(f"Found {total_records:,} total records")
        
        # If we have date range info and total exceeds limit, use date partitioning
        if total_records > self.API_FETCH_LIMIT and min_date_str and max_date_str:
            print(f"Dataset exceeds {self.API_FETCH_LIMIT:,} limit. Using date range partitioning...")
            print(f"Date range: {min_date_str} to {max_date_str}")
            return self._fetch_with_date_partitioning(query, sort, total_records, min_date_str, max_date_str)
        
        # If total is within the API's limit, fetch it in one go
        elif total_records <= self.API_FETCH_LIMIT:
            print("Total is within limit, fetching directly.")
            self.pbar = tqdm(total=total_records, desc="Fetching records", unit="rec")
            df = self._fetch_paginated_chunk(query, sort, total_records)
            self.pbar.close()
            return df
        
        # If we can't get date range but exceed limit, fetch what we can
        else:
            print(f"Warning: Dataset exceeds {self.API_FETCH_LIMIT:,} limit but no date range available.")
            print(f"Fetching first {self.API_FETCH_LIMIT:,} records only.")
            self.pbar = tqdm(total=self.API_FETCH_LIMIT, desc="Fetching records (limited)", unit="rec")
            df = self._fetch_paginated_chunk(query, sort, self.API_FETCH_LIMIT)
            self.pbar.close()
            return df
    
    def _fetch_with_date_partitioning(self, base_query: dict, sort: dict, total_records: int, 
                                    min_date_str: str, max_date_str: str) -> pd.DataFrame:
        """
        Fetch data using recursive date range partitioning.
        
        Args:
            base_query: Base query without date constraints
            sort: Sort parameters
            total_records: Total expected records
            min_date_str: Earliest date in dataset
            max_date_str: Latest date in dataset
            
        Returns:
            pd.DataFrame: All fetched records
        """
        all_dfs = []
        date_format = "%Y-%m-%dT%H:%M:%S.%f"
        
        try:
            min_date = datetime.strptime(min_date_str.split('+')[0], date_format)
            max_date = datetime.strptime(max_date_str.split('+')[0], date_format)
        except ValueError as e:
            print(f"Error parsing dates: {e}")
            print("Falling back to non-partitioned fetch")
            return self._fetch_paginated_chunk(base_query, sort, min(total_records, self.API_FETCH_LIMIT))

        ranges_to_process = [(min_date, max_date)]
        self.pbar = tqdm(total=total_records, desc="Overall Progress", unit="rec")

        while ranges_to_process:
            start_date, end_date = ranges_to_process.pop(0)

            # Create date-constrained query
            range_query = {
                "bool": {
                    "must": base_query["bool"]["must"].copy() + [
                        {
                            "range": {
                                "es_SortDate": {
                                    "gte": start_date.strftime(date_format)[:-3] + "Z",
                                    "lte": end_date.strftime(date_format)[:-3] + "Z",
                                }
                            }
                        }
                    ]
                }
            }

            # Get count for this date range
            count_for_range, _, _ = self._get_metadata_with_date_range(range_query)

            if count_for_range == 0:
                continue

            if count_for_range <= self.API_FETCH_LIMIT:
                print(f"Fetching chunk: {count_for_range:,} records ({start_date.date()} to {end_date.date()})")
                chunk_df = self._fetch_paginated_chunk(range_query, sort, count_for_range)
                all_dfs.append(chunk_df)
            else:
                print(f"Splitting large chunk: {count_for_range:,} records ({start_date.date()} to {end_date.date()})")
                # Split the date range in half
                mid_point = start_date + (end_date - start_date) / 2
                ranges_to_process.append((start_date, mid_point))
                ranges_to_process.append((mid_point + timedelta(microseconds=1), end_date))

        self.pbar.close()

        if not all_dfs:
            print("No data was fetched.")
            return pd.DataFrame()

        print("Concatenating all chunks...")
        final_df = pd.concat(all_dfs, ignore_index=True)

        print(f"Fetch complete: {len(final_df):,} records retrieved (expected ~{total_records:,})")
        if abs(len(final_df) - total_records) > (total_records * 0.05):  # 5% tolerance
            print(f"Warning: Record count difference > 5%. Expected: {total_records:,}, Got: {len(final_df):,}")

        return final_df
    
    def _fetch_paginated_chunk(self, query: dict, sort: dict, count: int) -> pd.DataFrame:
        """Fetch all records for a query known to contain <= API_FETCH_LIMIT records."""
        all_records = []
        page_size = 100
        num_pages = min(math.ceil(count / page_size), 100)  # Cap at 100 pages

        chunk_pbar = tqdm(total=count, desc="Fetching chunk", leave=False, unit="rec")
        for page in range(1, num_pages + 1):
            data = self.query_api(query, sort, page_num=page, page_size=page_size)
            if data and "results" in data:
                results = data["results"]
                all_records.extend(results)
                chunk_pbar.update(len(results))
                print(f"[DEBUG] Page {page} → {len(results)} hits")
            else:
                print(f"Warning: Failed to fetch page {page} for query {json.dumps(query)}")
                break
        chunk_pbar.close()

        if self.pbar:
            self.pbar.update(len(all_records))

        chunk_df = pd.DataFrame(all_records)
        if not chunk_df.empty:
            chunk_df = self._apply_unwrapping_to_chunk(chunk_df)

        return chunk_df


class SEDIASimpleFetcher(SEDIABaseFetcher):
    """
    Base class for fetchers that use simple GET requests.
    
    This covers endpoints like the topic details API that use URL parameters.
    """
    
    def __init__(self, flatten_metadata: bool = True, **kwargs):
        super().__init__(flatten_metadata=flatten_metadata, **kwargs)
        
        # Set up search API URL - subclasses can override if needed
        self.SEARCH_API_BASE = f"{self.SCHEME}{self.HOST}/search-api/prod/rest/search"
    
    def query_api(self, query: dict, sort: dict = None, page_num: int = 1, page_size: int = 100) -> dict:
        """
        Simple implementation for GET-based API queries.
        
        This works for endpoints that use URL parameters instead of form data.
        Note: query parameter might be used differently (e.g., as search text).
        """
        params = {
            "apiKey": self.API_KEY,
        }
        
        # Add query-specific parameters - subclasses should override this method
        # to handle their specific parameter requirements
        
        try:
            response = self.session.get(self.SEARCH_API_BASE, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"An API error occurred: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response content: {e.response.text}")
            return {}


# Export the base classes for use by individual fetchers
__all__ = ['SEDIABaseFetcher', 'SEDIAPaginatedFetcher', 'SEDIASimpleFetcher']
