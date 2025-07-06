import pandas as pd
import numpy as np
import warnings
from typing import Any, Dict, List, Tuple, Union
import json
import logging
from pathlib import Path
import os 
import pickle
import ast
import hashlib

class Functions:
    def __init__(self):
        pass

    @staticmethod
    def _cell_to_hashable_string(cell_value):
        """Converts a cell value to a hashable string, handling lists by sorting and joining."""
        if isinstance(cell_value, list):
            try:
                return ",".join(sorted(map(str, cell_value)))
            except TypeError:
                return ",".join(map(str, cell_value))
        elif pd.isna(cell_value):
            return "<NA>"
        return str(cell_value)

    @staticmethod
    def compare_dataframes(df_old: pd.DataFrame,
                           df_new: pd.DataFrame,
                           check_columns: list = [],
                           unique_key: str | list = [],
                           detect_column_changes: bool = False) -> pd.DataFrame:
        """
        Compare two dataframes and return a dataframe with the changes.
        """
        df_old = df_old.copy()
        df_new = df_new.copy()

        if isinstance(unique_key, list):
            combined_unique_key_name = 'combined_unique_key'
            for df_idx, df_ref in enumerate([df_old, df_new]):
                current_df = df_ref
                if current_df.empty:
                    current_df[combined_unique_key_name] = pd.Series(dtype=str)
                elif not all(col in current_df.columns for col in unique_key):
                    logging.warning(f"DataFrame at index {df_idx} is missing one or more columns from composite unique_key: {unique_key}. Adding empty '{combined_unique_key_name}'.")
                    current_df[combined_unique_key_name] = pd.Series(dtype=str)
                else:
                    current_df[combined_unique_key_name] = current_df[unique_key].astype(str).agg('|'.join, axis=1)
            unique_key = combined_unique_key_name

        cols_for_comparison_and_subset = check_columns[:]
        if unique_key not in cols_for_comparison_and_subset:
            cols_for_comparison_and_subset.append(unique_key)

        # Apply _cell_to_hashable_string to all columns involved in comparison/subsetting
        for col_name in cols_for_comparison_and_subset:
            if col_name in df_old.columns:
                df_old[col_name] = df_old[col_name].apply(Functions._cell_to_hashable_string)
            if col_name in df_new.columns:
                df_new[col_name] = df_new[col_name].apply(Functions._cell_to_hashable_string)

        # Check if the unique_key is unique in the dataframes
        if not df_old.empty and unique_key in df_old.columns:
            if not df_old[unique_key].is_unique:
                logging.warning(f"Duplicates found in df_old based on unique_key '{unique_key}'. This might affect comparison logic.")

        if not df_new.empty and unique_key in df_new.columns:
            if not df_new[unique_key].is_unique:
                logging.error(f"CRITICAL: Duplicates found in df_new based on unique_key '{unique_key}'. This indicates issues with data fetching or prior processing.")
                raise ValueError('The unique_key column is not unique in the new dataframe')
        elif df_new.empty:
             logging.warning("df_new is empty. Comparison will likely show all old records as deleted.")
        elif unique_key not in df_new.columns and not df_new.empty:
            logging.error(f"CRITICAL: unique_key '{unique_key}' not found in df_new. Cannot proceed with comparison.")
            raise KeyError(f"unique_key '{unique_key}' not found in df_new columns: {df_new.columns.tolist()}")

        # Handle column changes detection
        if detect_column_changes:
            if not df_new.empty:
                added_columns_list = [column for column in df_new.columns.values if column not in df_old.columns.values and column not in cols_for_comparison_and_subset]
                if added_columns_list:
                    new_cols_data = {col: Functions._cell_to_hashable_string(pd.NA) for col in added_columns_list}
                    new_cols_df = pd.DataFrame(new_cols_data, index=df_old.index).astype(dtype={key: 'object' for key in added_columns_list})
                    df_old = pd.concat([df_old, new_cols_df], axis=1)
            else:
                added_columns_list = []

            if not df_old.empty:
                deleted_columns_list = [column for column in df_old.columns.values if column not in df_new.columns.values and column != unique_key and column not in added_columns_list and column not in cols_for_comparison_and_subset]
                if deleted_columns_list:
                    new_cols_data = {col: Functions._cell_to_hashable_string(pd.NA) for col in deleted_columns_list}
                    new_cols_df = pd.DataFrame(new_cols_data, index=df_new.index).astype(dtype={key: 'object' for key in deleted_columns_list})
                    df_new = pd.concat([df_new, new_cols_df], axis=1)
            else:
                deleted_columns_list = []

        # Check column types
        if not df_old.empty and not df_new.empty:
            common_columns_for_type_check = [col for col in (check_columns + [unique_key]) if col in df_old.columns and col in df_new.columns]
            for column in common_columns_for_type_check:
                old_dtype = df_old[column].dtype
                new_dtype = df_new[column].dtype
                numeric_types = ['int64', 'float64']
                if old_dtype != new_dtype and not (old_dtype in numeric_types and new_dtype in numeric_types):
                    if df_old[column].notna().sum() == 0 or df_new[column].notna().sum() == 0:
                        logging.warning(f"Type difference in column '{column}' ({old_dtype} vs {new_dtype}), but one is all NA. Proceeding with caution.")
                    else:
                        raise ValueError(
                                        f"Type mismatch in column '{column}': df_old has {old_dtype}, df_new has {new_dtype}."
                                        )
        elif df_old.empty and df_new.empty:
            logging.info("Both df_old and df_new are empty. No type comparison needed.")
        else:
            logging.info("One of the dataframes is empty. Skipping type comparison.")

        # Track values before concat
        if not df_old.empty:
            df_old = df_old.assign(flag_old=1)
        if not df_new.empty:
            df_new = df_new.assign(flag_old=0)

        # Handle empty DataFrames
        if df_old.empty and df_new.empty:
            logging.info("Both df_old and df_new are empty. No changes to report.")
            cols_to_return = check_columns + ([unique_key] if unique_key not in check_columns else []) + ['change_type', 'changes']
            return pd.DataFrame(columns=cols_to_return)
        elif df_old.empty:
            logging.info("df_old is empty. All records in df_new will be marked as 'new'.")
            df_changes_final = df_new.copy()
            if unique_key not in df_changes_final.columns and unique_key == 'combined_unique_key' and 'combined_unique_key' in df_changes_final.columns:
                 pass
            elif unique_key not in df_changes_final.columns:
                 df_changes_final = df_changes_final.assign(**{unique_key: Functions._cell_to_hashable_string(pd.NA)})
            df_changes_final = df_changes_final.assign(change_type='new', changes='')
            cols_to_return = [c for c in df_new.columns if c != 'flag_old'] + ['change_type', 'changes']
            if unique_key not in cols_to_return and unique_key in df_changes_final.columns:
                if unique_key in cols_to_return: cols_to_return.remove(unique_key)
                cols_to_return.insert(0, unique_key)
            return df_changes_final.reindex(columns=cols_to_return, fill_value='')
        elif df_new.empty:
            logging.info("df_new is empty. All records in df_old will be marked as 'deleted'.")
            df_changes_final = df_old.copy()
            if unique_key not in df_changes_final.columns and unique_key == 'combined_unique_key' and 'combined_unique_key' in df_changes_final.columns:
                pass
            elif unique_key not in df_changes_final.columns:
                df_changes_final = df_changes_final.assign(**{unique_key: Functions._cell_to_hashable_string(pd.NA)})
            df_changes_final = df_changes_final.assign(change_type='deleted', changes='')
            cols_to_return = [c for c in df_old.columns if c != 'flag_old'] + ['change_type', 'changes']
            if unique_key not in cols_to_return and unique_key in df_changes_final.columns:
                if unique_key in cols_to_return: cols_to_return.remove(unique_key)
                cols_to_return.insert(0, unique_key)
            return df_changes_final.reindex(columns=cols_to_return, fill_value='')

        # Concat and drop duplicates
        subset_cols = cols_for_comparison_and_subset
        df_concatenated = pd.concat([df_old, df_new], ignore_index=True)

        actual_cols_in_concatenated_df = df_concatenated.columns.tolist()
        final_subset_cols_for_drop = [col for col in subset_cols if col in actual_cols_in_concatenated_df]

        if not final_subset_cols_for_drop and subset_cols:
            logging.error(
                f"Attempting to drop duplicates: NO columns from the intended subset ({subset_cols}) "
                f"were found in the concatenated DataFrame. This will likely not work as expected. "
                f"Concatenated DF columns: {actual_cols_in_concatenated_df}. Skipping drop_duplicates effectively."
            )
            df = df_concatenated
        else:
            if len(final_subset_cols_for_drop) != len(subset_cols) and subset_cols:
                missing_in_concatenated = set(subset_cols) - set(final_subset_cols_for_drop)
                logging.warning(
                    f"Attempting to drop duplicates: Some columns from the intended subset ({subset_cols}) "
                    f"were NOT FOUND in the concatenated DataFrame. Missing columns: {list(missing_in_concatenated)}. "
                    f"Proceeding with available columns: {final_subset_cols_for_drop}. "
                    f"Concatenated DF columns: {actual_cols_in_concatenated_df}"
                )
            df = df_concatenated.drop_duplicates(subset=final_subset_cols_for_drop if final_subset_cols_for_drop else None, keep=False)

        # Handle empty df after concat
        if df.empty:
            final_cols = check_columns[:]
            if unique_key not in final_cols:
                final_cols.insert(0, unique_key)
            elif unique_key in final_cols and unique_key == 'combined_unique_key':
                 final_cols.remove(unique_key)
                 final_cols.insert(0, unique_key)
            final_cols.extend(['change_type', 'changes'])
            seen = set()
            ordered_final_cols = [x for x in final_cols if not (x in seen or seen.add(x))]
            return pd.DataFrame(columns=ordered_final_cols)

        # Determine change types
        df = df.assign(
            freq=df.groupby(unique_key, observed=True)[unique_key].transform('count')
        )
        df = df.assign(
            change_type=np.select(
                condlist=[
                    (df['freq'] == 1) & (df['flag_old'] == 0),
                    (df['freq'] == 1) & (df['flag_old'] == 1),
                    (df['freq'] == 2)
                ],
                choicelist=[
                    'new',
                    'deleted',
                    'edited'
                ],
                default='duplicates_after_string_conversion'
            )
        )

        # Check which values in which column are changed
        df.sort_values(by=[unique_key] + ['flag_old'], inplace=True, ascending=False)
        df.reset_index(inplace=True, drop=True)

        df = df.assign(changes=pd.Series(dtype='object'))
        changes_list = [None] * len(df)

        relevant_columns_for_change_detection = check_columns[:]
        if unique_key not in relevant_columns_for_change_detection:
            relevant_columns_for_change_detection.append(unique_key)

        for i in df.index:
            if df.loc[i, 'change_type'] == 'edited':
                if i > 0 and df.loc[i, unique_key] == df.loc[i - 1, unique_key]:
                    curr_dict = df.loc[i, relevant_columns_for_change_detection].to_dict()
                    prev_dict = df.loc[i - 1, relevant_columns_for_change_detection].to_dict()

                    changed_columns_dict = {}
                    for key in relevant_columns_for_change_detection:
                        if key == unique_key: continue

                        val_curr = curr_dict.get(key)
                        val_prev = prev_dict.get(key)

                        if str(val_curr) != str(val_prev):
                             changed_columns_dict[key] = str(val_prev)

                    if changed_columns_dict:
                        changes_list[i] = json.dumps(changed_columns_dict)
                else:
                    logging.warning(f"Row {i} marked 'edited' but no matching previous row found for {df.loc[i, unique_key]}. 'changes' will be empty.")
                    changes_list[i] = json.dumps({})
            else:
                changes_list[i] = json.dumps({})

        df['changes'] = pd.Series(changes_list, index=df.index)

        df = df[(df['flag_old'] == 0) | (df['change_type'] == 'deleted')]
        df.drop(labels=['flag_old', 'freq'], axis='columns', inplace=True, errors='ignore')

        # Final column selection and ordering
        final_columns_ordered = []
        if unique_key in df.columns:
            final_columns_ordered.append(unique_key)

        for col in check_columns:
            if col not in final_columns_ordered:
                final_columns_ordered.append(col)

        final_columns_ordered.extend(['change_type', 'changes'])

        for col in df.columns:
            if col not in final_columns_ordered:
                final_columns_ordered.append(col)

        df = df.reindex(columns=final_columns_ordered)
        return df.copy()
    
    @staticmethod
    def load_and_stitch_cordis_json(base_data_path = r"/mnt/c/Users/Ruben/GPUcodig/thesis_EU/data/cordis_data") -> pd.DataFrame:
        """
        Loads and stitches together fragmented CORDIS JSON files from specified subdirectories.
        requires the following files to be present:
        - project.json
        - policyPriorities.json
        - organization.json
        - projectDeliverables.json
        - projectPublications.json
        - reportSummaries.json
        - euroSciVoc.json
        - legalBasis.json
        - topics.json
        - webLink.json
        requires following dir structure:
        - cordis_data
            - cordis_h2020
                - *.json
            - cordis_horizon
                - *.json
        
        Args:
            base_data_path: The root directory containing 'cordis_h2020' and 'cordis_horizon'.

        Returns:
            A single, stitched pandas DataFrame with one row per project.
        """
        base_data_path = Path(base_data_path)
        h2020_path = base_data_path / 'cordis_h2020'
        horizon_path = base_data_path / 'cordis_horizon'
        
        print(f"Reading CORDIS files from:\n- {h2020_path}\n- {horizon_path}")

        def _load_and_concat(filename: str) -> pd.DataFrame | None:
            """Helper to safely load and combine JSON files from both directories."""
            dfs = []
            for path in [h2020_path, horizon_path]:
                file_path = path / filename
                if file_path.exists():
                    with open(file_path, 'r', encoding='utf-8-sig') as f:
                        try:
                            data = json.load(f)
                            df = pd.DataFrame(data)
                            df['sourceProgram'] = path.name
                            dfs.append(df)
                        except json.JSONDecodeError:
                            print(f"Warning: Could not decode JSON from {file_path}. Skipping.")
                else:
                    print(f"Info: '{filename}' not found in '{path.name}'. Skipping.")
            
            if not dfs:
                return None
            return pd.concat(dfs, ignore_index=True)

        print("\nProcessing core project data...")
        projects_df = _load_and_concat("project.json")
        if projects_df is None:
            raise FileNotFoundError("Core file 'project.json' not found in any directory.")
        
        projects_df.rename(columns={'id': 'projectID'}, inplace=True)
        print(f"Loaded {len(projects_df)} total projects.")

        # Merge one-to-one relationships
        one_to_one_files = ["policyPriorities.json"]
        for filename in one_to_one_files:
            print(f"Merging '{filename}'...")
            df_to_merge = _load_and_concat(filename)
            if df_to_merge is not None:
                projects_df = pd.merge(
                    projects_df, df_to_merge, on='projectID', how='left', 
                    suffixes=('', f'_{filename.split(".")[0]}')
                )

        # Aggregate and merge one-to-many relationships
        one_to_many_map = {
            "organization.json": "participants",
            "projectDeliverables.json": "deliverables",
            "projectPublications.json": "publications",
            "reportSummaries.json": "reportSummaries",
            "euroSciVoc.json": "euroSciVoc",
            "legalBasis.json": "legalBases",
            "topics.json": "topics",
            "webLink.json": "webLinks"
        }

        for filename, new_col_name in one_to_many_map.items():
            print(f"Aggregating '{filename}' into '{new_col_name}'...")
            df_to_agg = _load_and_concat(filename)
            if df_to_agg is not None and 'projectID' in df_to_agg.columns:
                agg_series = df_to_agg.groupby('projectID').apply(
                    lambda x: x.drop(columns=['projectID']).to_dict('records')
                )
                agg_series.name = new_col_name
                projects_df = projects_df.merge(agg_series, on='projectID', how='left')

        print("\nStitching complete.")
        return projects_df
    
    @staticmethod
    def _deep_parse(val: Any) -> Any:
        if isinstance(val, list) and len(val) == 1 and isinstance(val[0], str): val = val[0]
        while isinstance(val, str):
            original_val = val
            try: val = ast.literal_eval(val)
            except (ValueError, SyntaxError, MemoryError): break
            if val == original_val: break
        return val

    @staticmethod
    def _fingerprint(obj: Any) -> str:
        payload = json.dumps(obj, sort_keys=True, default=str).encode()
        return hashlib.blake2b(payload, digest_size=8).hexdigest()

    @staticmethod
    def _safe_col_name(col: str) -> str:
        return "".join(c if c.isalnum() else '_' for c in col).lower().strip('_')

    @staticmethod
    def normalise(df: pd.DataFrame, ref_col: str, pfx: str, cols: List[str]) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
        fact = df.copy()
        dim_tables: Dict[str, pd.DataFrame] = {}
        if ref_col not in fact.columns: raise KeyError(f"Input DataFrame must contain the specified reference column: '{ref_col}'.")
        for col in [c for c in cols if c in fact.columns]:
            print(f"Normalizing column: {col}")
            safe_name = Functions._safe_col_name(col)
            parsed_col = df[col].apply(Functions._deep_parse)
            records = []
            for ref, parsed_item_or_list in zip(df[ref_col], parsed_col):
                if isinstance(parsed_item_or_list, list):
                    for item in parsed_item_or_list: records.append({ref_col: ref, 'parsed': item})
                elif parsed_item_or_list: records.append({ref_col: ref, 'parsed': parsed_item_or_list})
            if not records:
                print(f"  INFO: Column '{col}' has no valid data after parsing. Skipping.")
                continue
            exploded = pd.DataFrame(records).explode("parsed").dropna(subset=["parsed"])
            exploded["_fp"] = exploded["parsed"].apply(Functions._fingerprint)
            unique_items = exploded.drop_duplicates(subset=["_fp"]).copy()
            try:
                normalized_data = pd.json_normalize(unique_items['parsed'])
                normalized_data.columns = [Functions._safe_col_name(c) for c in normalized_data.columns]
                dim_df = pd.concat([unique_items[['_fp']].reset_index(drop=True), normalized_data.reset_index(drop=True)], axis=1)
            except (AttributeError, TypeError):
                dim_df = unique_items[['_fp', 'parsed']].rename(columns={"parsed": f"{safe_name}_value"})
            dim_df.insert(0, f"{safe_name}_id", range(1, len(dim_df) + 1))
            dim_tables[f"dim_{pfx}_{safe_name}"] = dim_df.drop(columns=['_fp'], errors='ignore')
            junction = pd.merge(exploded[[ref_col, '_fp']], dim_df[['_fp', f"{safe_name}_id"]], on="_fp", how="left")
            junction = junction[[ref_col, f"{safe_name}_id"]].drop_duplicates().dropna()
            dim_tables[f"junction_{pfx}_{safe_name}"] = junction
            id_map_df = junction.groupby(ref_col)[f"{safe_name}_id"].apply(list).reset_index()
            id_map_df.rename(columns={f"{safe_name}_id": "id_list"}, inplace=True)
            if col in fact.columns: fact = fact.drop(columns=[col])
            fact = pd.merge(fact, id_map_df, on=ref_col, how='left')
            fact['id_list'] = fact['id_list'].fillna("[]").astype(str)
            fact.rename(columns={'id_list': col}, inplace=True)
            print(f"  SUCCESS: Created dim_{pfx}_{safe_name} and junction_{pfx}_{safe_name}")
        return fact, dim_tables

    @staticmethod
    def cache_dataframe(df, cache_file='cache/cordis_data_cache.feather'):
        """Cache dataframe to feather file for faster reloading"""
        cache_dir = os.path.dirname(cache_file)
        if cache_dir and not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
            print(f"Created cache directory: {cache_dir}")
        
        df_to_cache = df.copy()
        
        # Handle mixed-type columns that Feather doesn't like
        for col in df_to_cache.columns:
            if df_to_cache[col].dtype == 'object':
                df_to_cache[col] = df_to_cache[col].astype(str)
        
        df_to_cache.to_feather(cache_file)
        print(f"DataFrame cached to {cache_file} (Feather format - faster loading!)")

    @staticmethod
    def load_cached_dataframe(cache_file='cache/cordis_data_cache.feather'):
        """Load dataframe from cache if available"""
        if os.path.exists(cache_file):
            print(f"Loading cached DataFrame from {cache_file} (Feather format)")
            return pd.read_feather(cache_file)
        else:
            # Check for legacy pickle cache and convert if found
            pickle_cache = cache_file.replace('.feather', '.pkl')
            if os.path.exists(pickle_cache):
                print(f"Found legacy pickle cache at {pickle_cache}, converting to Feather format...")
                with open(pickle_cache, 'rb') as f:
                    df = pickle.load(f)
                Functions.cache_dataframe(df, cache_file)
                print(f"Conversion complete! Future loads will be faster.")
                return df
            else:
                print("No cache found, loading from source...")
                return None
            
    @staticmethod
    def _unwrap(value):
        """
        If `value` is a single‐element list, return its only element.
        If it's an empty list, return None.
        Otherwise, return `value` unchanged.
        """
        if isinstance(value, list):
            if len(value) == 1:
                return value[0]
            if len(value) == 0:
                return None
        return value

    @staticmethod
    def _parse_participants(raw_value):
        """
        Parse a JSON‐string (or single‐element list containing a JSON‐string) of participants,
        flatten any 'postalAddress' → 'countryCode' substructure, and return a list of dicts.
        If parsing fails, return the original `raw_value`.
        """
        candidate = Functions._unwrap(raw_value)
        if not isinstance(candidate, str):
            return raw_value

        try:
            parsed_list = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            return raw_value

        flattened = []
        for entry in parsed_list:
            flat_entry = {}
            for k, v in entry.items():
                if k == "postalAddress" and isinstance(v, dict):
                    for addr_key, addr_val in v.items():
                        if addr_key == "countryCode" and isinstance(addr_val, dict):
                            for cc_key, cc_val in addr_val.items():
                                flat_entry[f"address_country_{cc_key}"] = cc_val
                        else:
                            flat_entry[f"address_{addr_key}"] = addr_val
                else:
                    flat_entry[k] = v
            flattened.append(flat_entry)
        return flattened

    @staticmethod
    def _flatten_metadata_section(metadata: dict, flat_data: dict, prefix: str):
        """
        For each key/value in `metadata`, write a new prefixed key into `flat_data`.
        - 'participants' is processed via `_parse_participants()`.
        - Other keys are unwrapped via `_unwrap()`.
        """
        for key, val in metadata.items():
            new_key = f"{prefix}{key}"
            if key == "participants":
                flat_data[new_key] = Functions._parse_participants(val)
            else:
                flat_data[new_key] = Functions._unwrap(val)

    @staticmethod
    def flatten_project_data(input_json: dict) -> dict:
        """
        Flatten the JSON structure by preserving all original fields but adding prefixed,
        flattened counterparts. No original data is removed or overwritten; everything from
        `project_data` becomes `project_data_<field>` (and `project_data_metadata_<field>` for inner metadata).
        Top-level metadata becomes `metadata_<field>`, and other top-level keys remain as-is (unwrapped).
        """
        working = dict(input_json)
        flat_data = {}

        # Flatten `project_data` contents under `project_data_…`
        project_data = working.get("project_data", {}) or {}

        # Flatten `project_data.metadata` → `project_data_metadata_<field>`
        proj_meta = project_data.get("metadata", {}) or {}
        Functions._flatten_metadata_section(proj_meta, flat_data, prefix="project_data_metadata_")

        # Flatten other `project_data` keys → `project_data_<field>`
        for key, val in project_data.items():
            if key == "metadata":
                continue
            flat_data[f"project_data_{key}"] = Functions._unwrap(val)

        # Flatten top-level `metadata` → `metadata_<field>`
        top_meta = working.get("metadata", {}) or {}
        Functions._flatten_metadata_section(top_meta, flat_data, prefix="metadata_")

        # Preserve all other top-level keys exactly (with _unwrap on lists)
        for key, val in working.items():
            if key in ("project_data", "metadata"):
                continue
            flat_data[key] = Functions._unwrap(val)

        return flat_data

    @staticmethod
    def clean_empty_containers(df: pd.DataFrame) -> pd.DataFrame:
        """Enhanced empty container cleaning from other sources."""
        patterns = [
            r'^[\[\{]\s*(None|null|nan)?\s*[\]\}]$',
            r'^\[\]$',
            r'^\{\}$',
            r'^null$',
            r'^None$',
        ]

        for pattern in patterns:
            df = df.replace(to_replace=pattern, value=np.nan, regex=True)

        return df.map(lambda cell: np.nan if isinstance(cell, (list, dict)) and not cell else cell)

    @staticmethod
    def flatten_dataframe_metadata(df: pd.DataFrame) -> pd.DataFrame:
        """
        Flatten metadata in all columns of a DataFrame with proper unwrapping.
        Processes each row and flattens complex nested structures using the detailed project logic.
        """
        if df.empty:
            return df

        print(f"Applying comprehensive metadata flattening to {len(df):,} records...")
        flattened_records = []

        for idx, row in df.iterrows():
            if idx % 1000 == 0 and idx > 0:
                print(f"  Processed {idx:,}/{len(df):,} records...")

            try:
                row_dict = row.to_dict()
                flattened_row = Functions.flatten_project_data(row_dict)
                flattened_records.append(flattened_row)
            except Exception as e:
                print(f"Warning: Could not flatten record {idx}: {e}")
                fallback_row = {}
                for key, value in row.to_dict().items():
                    fallback_row[key] = Functions._unwrap(value)
                flattened_records.append(fallback_row)

        flattened_df = pd.DataFrame(flattened_records)
        flattened_df = Functions.clean_empty_containers(flattened_df)

        print(f"Comprehensive flattening complete!")
        print(f"  Original columns: {len(df.columns)}")
        print(f"  Flattened columns: {len(flattened_df.columns)}")
        print(f"  New columns added: {len(flattened_df.columns) - len(df.columns)}")

        return flattened_df
