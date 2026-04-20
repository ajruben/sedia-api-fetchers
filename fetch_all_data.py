#!/usr/bin/env python3
"""
ETL Pipeline for SEDIA Data Retrieval
====================================
Extract, Transform, Load pipeline for fetching ALL available data from ALL programmes 
across all SEDIA API endpoints using the refactored fetchers.

ETL Architecture:
- Extract: Fetch raw data from SEDIA APIs
- Transform: Process, validate, and clean the data
- Load: Save data with change detection and version management

Includes comprehensive logging, change detection, and performance monitoring.
"""

import sys
import json
import glob
import time
import logging
import pandas as pd
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass

# Add current directory to path for imports
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

@dataclass
class ETLConfig:
    """Configuration for the ETL pipeline."""
    data_dir: Path
    logs_dir: Path
    legacy_dir: Path
    min_record_threshold: int = 100
    enable_change_detection: bool = True
    enable_legacy_management: bool = True
    log_level: str = "INFO"

@dataclass
class ProgrammeMetadata:
    """Metadata for a programme."""
    id: int
    name: str
    clean_name: str
    record_count: int

@dataclass
class ExtractionResult:
    """Result of data extraction."""
    programme: ProgrammeMetadata
    endpoint: str
    data: pd.DataFrame
    extraction_time: float
    success: bool
    error_message: Optional[str] = None

@dataclass
class TransformationResult:
    """Result of data transformation."""
    extraction_result: ExtractionResult
    transformed_data: pd.DataFrame
    transformation_time: float
    validation_passed: bool
    transformation_notes: List[str]

@dataclass
class LoadResult:
    """Result of data loading."""
    transformation_result: TransformationResult
    file_path: Optional[str]
    load_time: float
    change_detected: bool
    change_type: str
    legacy_file_moved: Optional[str] = None

class ETLLogger:
    """Centralized logging for the ETL pipeline."""
    
    def __init__(self, config: ETLConfig):
        self.config = config
        self.setup_logging()
        self.setup_change_logging()
    
    def setup_logging(self):
        """Set up main logging."""
        self.config.logs_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.config.logs_dir / f"etl_pipeline_{timestamp}.log"
        
        logging.basicConfig(
            level=getattr(logging, self.config.log_level),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )
        
        self.main_logger = logging.getLogger('etl_pipeline')
        self.log_file = log_file
    
    def setup_change_logging(self):
        """Set up change tracking logging."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        change_log_file = self.config.logs_dir / f"etl_changes_{timestamp}.log"
        
        self.change_logger = logging.getLogger('etl_changes')
        self.change_logger.setLevel(logging.INFO)
        
        # Remove existing handlers
        for handler in self.change_logger.handlers[:]:
            self.change_logger.removeHandler(handler)
        
        change_handler = logging.FileHandler(change_log_file)
        change_formatter = logging.Formatter('%(asctime)s - %(message)s')
        change_handler.setFormatter(change_formatter)
        self.change_logger.addHandler(change_handler)
        
        self.change_log_file = change_log_file

class ETLExtractor:
    """Extract phase - Fetch raw data from SEDIA APIs."""
    
    def __init__(self, logger: ETLLogger):
        self.logger = logger
        self.main_logger = logger.main_logger
        self._import_fetchers()
    
    def _import_fetchers(self):
        """Import all fetcher classes."""
        try:
            from sedia_api_fetchers.EUFT_retrieve_projects import SEDIA_GET_PROJECTS
            from sedia_api_fetchers.EUFT_retrieve_participants import SEDIA_GET_PARTICIPANTS
            from sedia_api_fetchers.EUFT_retrieve_funding_tenders import SEDIA_GET_FUNDING_TENDERS
            from sedia_api_fetchers.EUFT_retrieve_faq import SEDIA_GET_FAQ
            
            self.fetchers = {
                'projects': SEDIA_GET_PROJECTS,
                'participants': SEDIA_GET_PARTICIPANTS,
                'funding_tenders': SEDIA_GET_FUNDING_TENDERS,
                'faq': SEDIA_GET_FAQ
            }
            self.main_logger.info("All fetcher classes imported successfully")
        except ImportError as e:
            self.main_logger.error(f"Failed to import fetchers: {e}")
            raise
    
    def extract_programme_metadata(self, config: ETLConfig) -> List[ProgrammeMetadata]:
        """Extract programme metadata from facet data."""
        self.main_logger.info("EXTRACT PHASE: Loading programme metadata from facets")
        
        start_time = time.time()
        facet_files = list(config.data_dir.glob("facet_data_*.json"))
        
        if not facet_files:
            raise FileNotFoundError("No facet data files found. Run facets fetcher first.")
        
        latest_facet_file = max(facet_files, key=lambda x: x.stat().st_mtime)
        self.main_logger.info(f"Reading from: {latest_facet_file.name}")
        
        with open(latest_facet_file, 'r', encoding='utf-8') as f:
            facet_data = json.load(f)
        
        programmes = []
        for facet in facet_data.get('facets', []):
            if facet.get('name') == 'programId':
                for prog in facet.get('values', []):
                    programme_id = int(prog['rawValue'])
                    programme_name = prog['value']
                    record_count = prog['count']
                    
                    # Clean programme name for filename
                    clean_name = (programme_name.replace(' ', '_').replace('(', '')
                                 .replace(')', '').replace('-', '_').replace(',', '')
                                 .replace('&', 'and').replace('/', '_'))
                    clean_name = '_'.join(filter(None, clean_name.split('_')))
                    
                    programmes.append(ProgrammeMetadata(
                        id=programme_id,
                        name=programme_name,
                        clean_name=clean_name,
                        record_count=record_count
                    ))
                break
        
        # Sort by record count (descending)
        programmes.sort(key=lambda x: x.record_count, reverse=True)
        
        extraction_time = time.time() - start_time
        self.main_logger.info(f"Extracted {len(programmes)} programmes in {extraction_time:.1f}s")
        
        return programmes
    
    def extract_programme_data(self, programme: ProgrammeMetadata, endpoint: str) -> ExtractionResult:
        """Extract data for a specific programme and endpoint."""
        start_time = time.time()
        self.main_logger.info(f"EXTRACT: {endpoint} for {programme.name} (ID: {programme.id})")
        
        # Check if this programme might exceed API limits
        if programme.record_count > 10000:
            self.main_logger.warning(f"Large dataset detected ({programme.record_count:,} records) - using date partitioning strategy")
        
        try:
            fetcher_class = self.fetchers[endpoint]
            
            # Special handling for projects endpoint which has date partitioning logic
            if endpoint == "projects":
                fetcher = fetcher_class(flatten_metadata=True, enrich_with_details=False)
                
                # Use the fetch_all_records method directly to ensure date partitioning works
                # This method handles large datasets automatically
                data = fetcher.fetch_all_records(programme.id)
                
            else:
                # For other endpoints, use the standard get method
                fetcher = fetcher_class(flatten_metadata=True)
                
                if endpoint == "funding_tenders":
                    data = fetcher.get(programme.id, funding_type='all', status='all', save=False)
                elif endpoint == "faq":
                    data = fetcher.get(programme.id, faq_type='all', status='all', save=False)
                else:
                    data = fetcher.get(programme.id, save=False)
            
            extraction_time = time.time() - start_time
            
            if isinstance(data, pd.DataFrame) and not data.empty:
                self.main_logger.info(f"EXTRACT SUCCESS: {len(data):,} records in {extraction_time:.1f}s")
                
                # Log if we got significantly different record count than expected
                if abs(len(data) - programme.record_count) > (programme.record_count * 0.1):
                    self.main_logger.warning(f"Record count mismatch: expected {programme.record_count:,}, got {len(data):,}")
                
                return ExtractionResult(
                    programme=programme,
                    endpoint=endpoint,
                    data=data,
                    extraction_time=extraction_time,
                    success=True
                )
            else:
                self.main_logger.warning(f"EXTRACT WARNING: No data returned for {endpoint}")
                return ExtractionResult(
                    programme=programme,
                    endpoint=endpoint,
                    data=pd.DataFrame(),
                    extraction_time=extraction_time,
                    success=False,
                    error_message="No data returned"
                )
                
        except Exception as e:
            extraction_time = time.time() - start_time
            self.main_logger.error(f"EXTRACT FAILED: {endpoint} for {programme.name} after {extraction_time:.1f}s: {e}")
            return ExtractionResult(
                programme=programme,
                endpoint=endpoint,
                data=pd.DataFrame(),
                extraction_time=extraction_time,
                success=False,
                error_message=str(e)
            )

class ETLTransformer:
    """Transform phase - Process, validate, and clean the data."""
    
    def __init__(self, logger: ETLLogger):
        self.logger = logger
        self.main_logger = logger.main_logger
    
    def transform_data(self, extraction_result: ExtractionResult) -> TransformationResult:
        """Transform extracted data."""
        start_time = time.time()
        self.main_logger.info(f"TRANSFORM: {extraction_result.endpoint} for {extraction_result.programme.name}")
        
        transformation_notes = []
        
        if not extraction_result.success or extraction_result.data.empty:
            transformation_time = time.time() - start_time
            return TransformationResult(
                extraction_result=extraction_result,
                transformed_data=pd.DataFrame(),
                transformation_time=transformation_time,
                validation_passed=False,
                transformation_notes=["No data to transform"]
            )
        
        try:
            # Start with the extracted data
            transformed_data = extraction_result.data.copy()
            original_shape = transformed_data.shape
            
            # Apply transformations
            transformed_data = self._clean_data(transformed_data, transformation_notes)
            transformed_data = self._validate_data(transformed_data, transformation_notes)
            transformed_data = self._standardize_data(transformed_data, transformation_notes)
            
            transformation_time = time.time() - start_time
            final_shape = transformed_data.shape
            
            self.main_logger.info(f"TRANSFORM SUCCESS: {original_shape} -> {final_shape} in {transformation_time:.1f}s")
            
            return TransformationResult(
                extraction_result=extraction_result,
                transformed_data=transformed_data,
                transformation_time=transformation_time,
                validation_passed=True,
                transformation_notes=transformation_notes
            )
            
        except Exception as e:
            transformation_time = time.time() - start_time
            self.main_logger.error(f"TRANSFORM FAILED: {extraction_result.endpoint} after {transformation_time:.1f}s: {e}")
            return TransformationResult(
                extraction_result=extraction_result,
                transformed_data=pd.DataFrame(),
                transformation_time=transformation_time,
                validation_passed=False,
                transformation_notes=[f"Transformation error: {e}"]
            )
    
    def _clean_data(self, df: pd.DataFrame, notes: List[str]) -> pd.DataFrame:
        """Clean the data."""
        if df.empty:
            return df
        
        original_rows = len(df)
        
        # Remove duplicates - handle unhashable types (nested dicts/lists)
        try:
            df = df.drop_duplicates()
            if len(df) < original_rows:
                notes.append(f"Removed {original_rows - len(df)} duplicate rows")
        except TypeError as e:
            if "unhashable type" in str(e):
                # Find hashable columns and remove duplicates based on those only
                hashable_cols = []
                for col in df.columns:
                    try:
                        # Test if column is hashable by trying to create a set
                        test_sample = df[col].dropna().iloc[:5] if len(df) > 0 else []
                        if len(test_sample) > 0:
                            set(test_sample)
                        hashable_cols.append(col)
                    except (TypeError, ValueError):
                        continue
                
                if hashable_cols:
                    df = df.drop_duplicates(subset=hashable_cols)
                    if len(df) < original_rows:
                        notes.append(f"Removed {original_rows - len(df)} duplicate rows (using hashable columns only)")
                else:
                    notes.append("Skipped duplicate removal: no hashable columns found")
            else:
                raise e
        
        # Handle missing values
        missing_before = df.isnull().sum().sum()
        if missing_before > 0:
            notes.append(f"Found {missing_before} missing values")
        
        return df
    
    def _validate_data(self, df: pd.DataFrame, notes: List[str]) -> pd.DataFrame:
        """Validate data quality."""
        if df.empty:
            return df
        
        # Check for required columns (basic validation)
        if 'programId' in df.columns:
            invalid_program_ids = df[df['programId'].isnull()].index
            if len(invalid_program_ids) > 0:
                df = df.drop(invalid_program_ids)
                notes.append(f"Removed {len(invalid_program_ids)} rows with invalid programId")
        
        return df
    
    def _standardize_data(self, df: pd.DataFrame, notes: List[str]) -> pd.DataFrame:
        """Standardize data formats."""
        if df.empty:
            return df
        
        # Standardize date columns
        date_columns = [col for col in df.columns if 'date' in col.lower() or 'Date' in col]
        for col in date_columns:
            try:
                df[col] = pd.to_datetime(df[col], errors='coerce')
                notes.append(f"Standardized date format for column: {col}")
            except Exception:
                pass
        
        return df

class ETLLoader:
    """Load phase - Save data with change detection and version management."""
    
    def __init__(self, config: ETLConfig, logger: ETLLogger):
        self.config = config
        self.logger = logger
        self.main_logger = logger.main_logger
        self.change_logger = logger.change_logger
    
    def load_data(self, transformation_result: TransformationResult) -> LoadResult:
        """Load transformed data with change detection."""
        start_time = time.time()
        
        if not transformation_result.validation_passed or transformation_result.transformed_data.empty:
            load_time = time.time() - start_time
            return LoadResult(
                transformation_result=transformation_result,
                file_path=None,
                load_time=load_time,
                change_detected=False,
                change_type="NO_DATA"
            )
        
        programme = transformation_result.extraction_result.programme
        endpoint = transformation_result.extraction_result.endpoint
        
        self.main_logger.info(f"LOAD: {endpoint} for {programme.name}")
        
        try:
            # Check for changes if enabled
            if self.config.enable_change_detection:
                should_save, change_type, old_file = self._check_for_changes(
                    transformation_result.transformed_data, endpoint, programme
                )
            else:
                should_save, change_type, old_file = True, "FORCE_SAVE", None
            
            if not should_save:
                load_time = time.time() - start_time
                self.main_logger.info(f"LOAD SKIPPED: No changes detected for {endpoint}_{programme.clean_name}")
                return LoadResult(
                    transformation_result=transformation_result,
                    file_path=str(old_file) if old_file else None,
                    load_time=load_time,
                    change_detected=False,
                    change_type=change_type
                )
            
            # Move old file to legacy if changes detected
            legacy_file_moved = None
            if old_file and change_type != "NEW_DATA" and self.config.enable_legacy_management:
                legacy_file_moved = self._move_to_legacy(old_file)
            
            # Save new file
            file_path = self._save_data(transformation_result.transformed_data, endpoint, programme)
            
            load_time = time.time() - start_time
            self.main_logger.info(f"LOAD SUCCESS: Saved to {Path(file_path).name} in {load_time:.1f}s")
            
            # Log change detection result
            if legacy_file_moved:
                self.main_logger.info(f"LEGACY: Moved old file to {Path(legacy_file_moved).name}")
            
            self.change_logger.info(f"💾 SAVED: {endpoint}_{programme.clean_name} -> {Path(file_path).name}")
            
            return LoadResult(
                transformation_result=transformation_result,
                file_path=file_path,
                load_time=load_time,
                change_detected=True,
                change_type=change_type,
                legacy_file_moved=legacy_file_moved
            )
            
        except Exception as e:
            load_time = time.time() - start_time
            self.main_logger.error(f"LOAD FAILED: {endpoint} for {programme.name} after {load_time:.1f}s: {e}")
            return LoadResult(
                transformation_result=transformation_result,
                file_path=None,
                load_time=load_time,
                change_detected=False,
                change_type=f"ERROR: {e}"
            )
    
    def _check_for_changes(self, new_df: pd.DataFrame, endpoint: str, programme: ProgrammeMetadata) -> Tuple[bool, str, Optional[Path]]:
        """Check for changes compared to existing data."""
        # Import Functions here to avoid circular imports
        try:
            from helpers.functions import Functions
        except ImportError:
            import sys
            from pathlib import Path
            sys.path.append(str(Path(__file__).parent))
            from helpers.functions import Functions
        
        pattern = f"{endpoint}_{programme.clean_name}_*.csv"
        existing_files = list(self.config.data_dir.glob(pattern))
        
        self.change_logger.info(f"🔍 CHANGE DETECTION: {endpoint}_{programme.clean_name}")
        self.change_logger.info(f"   Looking for pattern: {pattern}")
        self.change_logger.info(f"   Found {len(existing_files)} existing files")
        
        if not existing_files:
            self.change_logger.info(f"✅ NEW DATA: {endpoint}_{programme.clean_name} - No previous files found")
            self.main_logger.info(f"NEW DATA: {endpoint}_{programme.clean_name} ({len(new_df)} records)")
            return True, "NEW_DATA", None
        
        # Get most recent file
        existing_file = max(existing_files, key=lambda x: x.stat().st_mtime)
        self.change_logger.info(f"   Most recent file: {existing_file.name}")
        
        try:
            existing_df = pd.read_csv(existing_file)
            self.change_logger.info(f"   Comparing: {existing_df.shape} vs {new_df.shape}")
            
            # Use smart comparison based on endpoint type
            comparison_result = self._smart_dataframe_comparison(existing_df, new_df, endpoint)
            
            if comparison_result == "identical":
                self.change_logger.info(f"🟰 IDENTICAL: {endpoint}_{programme.clean_name} - {existing_file.name}")
                self.main_logger.info(f"SKIPPING (IDENTICAL): {endpoint}_{programme.clean_name}")
                return False, "IDENTICAL", existing_file
            else:
                self.change_logger.info(f"🔄 CHANGES DETECTED: {endpoint}_{programme.clean_name}")
                self.change_logger.info(f"   Change type: {comparison_result}")
                self.change_logger.info(f"   Previous: {existing_df.shape}, New: {new_df.shape}")
                self.main_logger.info(f"CHANGES DETECTED: {endpoint}_{programme.clean_name} - {comparison_result}")
                return True, comparison_result, existing_file
                
        except Exception as e:
            self.change_logger.error(f"❌ COMPARISON ERROR: {endpoint}_{programme.clean_name}: {e}")
            self.main_logger.warning(f"COMPARISON ERROR: {endpoint}_{programme.clean_name} - Will save anyway")
            return True, f"COMPARISON_ERROR: {e}", existing_file
    
    def _smart_dataframe_comparison(self, existing_df: pd.DataFrame, new_df: pd.DataFrame, endpoint: str) -> str:
        """
        Smart comparison that handles different data types with appropriate unique keys.
        
        Args:
            existing_df: Previously saved dataframe
            new_df: Newly fetched dataframe  
            endpoint: Type of data (projects, participants, funding_tenders, faq)
            
        Returns:
            str: Comparison result ('identical' or description of changes)
        """
        try:
            # Quick check for identical shapes and sizes
            if existing_df.shape == new_df.shape:
                # Try simple hash comparison first (fastest)
                if existing_df.equals(new_df):
                    return "identical"
            
            # Shape difference - quick comparison
            if existing_df.shape != new_df.shape:
                old_rows, old_cols = existing_df.shape
                new_rows, new_cols = new_df.shape
                
                if old_rows != new_rows and old_cols == new_cols:
                    if new_rows > old_rows:
                        return f"row_count_increased_from_{old_rows}_to_{new_rows}"
                    else:
                        return f"row_count_decreased_from_{old_rows}_to_{new_rows}"
                elif old_cols != new_cols and old_rows == new_rows:
                    return f"column_count_changed_from_{old_cols}_to_{new_cols}"
                else:
                    return f"shape_changed_from_{existing_df.shape}_to_{new_df.shape}"
            
            # Same shape but content differences - use endpoint-specific comparison
            if endpoint == "projects":
                # Projects have projectId as unique identifier
                unique_key = "projectId" if "projectId" in new_df.columns else []
                check_columns = ["title", "programId", "startDate", "endDate"] 
                
            elif endpoint == "participants":
                # Participants don't have a single unique ID - use composite key
                # Use organization name + programme combination as best identifier
                if "name" in new_df.columns and "programmes" in new_df.columns:
                    unique_key = ["name", "programmes"]
                    check_columns = ["type", "country", "activityType"]
                else:
                    # Fallback: just do row count comparison for participants
                    return f"participant_data_modified_{len(existing_df)}_vs_{len(new_df)}_records"
                    
            elif endpoint == "funding_tenders":
                # Funding/tenders have identifier field
                unique_key = "identifier" if "identifier" in new_df.columns else []
                check_columns = ["title", "status", "type", "deadline"]
                
            elif endpoint == "faq":
                # FAQ items have question/title as identifier
                unique_key = "title" if "title" in new_df.columns else []
                check_columns = ["type", "status", "lastModified"]
                
            else:
                # Unknown endpoint - basic comparison
                return f"data_modified_shape_{existing_df.shape}_vs_{new_df.shape}"
            
            # Filter check_columns to only include existing columns
            check_columns = [col for col in check_columns if col in new_df.columns and col in existing_df.columns]
            
            # If we don't have a proper unique key, fall back to simple comparison
            if not unique_key or (isinstance(unique_key, list) and not all(col in new_df.columns for col in unique_key)):
                # Just return a generic change description
                return f"content_modified_{endpoint}_data"
            
            # Use the comparison function with proper parameters
            comparison_df = Functions.compare_dataframes(
                existing_df, 
                new_df, 
                check_columns=check_columns,
                unique_key=unique_key,
                detect_column_changes=True
            )
            
            if comparison_df.empty:
                return "identical"
            else:
                # Analyze the changes
                change_types = comparison_df['change_type'].value_counts()
                change_summary = []
                
                for change_type, count in change_types.items():
                    change_summary.append(f"{count}_{change_type}")
                
                return "_".join(change_summary)
                
        except Exception as e:
            # If detailed comparison fails, fall back to basic comparison
            self.change_logger.warning(f"Detailed comparison failed for {endpoint}: {e}, using basic comparison")
            
            if existing_df.shape != new_df.shape:
                return f"shape_changed_from_{existing_df.shape}_to_{new_df.shape}"
            else:
                return f"content_modified_{endpoint}_data"
    
    def _move_to_legacy(self, file_path: Path) -> str:
        """Move old file to legacy directory."""
        self.config.legacy_dir.mkdir(exist_ok=True)
        
        destination = self.config.legacy_dir / file_path.name
        
        # Handle naming conflicts
        if destination.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            name_parts = destination.stem.split('_')
            new_name = '_'.join(name_parts[:-1]) + f"_legacy_{timestamp}.csv"
            destination = self.config.legacy_dir / new_name
        
        shutil.move(str(file_path), str(destination))
        self.main_logger.info(f"Moved to legacy: {destination.name}")
        return str(destination)
    
    def _save_data(self, df: pd.DataFrame, endpoint: str, programme: ProgrammeMetadata) -> str:
        """Save dataframe to CSV file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{endpoint}_{programme.clean_name}_{timestamp}.csv"
        file_path = self.config.data_dir / filename
        
        df.to_csv(file_path, index=False)
        
        file_size = file_path.stat().st_size / (1024*1024)
        self.main_logger.info(f"Saved {len(df)} records ({file_size:.1f} MB) to {filename}")
        
        return str(file_path)

class ETLPipeline:
    """Main ETL Pipeline orchestrator."""
    
    def __init__(self, config: ETLConfig):
        self.config = config
        self.logger = ETLLogger(config)
        self.extractor = ETLExtractor(self.logger)
        self.transformer = ETLTransformer(self.logger)
        self.loader = ETLLoader(config, self.logger)
        
        self.main_logger = self.logger.main_logger
        self.change_logger = self.logger.change_logger
    
    def run(self) -> Dict[str, Any]:
        """Execute the complete ETL pipeline."""
        pipeline_start_time = time.time()
        
        self.main_logger.info("="*80)
        self.main_logger.info("ETL PIPELINE STARTING")
        self.main_logger.info("="*80)
        self.main_logger.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.main_logger.info(f"Configuration: {self.config}")
        
        # Initialize results tracking
        results = {
            'programmes_processed': 0,
            'endpoints_processed': 0,
            'total_records': 0,
            'files_saved': 0,
            'changes_detected': 0,
            'extraction_results': [],
            'transformation_results': [],
            'load_results': [],
            'timing': {
                'extraction': 0,
                'transformation': 0,
                'loading': 0,
                'total': 0
            }
        }
        
        try:
            # EXTRACT: Get programme metadata
            programmes = self.extractor.extract_programme_metadata(self.config)
            major_programmes = [p for p in programmes if p.record_count >= self.config.min_record_threshold]
            
            self.main_logger.info(f"Processing {len(major_programmes)} programmes (>={self.config.min_record_threshold} records) out of {len(programmes)} total programmes")
            
            # Process each programme
            for i, programme in enumerate(major_programmes, 1):
                self.main_logger.info("="*60)
                self.main_logger.info(f"PROGRAMME {i}/{len(major_programmes)}: {programme.name}")
                self.main_logger.info(f"Expected records: {programme.record_count:,}")
                self.main_logger.info("="*60)
                
                # Process each endpoint for this programme
                for endpoint in self.extractor.fetchers.keys():
                    # EXTRACT
                    extraction_result = self.extractor.extract_programme_data(programme, endpoint)
                    results['extraction_results'].append(extraction_result)
                    results['timing']['extraction'] += extraction_result.extraction_time
                    
                    if extraction_result.success:
                        # TRANSFORM
                        transformation_result = self.transformer.transform_data(extraction_result)
                        results['transformation_results'].append(transformation_result)
                        results['timing']['transformation'] += transformation_result.transformation_time
                        
                        if transformation_result.validation_passed:
                            # LOAD
                            load_result = self.loader.load_data(transformation_result)
                            results['load_results'].append(load_result)
                            results['timing']['loading'] += load_result.load_time
                            
                            # Update statistics
                            if load_result.file_path:
                                results['files_saved'] += 1
                                results['total_records'] += len(transformation_result.transformed_data)
                            
                            if load_result.change_detected:
                                results['changes_detected'] += 1
                
                results['programmes_processed'] += 1
            
            results['endpoints_processed'] = len(results['extraction_results'])
            
        except Exception as e:
            self.main_logger.error(f"Pipeline failed: {e}")
            raise
        
        finally:
            # Calculate final timing
            results['timing']['total'] = time.time() - pipeline_start_time
            
            # Log final summary
            self._log_final_summary(results)
        
        return results
    
    def _log_final_summary(self, results: Dict[str, Any]):
        """Log comprehensive pipeline summary."""
        self.main_logger.info("="*80)
        self.main_logger.info("ETL PIPELINE COMPLETED")
        self.main_logger.info("="*80)
        
        # Performance summary
        timing = results['timing']
        self.main_logger.info("PERFORMANCE SUMMARY:")
        self.main_logger.info(f"   Total execution time: {timing['total']:.1f}s")
        self.main_logger.info(f"   Extraction time: {timing['extraction']:.1f}s ({timing['extraction']/timing['total']*100:.1f}%)")
        self.main_logger.info(f"   Transformation time: {timing['transformation']:.1f}s ({timing['transformation']/timing['total']*100:.1f}%)")
        self.main_logger.info(f"   Loading time: {timing['loading']:.1f}s ({timing['loading']/timing['total']*100:.1f}%)")
        
        # Data summary
        self.main_logger.info("DATA SUMMARY:")
        self.main_logger.info(f"   Programmes processed: {results['programmes_processed']}")
        self.main_logger.info(f"   Endpoints processed: {results['endpoints_processed']}")
        self.main_logger.info(f"   Total records: {results['total_records']:,}")
        self.main_logger.info(f"   Files saved: {results['files_saved']}")
        self.main_logger.info(f"   Changes detected: {results['changes_detected']}")
        
        # Success rates
        successful_extractions = sum(1 for r in results['extraction_results'] if r.success)
        successful_transformations = sum(1 for r in results['transformation_results'] if r.validation_passed)
        
        self.main_logger.info("SUCCESS RATES:")
        self.main_logger.info(f"   Extraction success: {successful_extractions}/{len(results['extraction_results'])} ({successful_extractions/len(results['extraction_results'])*100:.1f}%)")
        self.main_logger.info(f"   Transformation success: {successful_transformations}/{len(results['transformation_results'])} ({successful_transformations/len(results['transformation_results'])*100:.1f}%)")
        
        self.main_logger.info(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.main_logger.info(f"Main log: {self.logger.log_file}")
        self.main_logger.info(f"Change log: {self.logger.change_log_file}")

def main():
    """Main entry point for the ETL pipeline."""
    # Set up configuration
    base_dir = Path.cwd()
    config = ETLConfig(
        data_dir=base_dir / "data",
        logs_dir=base_dir / "logs",
        legacy_dir=base_dir / "data" / "legacy",
        min_record_threshold=1,  # Changed from 100 to 1 to extract ALL programmes
        enable_change_detection=True,
        enable_legacy_management=True,
        log_level="INFO"
    )
    
    # Ensure directories exist
    config.data_dir.mkdir(exist_ok=True)
    config.logs_dir.mkdir(exist_ok=True)
    
    # Run the ETL pipeline
    pipeline = ETLPipeline(config)
    results = pipeline.run()
    
    return results['files_saved'] > 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 