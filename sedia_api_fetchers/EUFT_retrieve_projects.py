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

class SEDIA_GET_PROJECTS(SEDIAPaginatedFetcher):
    """
    A class to fetch data from the SEDIA API, handling pagination limits
    by recursively splitting large requests by date range and then enriching
    each record with detailed project information.

    This approach is robust against the API's 10,000 record limit because it
    partitions the entire dataset into manageable date-range chunks rather than
    relying on record-by-record cursor pagination, which fails with non-unique
    sort keys like es_SortDate.
    """
    
    # Endpoint-specific configuration
    API_KEY = "SEDIA_NONH2020_PROD"
    
    def __init__(self, flatten_metadata: bool = True, enrich_with_details: bool = False):
        """
        Initializes the fetcher with an API key.
        Args:
            flatten_metadata (bool): Whether to flatten complex metadata structures. Default True.
            enrich_with_details (bool): Whether to fetch detailed project data via document API. Default False.
        """
        super().__init__(flatten_metadata=flatten_metadata)
        self.enrich_with_details = enrich_with_details
        
        # Set up document API URL for detailed project information
        self.DOCUMENT_API_BASE = f"{self.SCHEME}{self.HOST}/search-api/prod/rest/document/"



    def query_api(self, query: dict, sort: dict, page_num: int = 1, page_size: int = 100) -> dict:
        """
        Override to include comprehensive project fields for detailed information.
        """
        # Define comprehensive fields to be returned by the API for detailed information
        display_fields = [
            "reference", "projectId", "title", "acronym", "status", "objective",
            "programId", "programAbbreviation", "programmes", "frameworkProgramme",
            "topicAbbreviation", "topics", "subjects", "participants", "legalEntityNames", 
            "coordinatorCountry", "overallBudget", "euContributionAmount", "euContributionRate",
            "maxContributionAmount", "ecContribution", "startDate", "endDate", "ecSignatureDate", 
            "es_SortDate", "freeKeywords", "keywords", "sicCode", "nutsCode", "countries", 
            "regions", "coordinatorRegion", "technologyReadinessLevel", "activityType", "rcn",
            "callIdentifier", "grantAgreementNumber", "metadata", "project_data"
        ]
        
        headers = {
            "apiKey": self.API_KEY,
            "text": "***", 
            "pageSize": str(page_size),
            "pageNumber": str(page_num),
        }
        form_data = {
            "query": ("blob", json.dumps(query), "application/json"),
            "sort": ("blob", json.dumps(sort), "application/json"),
            "displayFields": ("blob", json.dumps(display_fields), "application/json"),
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

    def _flatten_json(self, d: dict, parent_key: str = '', sep: str = '_') -> dict:
        """
        Recursively flattens a nested dictionary.
        Converts lists to JSON strings to keep them in single columns.
        """
        items = []
        for k, v in d.items():
            new_key = parent_key + sep + k if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_json(v, new_key, sep=sep).items())
            elif isinstance(v, list):
                items.append((new_key, json.dumps(v)))
            else:
                items.append((new_key, v))
        return dict(items)

    def _fetch_project_details(self, project_reference: str) -> dict:
        """
        Fetches detailed project information using the document API.

        Args:
            project_reference (str): The project reference ID

        Returns:
            dict: Detailed project data or empty dict if fetch fails
        """
        if not project_reference:
            return {}

        project_url = f"{self.DOCUMENT_API_BASE}{project_reference}"
        project_header = {"apiKey": self.API_KEY}

        try:
            response = self.session.get(project_url, params=project_header)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Could not fetch details for {project_reference}: {e}")
            return {}

    def _enrich_records_with_details(self, records: list, force_enrich: bool = None) -> list:
        """
        Enriches a list of project records with detailed information from document API.

        Args:
            records (list): List of project records from search API
            force_enrich (bool): Override instance setting for enrichment. If None, uses self.enrich_with_details

        Returns:
            list: List of enriched and flattened records
        """
        should_enrich = force_enrich if force_enrich is not None else self.enrich_with_details

        if not should_enrich or not records:
            return records

        print(f"🔍 INDIVIDUAL PROJECT ENRICHMENT STARTING...")
        print(f"Enriching {len(records)} records with detailed project information...")
        print(f"💾 Writing incrementally to single file for progress tracking...")

        enriched_records = []
        checkpoint_interval = 100
        total_projects = len(records)
        
        output_file = str(self.DATA_DIR / "cordis_enriched_projects.csv")
        is_new_file = not os.path.exists(output_file)
        current_batch = []

        for i, record in enumerate(tqdm(records, desc="Processing project details", unit="project")):
            project_reference = record.get('reference')
            if project_reference:
                if i % 10 == 0 or i < 10:
                    print(f"  → Fetching details for project {i+1}/{total_projects}: {project_reference}")

                detail_data = self._fetch_project_details(project_reference)
                
                if detail_data:
                    flattened_record = record.copy()
                    for key, value in detail_data.items():
                        flattened_record[f'details_{key}'] = value
                    record = flattened_record
                else:
                    record['details'] = {}
            else:
                if i < 10:
                    print(f"Skipping record {i+1} due to missing 'reference'")
                record['details'] = {}

            current_batch.append(record)
            enriched_records.append(record)

            # Write incrementally every checkpoint_interval records
            if (i + 1) % checkpoint_interval == 0 or (i + 1) == total_projects:
                try:
                    batch_df = pd.DataFrame(current_batch)
                    
                    if not batch_df.empty:
                        detail_cols = [col for col in batch_df.columns if col.startswith('details_')]
                        
                        if not detail_cols and 'details' in batch_df.columns:
                            details_df = pd.json_normalize(batch_df['details'])
                            details_df.columns = ['details_' + col for col in details_df.columns]
                            batch_df = pd.concat([batch_df.drop('details', axis=1), details_df], axis=1)
                    
                    batch_df.to_csv(output_file, 
                                  mode='a' if not is_new_file else 'w',
                                  header=is_new_file,
                                  index=False)
                    
                    is_new_file = False
                    current_batch = []
                    
                    print(f"\n💾 Progress Update:")
                    print(f"   • Processed {i+1}/{total_projects} projects")
                    print(f"   • Written to: {output_file}")
                    print(f"   • Progress: {((i+1)/total_projects)*100:.1f}%")
                    
                    if os.path.exists(output_file):
                        file_size = os.path.getsize(output_file) / (1024*1024)
                        print(f"   • Current file size: {file_size:.1f} MB")
                        if not batch_df.empty:
                            detail_cols = [col for col in batch_df.columns if col.startswith('details_')]
                            print(f"   • Number of detail columns: {len(detail_cols)}")
                            if detail_cols:
                                print(f"   • Sample detail columns: {detail_cols[:5]}")

                except Exception as e:
                    print(f"❌ Warning: Could not write batch to file: {e}")

        print(f"🎉 INDIVIDUAL PROJECT ENRICHMENT COMPLETE!")
        print(f"Successfully processed {len(enriched_records)} projects with detailed information")
        print(f"💾 All data written to: {output_file}")
        return enriched_records

    def fetch_all_records(self, programmes) -> pd.DataFrame:
        """
        Fetches all records for given programmes using the base class partitioning logic.
        
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
        
        base_query = {"bool": {"must": [{"terms": {"programId": [str(pid) for pid in program_ids]}}]}}
        sort = {"field": "es_SortDate", "order": "DESC"}
        
        # Use the base class method for partitioning
        final_df = self.fetch_all_records_with_partitioning(base_query, sort)
        
        if not final_df.empty:
            print(f"Successfully retrieved {len(final_df)} records.")
            print(f"Unique records: {len(final_df.drop_duplicates(subset=['projectId'])) if 'projectId' in final_df.columns else 'N/A'}")
            final_df = self._apply_metadata_flattening(final_df)
        
        return final_df

    def get(self, programmes, save: bool = False) -> pd.DataFrame:
        """
        Comprehensive method that fetches all records for programme(s), then enriches each record with
        detailed data from the document API and returns a fully processed DataFrame.

        Args:
            programmes: Programme names or IDs. Can be:
                - Single string: 'h2020'
                - Single int: 31045243
                - List of strings: ['h2020', 'horizon']
                - List of ints: [31045243, 43108390]
                - Mixed list: ['h2020', 43108390]
            save (bool): Whether to save the final result to file

        Returns:
            pd.DataFrame: Fully processed and enriched project data
        """
        program_ids = self._normalize_programme_input(programmes)
        print(f"Starting comprehensive fetch and processing for programme IDs: {program_ids}...")
        print(f"🔍 DEBUG: Programme IDs being processed: {program_ids}")
        print(f"🔍 DEBUG: Number of programmes: {len(program_ids)}")

        # Temporarily disable settings to get raw records first
        original_flatten_setting = self.flatten_metadata
        original_enrich_setting = self.enrich_with_details

        self.flatten_metadata = False
        self.enrich_with_details = False

        try:
            initial_df = self.fetch_all_records(programmes)

            if initial_df.empty:
                print("No initial records found. Cannot proceed to fetch details.")
                return pd.DataFrame()

            initial_records = initial_df.to_dict('records')
            print(f"Retrieved {len(initial_records)} initial project records.")

            # Debug: Check programme distribution
            if initial_records:
                program_distribution = {}
                for record in initial_records:
                    pid = record.get('programId', 'unknown')
                    program_distribution[pid] = program_distribution.get(pid, 0) + 1
                print(f"Initial programme distribution: {program_distribution}")

            # Enrich with detailed information if requested
            if original_enrich_setting:
                enriched_records = self._enrich_records_with_details(initial_records, force_enrich=True)
            else:
                enriched_records = initial_records

            # Apply flattening if requested
            if original_flatten_setting:
                print("Applying comprehensive flattening to enriched records...")
                processed_records = []
                for record in enriched_records:
                    if original_enrich_setting:
                        flattened_record = self._flatten_json(record)
                    else:
                        flattened_record = Functions.flatten_project_data(record)
                    processed_records.append(flattened_record)
                enriched_records = processed_records

            # Create final DataFrame and apply cleaning
            print("Creating final processed DataFrame...")
            final_df = pd.DataFrame(enriched_records)

            if not final_df.empty and 'programId' in final_df.columns:
                final_distribution = final_df['programId'].value_counts().to_dict()
                print(f"Final DataFrame programme distribution: {final_distribution}")
                print(f"Final DataFrame shape: {final_df.shape}")

            final_df = self._clean_final_data(final_df)

            print(f"Comprehensive processing complete! Final dataset: {len(final_df)} records, {len(final_df.columns) if not final_df.empty else 0} columns")

            # Save the final processed data
            if not final_df.empty and save:
                try:
                    prog_suffix = '_'.join(map(str, program_ids))
                    self._save_data(final_df, "project_data", programmes=prog_suffix)
                except Exception as e:
                    print(f"[ERROR] Could not save final output: {e}")

            return final_df

        finally:
            # Restore original settings
            self.flatten_metadata = original_flatten_setting
            self.enrich_with_details = original_enrich_setting


# --- Example Usage ---
if __name__ == '__main__':
    # Create fetcher with enhanced mode enabled for comprehensive project information
    fetcher = SEDIA_GET_PROJECTS(
        flatten_metadata=True,
        enrich_with_details=False
    )

    # Example 1: Using programme names (recommended)
    print("=== Example 1: Using programme names ===")
    # Single programme
    data = fetcher.get('edf', save=True)

    print('')
