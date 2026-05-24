import requests
import csv
import logging
import os
from datetime import datetime
import re
import time
import json
from typing import Dict, List, Set, Optional
from html import unescape
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ========== STATE MANAGEMENT FOR 24-HOUR SCHEDULE ==========
STATE_FILE = os.path.join("job_outputs", "last_run_state.json")

def get_last_successful_run() -> Optional[datetime]:
    """Read the timestamp of the last successful run from state file"""
    if not os.path.exists(STATE_FILE):
        return None
    
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            timestamp_str = data.get('last_successful_run')
            if timestamp_str:
                return datetime.fromisoformat(timestamp_str)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logging.warning(f"Could not read state file: {e}")
    
    return None

def should_run_now() -> bool:
    """
    Check if 24+ hours have passed since last successful run.
    Returns True if:
    - Never run before (no state file)
    - 24+ hours have passed
    - State file is corrupted (runs anyway as safe fallback)
    """
    last_run = get_last_successful_run()
    
    if last_run is None:
        print("\n[STATE] First run detected. Executing now.")
        return True
    
    hours_since = (datetime.now() - last_run).total_seconds() / 3600
    
    if hours_since >= 24:
        print(f"\n[STATE] {hours_since:.1f} hours since last run. Executing now.")
        return True
    else:
        print(f"\n[STATE] Only {hours_since:.1f} hours since last run. Need 24 hours. Skipping.")
        return False

def record_successful_run():
    """Record the current timestamp as a successful run"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    state = {
        'last_successful_run': datetime.now().isoformat(),
        'last_run_timestamp': time.time()
    }
    
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
        logging.info(f"[STATE] Recorded successful run at {state['last_successful_run']}")
    except Exception as e:
        logging.error(f"[STATE] Failed to save state file: {e}")

# ========== CONFIGURATION ==========
API_URL = "https://api.reliefweb.int/v2/jobs"
APP_NAME = "oakjobseqAbdD2n0nX2eqZkOeu06"
JOBS_PER_PAGE = 100  # Reduced for better reliability
OUTPUT_DIR = "job_outputs"
LOG_FILE = "job_scraper.log"

# Set to True to fetch ALL Nigeria jobs (up to API totalCount)
# Set to False to stop after finding X jobs
FETCH_ALL_NIGERIA_JOBS = True
MAX_NIGERIA_JOBS_TO_FETCH = 1000  # Only used if FETCH_ALL_NIGERIA_JOBS is False

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
REQUEST_TIMEOUT = 45  # seconds

# ========== KNOWN NIGERIAN CITIES FOR VALIDATION ==========
NIGERIAN_CITIES = {
    'abuja', 'lagos', 'kano', 'ibadan', 'port harcourt', 'benin city',
    'maiduguri', 'zaria', 'aba', 'jos', 'ilorin', 'sokoto', 'enugu',
    'kaduna', 'akure', 'bauchi', 'gombe', 'makurdi', 'minna', 'yola',
    'owerri', 'umudike', 'nsukka', 'calabar', 'uffia', 'katsina',
    'damaturu', 'birnin kebbi', 'jalingo', 'lokoja', 'osogbo',
    'birnin kudu', 'gumel', 'hadejia', 'azare', 'potiskum', 'mubi',
    'gashua', 'bama', 'dikwa', 'gwoza', 'monguno', 'ngala', 'badegga',
    'nguru', 'kukawa', 'marte', 'gubio', 'magumeri', 'konduga',
    'jere', 'mbuliri', 'gamboru', 'fotokol', 'banki', 'pulka'
}

# Nigerian states (for extraction, then map to capital cities)
STATE_CAPITALS = {
    'borno': 'Maiduguri',
    'adamawa': 'Yola',
    'yobe': 'Damaturu',
    'gombe': 'Gombe',
    'bauchi': 'Bauchi',
    'taraba': 'Jalingo',
    'plateau': 'Jos',
    'nassarawa': 'Lafia',
    'niger': 'Minna',
    'kaduna': 'Kaduna',
    'katsina': 'Katsina',
    'kano': 'Kano',
    'jigawa': 'Dutse',
    'zamfara': 'Gusau',
    'sokoto': 'Sokoto',
    'kebbi': 'Birnin Kebbi',
    'kwara': 'Ilorin',
    'oyo': 'Ibadan',
    'ogun': 'Abeokuta',
    'osun': 'Osogbo',
    'ondo': 'Akure',
    'ekiti': 'Ado Ekiti',
    'lagos': 'Lagos',
    'delta': 'Asaba',
    'edo': 'Benin City',
    'anambra': 'Awka',
    'enugu': 'Enugu',
    'ebonyi': 'Abakaliki',
    'imo': 'Owerri',
    'abia': 'Umuahia',
    'rivers': 'Port Harcourt',
    'bayelsa': 'Yenagoa',
    'cross river': 'Calabar',
    'akwa ibom': 'Uyo',
    'benue': 'Makurdi',
    'kogi': 'Lokoja',
    'fct': 'Abuja',
    'federal capital territory': 'Abuja'
}

# ========== SETUP LOGGING ==========
def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

def create_session_with_retries() -> requests.Session:
    """Create a session with retry strategy"""
    session = requests.Session()
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=RETRY_DELAY,
        status_forcelist=[408, 429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

# ========== DUPLICATE TRACKING ==========
def load_processed_jobs() -> Set[str]:
    processed_ids = set()
    
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        return processed_ids
    
    for filename in os.listdir(OUTPUT_DIR):
        if filename.endswith('.csv') and not filename.startswith('_'):
            filepath = os.path.join(OUTPUT_DIR, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if 'job_id' in row and row['job_id']:
                            processed_ids.add(row['job_id'])
            except Exception as e:
                logger.warning(f"Could not read {filename}: {e}")
    
    logger.info(f"Loaded {len(processed_ids)} previously processed job IDs")
    return processed_ids

def save_processed_job_ids(job_ids: Set[str], output_file: str):
    tracking_file = os.path.join(OUTPUT_DIR, "_processed_ids.txt")
    with open(tracking_file, 'a', encoding='utf-8') as f:
        for job_id in job_ids:
            f.write(f"{job_id}\n")

# ========== SAVE RAW JSON RESPONSE ==========
def save_raw_json_response(data: Dict, prefix: str = "raw_api_response"):
    """Save the raw JSON response to a timestamped file"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{timestamp}.json"
    filepath = os.path.join(OUTPUT_DIR, filename)
    
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Raw JSON response saved to {filepath}")
        return filepath
    except Exception as e:
        logger.error(f"Failed to save raw JSON response: {e}")
        return None

# ========== HTML CONTENT PROCESSING ==========
def clean_html_content(html_content: str) -> str:
    if not html_content:
        return ""
    
    content = unescape(html_content)
    
    for i in range(1, 7):
        content = re.sub(rf'<h{i}[^>]*>(.*?)</h{i}>', r'\n\n**\1**\n', content, flags=re.IGNORECASE | re.DOTALL)
    
    content = re.sub(r'<p[^>]*>(.*?)</p>', r'\n\n\1\n\n', content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r'<ul[^>]*>(.*?)</ul>', r'\n\1\n', content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r'<li[^>]*>(.*?)</li>', r'  • \1\n', content, flags=re.IGNORECASE | re.DOTALL)
    
    def process_ol(match):
        items = re.findall(r'<li[^>]*>(.*?)</li>', match.group(1), flags=re.IGNORECASE | re.DOTALL)
        numbered = '\n'.join([f'  {i+1}. {item.strip()}' for i, item in enumerate(items)])
        return f'\n{numbered}\n'
    
    content = re.sub(r'<ol[^>]*>(.*?)</ol>', process_ol, content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r'<b[^>]*>(.*?)</b>', r'**\1**', content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r'<em[^>]*>(.*?)</em>', r'*\1*', content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r'<i[^>]*>(.*?)</i>', r'*\1*', content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r'<br\s*/?>', '\n', content, flags=re.IGNORECASE)
    content = re.sub(r'<[^>]+>', '', content)
    content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)
    content = re.sub(r' +\n', '\n', content)
    
    return content.strip()

def preserve_html_style(job_body: str, use_html: bool = True) -> str:
    if not job_body:
        return ""
    
    if '<' in job_body and '>' in job_body:
        return clean_html_content(job_body)
    
    lines = job_body.split('\n')
    formatted_lines = []
    in_list = False
    
    for line in lines:
        line = line.strip()
        if not line:
            formatted_lines.append('')
            in_list = False
        elif line.startswith('- ') or line.startswith('• ') or line.startswith('* '):
            if not in_list:
                in_list = True
            formatted_lines.append(f'  • {line[2:]}')
        elif re.match(r'^\d+\.', line):
            formatted_lines.append(f'  {line}')
        elif line.isupper() and len(line) > 5 and not line.endswith('.'):
            formatted_lines.append(f'\n**{line}**\n')
        else:
            formatted_lines.append(line)
    
    return '\n'.join(formatted_lines)

# ========== CLEAN URL FUNCTION ==========
def clean_url(url: str) -> str:
    """Remove markdown artifacts, trailing parentheses, and extra text from URLs"""
    if not url:
        return ""
    
    # Remove markdown link syntax
    url = re.sub(r'\]\(.*?\)', '', url)
    url = re.sub(r'\[.*?\]', '', url)
    
    # Remove trailing characters
    url = re.sub(r'[\)\]\*]+$', '', url)
    url = re.sub(r'\s*by\s*$', '', url, flags=re.IGNORECASE)
    url = re.sub(r'\s*apply here\s*$', '', url, flags=re.IGNORECASE)
    
    # Extract first valid URL if multiple
    match = re.search(r'https?://[^\s<>"\'\)\]]+', url)
    if match:
        url = match.group(0)
    
    return url.strip()

# ========== EXTRACT JOB LOCATION ==========
def extract_job_location(fields: Dict) -> str:
    """
    Extract ONLY the city name from job data.
    Returns empty string if no valid city found.
    """
    body_text = fields.get('body', '')
    body_html = fields.get('body-html', '')
    body_search = f"{body_text} {body_html}"
    
    # Clean up the search text first
    body_search = re.sub(r'\*+', '', body_search)
    body_search = re.sub(r'<[^>]+>', ' ', body_search)
    
    # PRIORITY 1: Check API city field
    if fields.get('city') and fields['city'][0].get('name'):
        city_candidate = fields['city'][0]['name'].strip().lower()
        if city_candidate in NIGERIAN_CITIES:
            return city_candidate.title()
        # Check if it's a state name that maps to a capital
        if city_candidate in STATE_CAPITALS:
            return STATE_CAPITALS[city_candidate]
    
    # PRIORITY 2: Extract from Duty station field
    duty_patterns = [
        r'Duty station:\s*([A-Za-z\s]+?)(?:\n|\.|\,|$|with)',
        r'<strong>Duty station:</strong>\s*([A-Za-z\s]+?)(?:<|$)',
        r'\*\*Duty station:\*\*\s*([A-Za-z\s]+?)(?:\n|\.|\,|$)',
        r'Based in\s*([A-Za-z\s]+?)(?:\n|\.|\,|$)',
    ]
    
    for pattern in duty_patterns:
        match = re.search(pattern, body_search, re.IGNORECASE)
        if match:
            city_candidate = match.group(1).strip().lower()
            # Get first word (usually the city)
            city_candidate = city_candidate.split()[0]
            if city_candidate in NIGERIAN_CITIES:
                return city_candidate.title()
            if city_candidate in STATE_CAPITALS:
                return STATE_CAPITALS[city_candidate]
    
    # PRIORITY 3: Extract from Job Location field
    location_patterns = [
        r'Job Location:\s*([A-Za-z\s]+?)(?:\n|\.|\,|$)',
        r'Location:\s*([A-Za-z\s]+?)(?:\n|\.|\,|$)',
    ]
    
    for pattern in location_patterns:
        match = re.search(pattern, body_search, re.IGNORECASE)
        if match:
            city_candidate = match.group(1).strip().lower()
            city_candidate = city_candidate.split()[0]
            if city_candidate in NIGERIAN_CITIES:
                return city_candidate.title()
            if city_candidate in STATE_CAPITALS:
                return STATE_CAPITALS[city_candidate]
    
    # PRIORITY 4: Search body for known city names
    for city in NIGERIAN_CITIES:
        if re.search(rf'\b{re.escape(city)}\b', body_search, re.IGNORECASE):
            return city.title()
    
    # PRIORITY 5: Check for state names (map to capital)
    for state, capital in STATE_CAPITALS.items():
        if re.search(rf'\b{re.escape(state)}\b', body_search, re.IGNORECASE):
            return capital
    
    # No valid city found
    return ""

# ========== CLEAN POST TITLE ==========
def clean_post_title(original_title: str, company_name: str) -> str:
    """Create clean post title in format: 'Original Title at Company'"""
    if not company_name:
        return f"[NO COMPANY] {original_title}"
    
    # Remove common company suffixes from title to avoid duplication
    patterns_to_remove = [
        rf'\s*[-–]\s*{re.escape(company_name)}.*$',
        rf'\s*[-–]\s*Nigeria.*$',
        rf'\s*\(.*{re.escape(company_name)}.*\)$',
        rf'\s*at\s+{re.escape(company_name)}$',
    ]
    
    clean_title = original_title
    for pattern in patterns_to_remove:
        clean_title = re.sub(pattern, '', clean_title, flags=re.IGNORECASE)
    
    clean_title = clean_title.strip()
    
    # Add the company name
    return f"{clean_title} at {company_name}"

# ========== DATA EXTRACTION ==========
def extract_job_data(job: Dict) -> Dict:
    fields = job.get('fields', {})
    
    # Get formatted content
    body_html = fields.get('body-html', '')
    body_text = fields.get('body', '')
    
    if body_html:
        post_content = preserve_html_style(body_html, use_html=True)
    else:
        post_content = preserve_html_style(body_text, use_html=False)
    
    # Extract application URL and clean it
    how_to_apply = fields.get('how_to_apply', '')
    url_match = re.search(r'https?://[^\s]+', how_to_apply)
    application_url = clean_url(url_match.group(0)) if url_match else None
    
    if not application_url:
        how_to_apply_html = fields.get('how_to_apply-html', '')
        url_match = re.search(r'https?://[^\s]+', how_to_apply_html)
        application_url = clean_url(url_match.group(0)) if url_match else None
    
    # Extract company name
    company_name = fields.get('source', [{}])[0].get('name', '')
    
    # Extract job location
    job_location = extract_job_location(fields)
    
    # Get original title and create cleaned post_title with company name
    original_title = fields.get('title', '')
    post_title = clean_post_title(original_title, company_name)
    
    # Get career category
    career_categories = fields.get('career_categories', [])
    job_category = ', '.join([cat.get('name', '') for cat in career_categories]) if career_categories else ''
    
    return {
        'job_id': str(job.get('id', '')),
        'post_title': post_title,
        'company': company_name,
        'job_location': job_location,
        'job_type': fields.get('type', [{}])[0].get('name', ''),
        'job_category': job_category,
        'experience_level': fields.get('experience', [{}])[0].get('name', '') if fields.get('experience') else '',
        'post_category': fields.get('type', [{}])[0].get('name', ''),
        'job_expires': fields.get('date', {}).get('closing', ''),
        'date_created': fields.get('date', {}).get('created', ''),
        'application_url': application_url if application_url else '',
        'url': fields.get('url', ''),
        'post_content': post_content,
        'has_valid_location': bool(job_location)
    }

# ========== API REQUEST WITH RETRY ==========
def make_api_request(session: requests.Session, params: Dict, page_num: int) -> Optional[Dict]:
    """Make API request with retry logic"""
    for attempt in range(MAX_RETRIES + 1):
        try:
            logger.info(f"Fetching page {page_num} (attempt {attempt + 1}/{MAX_RETRIES + 1})...")
            response = session.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout on page {page_num}, attempt {attempt + 1}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * (attempt + 1))
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Connection error on page {page_num}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * (attempt + 1))
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed on page {page_num}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Status code: {e.response.status_code}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                return None
    
    return None

# ========== API REQUEST - FETCH ALL NIGERIA JOBS ==========
def fetch_all_nigeria_jobs(logger) -> List[Dict]:
    """
    Fetch ALL jobs from API (up to totalCount) and filter for Nigeria.
    Uses pagination to get every job available.
    """
    session = create_session_with_retries()
    all_nigeria_jobs = []
    all_raw_responses = []  # Store raw responses for saving
    all_jobs_seen = 0
    total_available = None
    offset = 0
    page = 1
    
    logger.info("="*60)
    logger.info("FETCHING ALL NIGERIA JOBS FROM API")
    logger.info(f"Using {JOBS_PER_PAGE} jobs per page")
    if FETCH_ALL_NIGERIA_JOBS:
        logger.info("Mode: Fetch ALL Nigeria jobs available")
    else:
        logger.info(f"Mode: Fetch up to {MAX_NIGERIA_JOBS_TO_FETCH} Nigeria jobs")
    logger.info("="*60)
    
    while True:
        params = {
            'appname': APP_NAME,
            'profile': 'full',
            'limit': JOBS_PER_PAGE,
            'offset': offset,
            'sort': 'date.created:desc'  # Newest first
        }
        
        # Make request with retry
        data = make_api_request(session, params, page)
        
        if not data:
            logger.error(f"Failed to fetch page {page} after {MAX_RETRIES} attempts")
            break
        
        # Store raw response for this page
        all_raw_responses.append(data)
        
        # Get total count on first request
        if total_available is None:
            total_available = data.get('totalCount', 0)
            logger.info(f"Total jobs available in API: {total_available:,}")
            
            # If total is 0, break early
            if total_available == 0:
                logger.warning("No jobs found in API")
                break
        
        jobs = data.get('data', [])
        if not jobs:
            logger.info("No more jobs returned. Stopping.")
            break
        
        all_jobs_seen += len(jobs)
        
        # Filter this page for Nigeria
        nigeria_in_page = 0
        for job in jobs:
            countries = job.get('fields', {}).get('country', [])
            for country in countries:
                if country.get('iso3', '').lower() == 'nga':
                    all_nigeria_jobs.append(job)
                    nigeria_in_page += 1
                    break
        
        logger.info(f"  → Page {page}: {nigeria_in_page} Nigeria jobs (Total Nigeria so far: {len(all_nigeria_jobs)})")
        
        # Check if we've reached our target (if not fetching all)
        if not FETCH_ALL_NIGERIA_JOBS and len(all_nigeria_jobs) >= MAX_NIGERIA_JOBS_TO_FETCH:
            logger.info(f"Reached target of {MAX_NIGERIA_JOBS_TO_FETCH} Nigeria jobs. Stopping.")
            all_nigeria_jobs = all_nigeria_jobs[:MAX_NIGERIA_JOBS_TO_FETCH]
            break
        
        # Check if we've fetched all available jobs
        if len(jobs) < JOBS_PER_PAGE or all_jobs_seen >= total_available:
            logger.info(f"Fetched all {all_jobs_seen} jobs available in API.")
            break
        
        offset += JOBS_PER_PAGE
        page += 1
        
        # Be nice to the API - delay between requests
        time.sleep(1)
    
    session.close()
    
    # Save all raw JSON responses to a single combined file
    if all_raw_responses:
        combined_raw_data = {
            "fetch_timestamp": datetime.now().isoformat(),
            "total_pages": len(all_raw_responses),
            "total_nigeria_jobs_found": len(all_nigeria_jobs),
            "pages": all_raw_responses
        }
        save_raw_json_response(combined_raw_data, "raw_api_responses_combined")
    
    logger.info(f"\n✓ COMPLETE: Found {len(all_nigeria_jobs)} Nigeria jobs out of {all_jobs_seen} total jobs searched")
    return all_nigeria_jobs

# ========== ALTERNATIVE: TEST CONNECTION FIRST ==========
def test_api_connection(logger) -> bool:
    """Test if the API is accessible"""
    session = create_session_with_retries()
    
    try:
        params = {
            'appname': APP_NAME,
            'limit': 1
        }
        response = session.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        total = data.get('totalCount', 0)
        logger.info(f"✓ API connection successful! Total jobs available: {total:,}")
        session.close()
        return True
    except Exception as e:
        logger.error(f"✗ API connection failed: {e}")
        session.close()
        return False

# ========== CSV OUTPUT ==========
def save_to_csv(jobs: List[Dict], processed_ids: Set[str], logger) -> str:
    # Filter out duplicates AND jobs without valid job location
    new_jobs = []
    new_ids = set()
    skipped_no_location = []
    
    for job in jobs:
        job_id = job.get('job_id')
        if job_id and job_id not in processed_ids:
            if job.get('has_valid_location'):
                # Remove the temporary field before saving
                job_copy = job.copy()
                job_copy.pop('has_valid_location', None)
                new_jobs.append(job_copy)
                new_ids.add(job_id)
            else:
                skipped_no_location.append(job)
    
    if skipped_no_location:
        logger.info(f"Skipped {len(skipped_no_location)} jobs without valid job location")
    
    if not new_jobs:
        logger.info("No new jobs with valid locations found.")
        # Still save skipped jobs for review if any
        if skipped_no_location:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            skipped_filename = f"nigeria_jobs_review_needed_{timestamp}.csv"
            skipped_filepath = os.path.join(OUTPUT_DIR, skipped_filename)
            with open(skipped_filepath, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=['job_id', 'company', 'url', 'date_created'])
                writer.writeheader()
                for job in skipped_no_location:
                    writer.writerow({
                        'job_id': job['job_id'],
                        'company': job['company'],
                        'url': job['url'],
                        'date_created': job.get('date_created', '')
                    })
            logger.info(f"Saved {len(skipped_no_location)} jobs needing review to {skipped_filepath}")
        return None
    
    logger.info(f"Found {len(new_jobs)} new jobs with valid locations")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"nigeria_jobs_{timestamp}.csv"
    filepath = os.path.join(OUTPUT_DIR, filename)
    
    # Save skipped jobs separately for manual review
    if skipped_no_location:
        skipped_filename = f"nigeria_jobs_review_needed_{timestamp}.csv"
        skipped_filepath = os.path.join(OUTPUT_DIR, skipped_filename)
        with open(skipped_filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=['job_id', 'company', 'url', 'date_created'])
            writer.writeheader()
            for job in skipped_no_location:
                writer.writerow({
                    'job_id': job['job_id'],
                    'company': job['company'],
                    'url': job['url'],
                    'date_created': job.get('date_created', '')
                })
        logger.info(f"Saved {len(skipped_no_location)} jobs needing review to {skipped_filepath}")
    
    # Updated fieldnames without original_title and source_shortname, with job_location instead of city_location
    fieldnames = [
        'job_id',
        'post_title',
        'company',
        'job_location',
        'job_type',
        'job_category',
        'experience_level',
        'post_category',
        'job_expires',
        'date_created',
        'application_url',
        'url',
        'post_content'
    ]
    
    with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(
            csvfile, 
            fieldnames=fieldnames,
            quoting=csv.QUOTE_ALL,
            escapechar='\\'
        )
        writer.writeheader()
        
        for job in new_jobs:
            writer.writerow(job)
    
    logger.info(f"Saved {len(new_jobs)} jobs to {filepath}")
    save_processed_job_ids(new_ids, filepath)
    
    return filepath

# ========== SUMMARY REPORT ==========
def print_summary(jobs: List[Dict], processed_ids: Set[str], saved_file: str, logger):
    if not jobs:
        print("\n" + "="*60)
        print("NO NIGERIA JOBS FOUND")
        print("="*60)
        print("No jobs from Nigeria were found in the API.")
        print("Try increasing MAX_PAGES or using the direct method.")
        return
    
    new_jobs = [j for j in jobs if j.get('job_id') not in processed_ids]
    new_with_location = [j for j in new_jobs if j.get('has_valid_location')]
    new_without_location = [j for j in new_jobs if not j.get('has_valid_location')]
    
    print("\n" + "="*60)
    print("JOB SCRAPING SUMMARY")
    print("="*60)
    print(f"Total Nigeria jobs fetched:   {len(jobs)}")
    print(f"Previously processed:         {len([j for j in jobs if j.get('job_id') in processed_ids])}")
    print(f"New jobs found:               {len(new_jobs)}")
    print(f"  ✅ With valid location:          {len(new_with_location)}")
    print(f"  ❌ Needs review:             {len(new_without_location)}")
    print(f"Output file:                  {saved_file if saved_file else 'None (see review file)'}")
    print(f"Filter:                       Nigeria only (client-side)")
    print(f"Sort:                         Most recent first (date.created:desc)")
    print(f"Date filter:                  NONE (all Nigeria jobs)")
    print("="*60)
    
    if new_with_location:
        print("\n📍 Jobs by Location:")
        location_counts = {}
        for job in new_with_location:
            location = job.get('job_location', 'Unknown')
            location_counts[location] = location_counts.get(location, 0) + 1
        for location, count in sorted(location_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  - {location}: {count}")
    
    if new_without_location:
        print(f"\n⚠️ {len(new_without_location)} jobs need manual location review")
        print("   Check the 'nigeria_jobs_review_needed_*.csv' file")
    
    # Show date range of fetched jobs
    if jobs:
        dates = [j.get('date_created', '') for j in jobs if j.get('date_created')]
        if dates:
            print(f"\n📅 Date range of Nigeria jobs found:")
            print(f"   Oldest: {min(dates)}")
            print(f"   Newest: {max(dates)}")
    
    print("")

# ========== MAIN FUNCTION ==========
def main():
    global logger
    logger = setup_logging()
    
    # ========== 24-HOUR SCHEDULE CHECK ==========
    # Exit early if not enough time has passed since last successful run
    if not should_run_now():
        logger.info("Skipping execution: 24 hours not yet elapsed since last successful run")
        print("\n⏭️  Script exiting. Will run again on next trigger.")
        return
    
    logger.info("="*60)
    logger.info("STARTING NIGERIA JOBS SCRAPER (WITH PAGINATION)")
    logger.info("Configuration:")
    logger.info(f"  - Country: Nigeria only (client-side filtering)")
    logger.info(f"  - Date filter: NONE (all jobs)")
    logger.info(f"  - Sort: Most recent first (date.created:desc)")
    logger.info(f"  - Jobs per page: {JOBS_PER_PAGE}")
    logger.info(f"  - Mode: {'Fetch ALL Nigeria jobs' if FETCH_ALL_NIGERIA_JOBS else f'Fetch up to {MAX_NIGERIA_JOBS_TO_FETCH} Nigeria jobs'}")
    logger.info(f"  - Location extraction: City-only mode")
    logger.info(f"  - Max retries: {MAX_RETRIES}")
    logger.info(f"  - Request timeout: {REQUEST_TIMEOUT}s")
    logger.info("="*60)
    
    # Test API connection first
    if not test_api_connection(logger):
        logger.error("Cannot connect to API. Please check your internet connection and try again.")
        print("\n⚠️  API connection failed. Please check:")
        print("   1. Your internet connection")
        print("   2. If the ReliefWeb API is accessible (https://api.reliefweb.int)")
        print("   3. If you need to use a VPN/proxy")
        return
    
    # Load previously processed job IDs
    processed_ids = load_processed_jobs()
    
    # Fetch ALL Nigeria jobs using pagination (recommended method)
    nigeria_jobs = fetch_all_nigeria_jobs(logger)
    
    if not nigeria_jobs:
        logger.warning("No Nigeria jobs found in the API")
        print("\n" + "="*60)
        print("NO NIGERIA JOBS FOUND")
        print("="*60)
        print("No jobs from Nigeria were found in the API.")
        print("This could mean there are currently no Nigeria jobs posted.")
        return
    
    # Extract job data
    extracted_jobs = [extract_job_data(job) for job in nigeria_jobs]
    
    # Save to CSV
    saved_file = save_to_csv(extracted_jobs, processed_ids, logger)
    
    # Print summary
    print_summary(extracted_jobs, processed_ids, saved_file, logger)
    
    # ========== RECORD SUCCESSFUL RUN ==========
    # Only record success if we actually saved new jobs OR we successfully completed the fetch
    # Even if no new jobs were found, the script ran successfully
    if saved_file is not None or True:  # Script completed without fatal error
        record_successful_run()
        logger.info("Job scraper completed successfully - 24-hour timer reset")
    else:
        logger.warning("Job scraper completed but no CSV was saved - 24-hour timer NOT reset")
    
    logger.info("Job scraper completed successfully")

if __name__ == "__main__":
    main()