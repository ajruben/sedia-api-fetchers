# SEDIA API Fetchers

Python classes for fetching data from the European Commission's SEDIA API endpoints.

## Overview

This package includes 5 specialized fetchers for different types of EU data:

| Fetcher | Purpose | API Key | Data Type |
|---------|---------|---------|-----------|
| `SEDIA_GET_PROJECTS` | EU funded projects | `SEDIA_NONH2020_PROD` | Project details, metadata, participants |
| `SEDIA_GET_PARTICIPANTS` | Organizations & persons | `SEDIA_PERSON` | Participant profiles, collaborations |
| `SEDIA_GET_FUNDING_TENDERS` | Calls & tenders | `SEDIA` | Grant opportunities, tender notices |
| `SEDIA_GET_TOPICS` | Topic details | `SEDIA` | Research topic specifications |
| `SEDIA_GET_FAQ` | FAQ system | `SEDIA_FAQ` | Frequently asked questions |

## Installation & Setup

### Prerequisites
```bash
pip install requests pandas numpy tqdm pathlib urllib3
```

### Directory Structure
```
src/EUFT_retrieve/
├── EUFT_retrieve_projects.py          # Projects fetcher
├── EUFT_retrieve_participants.py      # Participants fetcher  
├── EUFT_retrieve_funding_tenders.py   # Funding & tenders fetcher
├── EUFT_retrieve_topics.py            # Topics fetcher
├── EUFT_retrieve_faq.py               # FAQ fetcher
├── demo_all_fetchers.py               # Comprehensive demo
├── helpers/
│   └── functions.py                   # Utility functions
└── README.md                          # This file
```

## Architecture

### Base Classes

The fetchers use an inheritance-based architecture:

- **`SEDIABaseFetcher`** (Abstract): Common functionality for all fetchers
- **`SEDIAPaginatedFetcher`**: For POST-based endpoints with pagination  
- **`SEDIASimpleFetcher`**: For GET-based endpoints


## Common Features

All fetchers inherit these capabilities:

### Flexible Programme Input
```python
# Single programme by name
data = fetcher.get('h2020')

# Single programme by ID  
data = fetcher.get(31045243)

# Multiple programmes
data = fetcher.get(['h2020', 'horizon'])

# Mixed input
data = fetcher.get(['h2020', 43108390])
```

### Configuration Options
```python
fetcher = SEDIA_GET_PROJECTS(
    flatten_metadata=True,      # Flatten nested JSON structures
    enrich_with_details=False   # Fetch detailed info (projects only)
)
```

### Data Management
- Automatic timestamping: Files saved with timestamp
- Progress tracking: Real-time progress bars
- Error handling: Robust retry mechanisms
- Memory efficient: Chunked processing for large datasets

### Consistent API Pattern
```python
# Basic usage
data = fetcher.get(programmes, save=True)

# Advanced usage with filters
data = fetcher.get(
    programmes=['h2020', 'horizon'],
    additional_filters='value',
    save=True
)
```

## Detailed Usage Guide

### 1. Projects Fetcher (`SEDIA_GET_PROJECTS`)

Fetches project data with optional enrichment.

```python
from EUFT_retrieve_projects import SEDIA_GET_PROJECTS

# Basic usage
fetcher = SEDIA_GET_PROJECTS(flatten_metadata=True)
data = fetcher.get('edf', save=True)

# With detailed project enrichment
fetcher = SEDIA_GET_PROJECTS(
    flatten_metadata=True,
    enrich_with_details=True  # Fetches detailed project info
)
data = fetcher.get(['h2020', 'horizon'], save=True)
```

Features:
- Handles >10K records via date-range partitioning
- Optional project detail enrichment
- Metadata flattening
- Automatic duplicate handling

**Architecture**: Inherits from `SEDIAPaginatedFetcher`

### 2. Participants Fetcher (`SEDIA_GET_PARTICIPANTS`)

Fetches organization and person data from EU programmes.

```python
from EUFT_retrieve_participants import SEDIA_GET_PARTICIPANTS

fetcher = SEDIA_GET_PARTICIPANTS(flatten_metadata=True)

# Fetch all participants for EDF programme
data = fetcher.get('edf', save=True)

# Multiple programmes
data = fetcher.get(['h2020', 'horizon'], save=True)
```

Features:
- Fetches ORGANISATION and PERSON types
- Participant metadata flattening
- Programme-specific filtering
- Collaboration network data

**Architecture**: Inherits from `SEDIAPaginatedFetcher`

### 3. Funding & Tenders Fetcher (`SEDIA_GET_FUNDING_TENDERS`)

Fetches grant opportunities and tender notices.

```python
from EUFT_retrieve_funding_tenders import SEDIA_GET_FUNDING_TENDERS

fetcher = SEDIA_GET_FUNDING_TENDERS(flatten_metadata=True)

# Open grants for Horizon Europe
data = fetcher.get(
    programmes='horizon',
    funding_type='grants',    # 'grants', 'tenders', 'all'
    status='open',           # 'open', 'closed', 'all'
    save=True
)

# All tenders regardless of programme
data = fetcher.get(
    programmes=None,         # All programmes
    funding_type='tenders',
    status='all',
    save=True
)

# With additional filters
data = fetcher.get(
    programmes='h2020',
    programmePeriod='2014 - 2020',
    crossCuttingPriorities=['OCEAN'],
    save=True
)
```

Available Options:
- Funding types: `grants`, `tenders`, `all`
- Status: `open`, `closed`, `all`
- Additional filters: Any valid API parameter

**Architecture**: Inherits from `SEDIAPaginatedFetcher`

### 4. Topics Fetcher (`SEDIA_GET_TOPICS`)

Fetches detailed information about specific research topics.

```python
from EUFT_retrieve_topics import SEDIA_GET_TOPICS

fetcher = SEDIA_GET_TOPICS(flatten_metadata=True)

# Single topic
data = fetcher.get('HORIZON-CL3-2022-BM-01-01', save=True)

# Multiple topics
topics = [
    'HORIZON-CL3-2022-BM-01-01',
    'HORIZON-CL4-2022-RESILIENCE-01-08'
]
data = fetcher.get(topics, save=True)
```

Features:
- Topic-specific detailed information
- Batch processing for multiple topics
- Missing topic tracking
- Research area categorization

**Architecture**: Inherits from `SEDIASimpleFetcher` (uses GET requests)

### 5. FAQ Fetcher (`SEDIA_GET_FAQ`)

Fetches FAQ index and detailed FAQ content.

```python
from EUFT_retrieve_faq import SEDIA_GET_FAQ

fetcher = SEDIA_GET_FAQ(flatten_metadata=True)

# FAQ index for specific programme
data = fetcher.get(
    programmes='h2020',
    faq_type='all',          # 'active', 'archived', 'all'
    status='all',            # 'active', 'archived', 'all'
    save=True
)

# FAQ index with detailed content
data = fetcher.get(
    programmes='horizon',
    fetch_details=True,      # Fetch full FAQ content
    save=True
)

# Specific FAQ details by NID
data = fetcher.get(
    nid_list=['755', '12350'],
    save=True
)
```

Available Options:
- FAQ types: `active`, `archived`, `all`
- Status: `active`, `archived`, `all`
- Details: `fetch_details=True` for complete content

**Architecture**: Uses `SEDIAPaginatedFetcher` (when migrated)

## Quick Start Demo

Run the demo:

```bash
cd src/EUFT_retrieve
python demo_all_fetchers.py
```

Demonstrates:
- All 5 fetchers with example usage
- Flexible input handling
- Data processing capabilities
- Error handling features
- Advanced usage patterns

## Programme IDs Reference

| Programme | Name | ID |
|-----------|------|-----|
| `h2020` | Horizon 2020 | 31045243 |
| `horizon` | Horizon Europe | 43108390 |
| `digital` | Digital Europe | 43152860 |
| `edf` | European Defence Fund | 44181033 |

## Advanced Usage

### Custom Query Parameters

All fetchers support additional query parameters via `**kwargs`:

```python
# Funding & Tenders with custom filters
data = fetcher.get(
    programmes='horizon',
    funding_type='grants',
    programmePeriod='2021 - 2027',
    crossCuttingPriorities=['CLIMATE'],
    destination=['43650651'],
    save=True
)
```

### Error Handling

```python
try:
    data = fetcher.get('invalid_programme')
except ValueError as e:
    print(f"Invalid programme: {e}")
except Exception as e:
    print(f"API error: {e}")
```

### Memory Management

For large datasets:

```python
# Disable metadata flattening for faster processing
fetcher = SEDIA_GET_PROJECTS(flatten_metadata=False)

# Process in smaller chunks
data = fetcher.get('h2020', save=True)  # Automatically chunked
```

### Data Processing Pipeline

```python
from helpers.functions import Functions

# Load and process cached data
df = Functions.load_cached_dataframe('cache/my_data.feather')

# Apply custom flattening
df_flat = Functions.flatten_dataframe_metadata(df)

# Clean empty containers
df_clean = Functions.clean_empty_containers(df_flat)
```

## Output Files

All fetchers generate timestamped CSV files:

```
data/
├── project_data_44181033_20241201_143022.csv
├── participant_data_44181033_20241201_143155.csv
├── funding_tenders_data_horizon_grants_open_20241201_143301.csv
├── topic_details_HORIZON-CL3-2022-BM-01-01_20241201_143445.csv
└── faq_data_31045243_all_all_20241201_143612.csv
```

## Important Notes

### API Rate Limits
- Retry mechanisms handle rate limiting
- Automatic backoff for server errors
- Session management

### Data Size Considerations
- Projects fetcher handles >10K records via partitioning
- Other fetchers may hit 10K API limits
- Use programme filters to reduce dataset size

### Memory Usage
- Metadata flattening increases memory usage
- Disable flattening for very large datasets
- Use chunked processing

## Contributing

To extend the fetchers:

1. Follow the existing class structure
2. Implement consistent API patterns
3. Add error handling
4. Include progress tracking
5. Update this README

## License

This project is part of the EU thesis research toolkit. Please refer to the main project license.

## Support

For issues or questions:
1. Check the demo script for usage examples
2. Review error messages for specific issues
3. Verify programme IDs and API parameters
4. Ensure network connectivity to EU APIs

---
