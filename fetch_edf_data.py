#!/usr/bin/env python3
"""
EDF Data Retrieval Script
========================
Fetches all available data related to the European Defence Fund (EDF) programme
from all SEDIA API endpoints using the refactored fetchers.
"""

import sys
from pathlib import Path

# Add current directory to path for imports
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

def fetch_edf_data():
    """Fetch all EDF-related data from all available endpoints."""
    
    print("🚀 Starting EDF data retrieval...")
    
    # Import all fetchers
    try:
        from EUFT_retrieve_projects import SEDIA_GET_PROJECTS
        from EUFT_retrieve_participants import SEDIA_GET_PARTICIPANTS
        from EUFT_retrieve_funding_tenders import SEDIA_GET_FUNDING_TENDERS
        from EUFT_retrieve_topics import SEDIA_GET_TOPICS
        from EUFT_retrieve_faq import SEDIA_GET_FAQ
        print("✅ All fetchers imported successfully")
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    
    results = {}
    
    # 1. Fetch EDF Projects
    print("\n📊 Fetching EDF projects...")
    try:
        projects_fetcher = SEDIA_GET_PROJECTS(flatten_metadata=True, enrich_with_details=False)
        projects_data = projects_fetcher.get('edf', save=True)
        results['projects'] = len(projects_data)
        print(f"✅ Retrieved {len(projects_data)} EDF projects")
    except Exception as e:
        print(f"❌ Projects fetch failed: {e}")
        results['projects'] = 0
    
    # 2. Fetch EDF Participants
    print("\n👥 Fetching EDF participants...")
    try:
        participants_fetcher = SEDIA_GET_PARTICIPANTS(flatten_metadata=True)
        participants_data = participants_fetcher.get('edf', save=True)
        results['participants'] = len(participants_data)
        print(f"✅ Retrieved {len(participants_data)} EDF participants")
    except Exception as e:
        print(f"❌ Participants fetch failed: {e}")
        results['participants'] = 0
    
    # 3. Fetch EDF Funding & Tenders
    print("\n💰 Fetching EDF funding & tenders...")
    try:
        funding_fetcher = SEDIA_GET_FUNDING_TENDERS(flatten_metadata=True)
        funding_data = funding_fetcher.get('edf', funding_type='all', status='all', save=True)
        results['funding_tenders'] = len(funding_data)
        print(f"✅ Retrieved {len(funding_data)} EDF funding & tenders records")
    except Exception as e:
        print(f"❌ Funding & tenders fetch failed: {e}")
        results['funding_tenders'] = 0
    
    # 4. Fetch EDF FAQ
    print("\n❓ Fetching EDF FAQ...")
    try:
        faq_fetcher = SEDIA_GET_FAQ(flatten_metadata=True)
        faq_data = faq_fetcher.get('edf', faq_type='all', status='all', save=True)
        results['faq'] = len(faq_data)
        print(f"✅ Retrieved {len(faq_data)} EDF FAQ records")
    except Exception as e:
        print(f"❌ FAQ fetch failed: {e}")
        results['faq'] = 0
    
    # 5. Note about Topics (no programme-specific filtering)
    print("\n📚 Topics fetcher available but requires specific topic identifiers")
    results['topics'] = 'N/A - requires specific topic IDs'
    
    # Summary
    print("\n" + "="*60)
    print("🎉 EDF DATA RETRIEVAL COMPLETE")
    print("="*60)
    
    total_records = sum(v for v in results.values() if isinstance(v, int))
    
    for endpoint, count in results.items():
        print(f"   {endpoint.title()}: {count}")
    
    print(f"\n📊 Total EDF records retrieved: {total_records}")
    print("💾 All data saved to timestamped CSV files in the data/ directory")
    
    return True

if __name__ == "__main__":
    success = fetch_edf_data()
    sys.exit(0 if success else 1) 