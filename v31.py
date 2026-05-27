from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import pandas as pd
import os
from datetime import datetime
import time
import sys
import random
import re
import uuid
import logging
import json
from pathlib import Path

# Configure logging - More verbose for terminal
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
CONFIG = {
    'user_agents': [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ],
    'retry_attempts': 3,
    'retry_delay': 2,
    'timeout': 40,
    'headless': True,
    'debug': False,
    'history_file': 'scraped_jobs_history.json'
}

# SIMPLIFIED SELECTORS - More robust
SELECTORS = {
    'job_title': [
        "h1",
        "h1.ip-typography",
        ".job-title",
        "title",
        "h1[class*='title']",
        "h1[class*='heading']"
    ],
    'company_name': [
        ".company-name",
        ".organization",
        "span.ip-typography[type='bodyEmphasis']:first-child",
        "h2",
        ".employer"
    ],
    'company_logo': [
        ".company-logo img",
        ".organization-logo img",
        ".employer-logo img",
        "img[alt*='logo']",
        "img[src*='logo']",
        "img[src*='organization']",
        "img[src*='company']",
        ".company_logo img",
        "img:not([src*='impactpool-logo'])"
    ],
    'location': [
        ".ip-layout span.ip-typography[type='body']",
        ".job-metadata span",
        ".location",
        "[class*='location']",
        ".ip-typography:contains('Location')"
    ],
    'job_type': [
        "span:contains('National')",
        "span:contains('International')",
        "span:contains('Consultant')",
        "span:contains('Full-time')",
        ".job-type",
        "[class*='type']"
    ],
    'deadline': [
        ".ip-typography[style*='color: #675402']",
        ".ip-typography[style*='color: #538F3E']",
        ".ip-badge.badge-type-warning",
        "span:contains('Application deadline')",
        "span:contains('Deadline')",
        "span:contains('Closing')",
        ".deadline",
        "[class*='deadline']"
    ],
    'apply_button': [
        "a.ip-cta[cta-type='splash']",
        "a:contains('Apply')",
        "button:contains('Apply')",
        ".apply-button",
        "[class*='apply']"
    ],
    'main_content': [
        ".main-content",
        "#job-description",
        ".job-description",
        ".description",
        "article"
    ],
    'summary': [
        ".summary .ip-typography[type='bodyEmphasis']:contains('Summary') + .ip-typography[type='body']",
        ".summary p",
        ".about-role",
        ".job-summary",
        ".overview"
    ],
    'requirements_headings': [
        ".summary .ip-typography[type='bodyEmphasis']:contains('Candidate Requirements')",
        "h2:contains('Requirements')",
        "h2:contains('Qualifications')",
        "h2:contains('Profile')",
        "h2:contains('Candidate Requirements')",
        "h2:contains('Required Qualifications')",
        "strong:contains('Minimum requirements')",
        "strong:contains('To qualify')",
        "h3:contains('Requirements')"
    ],
    'lists': [
        ".summary ul",
        "ul",
        "ol"
    ],
    'description_sections': [
        ".main-content",
        "div[class*='description']",
        "div[class*='content']",
        ".job-body"
    ],
    'sidebar': [
        ".sidebar",
        ".sidebar .card"
    ],
    'job_footer': [
        "#job-description-footer",
        ".job-snapshot"
    ]
}

class ScrapedJobsHistory:
    def __init__(self, history_file='scraped_jobs_history.json'):
        self.history_file = history_file
        self.scraped_jobs = self.load_history()
    
    def load_history(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def save_history(self):
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(self.scraped_jobs, f, indent=2, ensure_ascii=False)
    
    def is_job_scraped(self, job_url, job_title):
        if job_url in self.scraped_jobs:
            return True
        today = datetime.now().strftime('%Y-%m-%d')
        for url, data in self.scraped_jobs.items():
            if data.get('title') == job_title and data.get('date') == today:
                return True
        return False
    
    def add_job(self, job_url, job_title, job_data):
        self.scraped_jobs[job_url] = {
            'title': job_title,
            'url': job_url,
            'date': datetime.now().strftime('%Y-%m-%d'),
            'timestamp': datetime.now().isoformat(),
            'scraped_data': {
                'company': job_data.get('company', ''),
                'location': job_data.get('job_location', ''),
                'category': job_data.get('job_category', '')
            }
        }
        self.save_history()
    
    def get_today_scraped_count(self):
        today = datetime.now().strftime('%Y-%m-%d')
        count = 0
        for url, data in self.scraped_jobs.items():
            if data.get('date') == today:
                count += 1
        return count
    
    def get_history_summary(self):
        summary = {
            'total_scraped': len(self.scraped_jobs),
            'today_scraped': self.get_today_scraped_count(),
            'last_scraped': max([data.get('timestamp', '') for data in self.scraped_jobs.values()]) if self.scraped_jobs else None
        }
        return summary

class ImpactpoolScraper:
    def __init__(self, headless=True):
        self.driver = None
        self.headless = headless
        self.history = ScrapedJobsHistory()
        self.setup_driver()
    
    def setup_driver(self):
        try:
            options = Options()
            options.add_argument('--headless=new')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--disable-extensions')
            options.add_argument('--disable-setuid-sandbox')
            options.add_argument('--disable-web-security')
            options.add_argument('--disable-features=VizDisplayCompositor')
            options.add_argument(f'user-agent={random.choice(CONFIG["user_agents"])}')
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            
            try:
                from webdriver_manager.chrome import ChromeDriverManager
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=options)
            except:
                service = Service()
                self.driver = webdriver.Chrome(service=service, options=options)
            
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            self.driver.set_page_load_timeout(30)
            logger.info("WebDriver setup successful")
        except Exception as e:
            logger.error(f"Failed to setup WebDriver: {e}")
            raise
    
    def wait_for_element(self, selector, by=By.CSS_SELECTOR, timeout=30):
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, selector))
            )
            return element
        except:
            return None
    
    def find_element_with_selectors(self, selectors_list, timeout=10):
        for selector in selectors_list:
            try:
                element = self.wait_for_element(selector, timeout=timeout)
                if element and element.is_displayed():
                    return element
            except:
                continue
        return None
    
    def find_elements_with_selectors(self, selectors_list, timeout=5):
        for selector in selectors_list:
            try:
                elements = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, selector))
                )
                if elements:
                    return elements
            except:
                continue
        return []
    
    def get_text(self, element):
        if not element:
            return ""
        try:
            return element.text.strip()
        except:
            return ""
    
    def get_attribute(self, element, attr):
        if not element:
            return ""
        try:
            return element.get_attribute(attr)
        except:
            return ""
    
    def clean_text(self, text):
        if not text:
            return ""
        text = ' '.join(text.split())
        disclaimer_patterns = [
            r'At Impactpool we do our best.*',
            r'Please check on the recruiting organization.*',
            r'Candidates are responsible for complying.*',
            r'Before applying, please make sure.*',
            r'Applications from non-qualifying applicants.*',
            r'Only shortlisted candidates.*',
        ]
        for pattern in disclaimer_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        return ' '.join(text.split()).strip()
    
    def remove_summary_prefix(self, text):
        if not text:
            return ""
        text = re.sub(r'^Summary by Impactpool\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^"Summary by Impactpool"\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^Summary by Impactpool:\s*', '', text, flags=re.IGNORECASE)
        return text.strip()
    
    def is_valid_job(self):
        try:
            title_element = self.find_element_with_selectors(SELECTORS['job_title'])
            if not title_element:
                page_title = self.driver.title
                if not page_title or len(page_title) < 5:
                    return False
            else:
                title = self.get_text(title_element)
                if not title or len(title) < 3:
                    return False
            
            page_source = self.driver.page_source.lower()
            non_job_indicators = ['fellowship program', 'scholarship opportunity', 'grant opportunity', 'event registration', 'webinar']
            for indicator in non_job_indicators:
                if indicator in page_source[:3000]:
                    return False
            return True
        except:
            return True
    
    def extract_job_title(self):
        title_element = self.find_element_with_selectors(SELECTORS['job_title'])
        if title_element:
            title = self.get_text(title_element)
            if title and len(title) > 5:
                return self.clean_text(title)
        
        h1_elements = self.driver.find_elements(By.TAG_NAME, "h1")
        for h1 in h1_elements:
            text = self.get_text(h1)
            if text and len(text) > 10 and len(text) < 200:
                return self.clean_text(text)
        
        page_title = self.driver.title
        if page_title and 'Impactpool' not in page_title:
            title = page_title.split('|')[0].strip()
            if title and len(title) > 5:
                return self.clean_text(title)
        return ""
    
    def extract_company_info(self):
        company_info = {'name': '', 'logo': ''}
        company_element = self.find_element_with_selectors(SELECTORS['company_name'])
        if company_element:
            name = self.get_text(company_element)
            if name and len(name) > 2:
                company_info['name'] = self.clean_text(name)
        
        all_images = self.driver.find_elements(By.TAG_NAME, "img")
        for img in all_images:
            try:
                src = img.get_attribute('src') or ""
                alt = img.get_attribute('alt') or ""
                class_name = img.get_attribute('class') or ""
                if 'impactpool-logo' in src or 'impactpool-logo' in alt or 'impactpool' in class_name.lower():
                    continue
                if (('logo' in src.lower() or 'logo' in alt.lower() or 'logo' in class_name.lower()) and len(src) > 20):
                    if img.is_displayed():
                        if src.startswith('//'):
                            src = f"https:{src}"
                        elif src.startswith('/'):
                            src = f"https://www.impactpool.org{src}"
                        company_info['logo'] = src
                        return company_info
            except:
                continue
        
        if not company_info['logo']:
            logo_element = self.find_element_with_selectors(SELECTORS['company_logo'])
            if logo_element:
                src = self.get_attribute(logo_element, 'src')
                if src and 'impactpool-logo' not in src:
                    if src.startswith('//'):
                        src = f"https:{src}"
                    elif src.startswith('/'):
                        src = f"https://www.impactpool.org{src}"
                    company_info['logo'] = src
        return company_info
    
    def extract_single_location(self, location_text):
        """
        Extract only ONE primary location from location text.
        Removes 'Remote |', 'Remote /', '|', '/', 'and', '&' and takes the first valid location.
        """
        if not location_text:
            return ""
        
        # Clean the text
        location_text = location_text.strip()
        
        # Remove common prefixes like "Location:"
        location_text = re.sub(r'^Location:\s*', '', location_text, flags=re.IGNORECASE)
        
        # List of separators that indicate multiple locations
        separators = [
            ' | ', '|',           # Pipe separator
            ' / ', '/',           # Slash separator
            ' and ', ' & ',       # And separator
            ' , ', ', ',         # Comma separator (but careful with city, country)
            ' - ', ' -', '- ',    # Dash separator
            ' + ',               # Plus separator
            'Remote |', 'Remote|', 'Remote /', 'Remote/', 'Remote',  # Remote prefixes
            'Virtual |', 'Virtual|', 'Virtual /', 'Virtual/', 'Virtual',
            'Hybrid |', 'Hybrid|', 'Hybrid /', 'Hybrid/',
        ]
        
        # Check for and remove "Remote |" or "Remote /" patterns specifically
        remote_patterns = [
            r'^Remote\s*[|/]\s*',      # "Remote | " or "Remote / "
            r'^Remote\s+',              # "Remote "
            r'\s+[|/]\s+',              # " | " or " / "
        ]
        
        for pattern in remote_patterns:
            location_text = re.sub(pattern, '', location_text, flags=re.IGNORECASE)
        
        # Split by common separators and take the first part
        for sep in separators:
            if sep in location_text:
                parts = location_text.split(sep)
                # Find the first part that looks like a valid location (not empty and not too short)
                for part in parts:
                    part = part.strip()
                    if part and len(part) > 2:
                        # Check if this part looks like a city/place (not a country code or single word)
                        if re.match(r'^[A-Za-z\s\-]+$', part):
                            location_text = part
                            break
                break
        
        # Handle comma-separated locations (e.g., "Abuja, Nigeria" -> "Abuja")
        # But only if the first part looks like a specific city
        if ',' in location_text:
            parts = [p.strip() for p in location_text.split(',')]
            # Common country names to check
            countries = ['Nigeria', 'Ghana', 'Kenya', 'Senegal', 'Mali', 'Niger', 'Chad', 
                        'Cameroon', 'Benin', 'Togo', 'Burkina', 'Ivory Coast', 'Congo',
                        'Ethiopia', 'Uganda', 'Tanzania', 'Rwanda', 'Burundi', 'South Africa']
            
            # If first part is likely a city (short, not a country) and second part is a country
            if len(parts) >= 2:
                first_part = parts[0]
                second_part = parts[1] if len(parts) > 1 else ""
                
                # Check if second part looks like a country
                is_country = False
                for country in countries:
                    if country.lower() in second_part.lower():
                        is_country = True
                        break
                
                # If first part is plausible as a primary location
                if first_part and len(first_part) > 2 and len(first_part) < 40:
                    if is_country or len(parts) == 2:
                        location_text = first_part
        
        # Clean up any remaining artifacts
        location_text = re.sub(r'^\s*[,|/-]+\s*', '', location_text)
        location_text = re.sub(r'\s*[,|/-]+\s*$', '', location_text)
        
        # Remove any remaining special characters
        location_text = re.sub(r'[^\w\s\-]', '', location_text)
        
        # Trim whitespace
        location_text = location_text.strip()
        
        # If we ended up with multiple words that look like a full address, try to take just the city
        if ' ' in location_text and len(location_text.split()) > 2:
            # Look for common city names in Nigeria
            nigerian_cities = ['Abuja', 'Lagos', 'Kano', 'Ibadan', 'Kaduna', 'Port Harcourt', 
                              'Maiduguri', 'Benin City', 'Enugu', 'Jos', 'Sokoto', 'Katsina',
                              'Gombe', 'Yola', 'Damaturu', 'Calabar', 'Oyo', 'Ilorin', 'Abeokuta']
            for city in nigerian_cities:
                if city.lower() in location_text.lower():
                    location_text = city
                    break
        
        # Final validation
        if location_text and len(location_text) > 2 and len(location_text) < 60:
            logger.debug(f"Extracted single location: {location_text}")
            return location_text
        
        return ""
    
    def extract_location(self):
        """Extract ONLY the primary job location - single location only"""
        try:
            # Find all metadata spans
            meta_spans = self.driver.find_elements(By.CSS_SELECTOR, 
                ".ip-layout span.ip-typography[type='body']")
            
            for span in meta_spans:
                text = self.get_text(span)
                if text:
                    # Clean and normalize the text
                    text = text.strip()
                    
                    # Check if this looks like a location (contains city names, countries, or commas)
                    location_keywords = ['Abuja', 'Lagos', 'Kano', 'Kaduna', 'Port Harcourt', 'Ibadan', 
                                        'Maiduguri', 'Sokoto', 'Katsina', 'Gombe', 'Jos', 'Lokoja', 
                                        'Abakaliki', 'Osogbo', 'Yola', 'Damaturu', 'Calabar', 'Enugu', 'Oyo',
                                        'Nairobi', 'Accra', 'Dakar', 'Banjul', 'Bamako', 'Ouagadougou',
                                        'Niamey', "N'Djamena", 'Yaounde', 'Douala', 'Cotonou', 'Lome',
                                        'Nigeria', 'Ghana', 'Kenya', 'Senegal', 'Mali', 'Burkina Faso',
                                        'Niger', 'Chad', 'Cameroon', 'Benin', 'Togo', 'Remote', 'Virtual']
                    
                    # If this text contains location indicators
                    for keyword in location_keywords:
                        if keyword.lower() in text.lower():
                            # Extract single location from this text
                            single_location = self.extract_single_location(text)
                            if single_location:
                                return single_location
                    
                    # Also try to extract even without keyword match
                    single_location = self.extract_single_location(text)
                    if single_location:
                        return single_location
        
        except Exception as e:
            logger.debug(f"Error extracting location: {e}")
        
        # Fallback: try to find location using selectors
        location_element = self.find_element_with_selectors(SELECTORS['location'])
        if location_element:
            location = self.get_text(location_element)
            if location:
                single_location = self.extract_single_location(location)
                if single_location:
                    return single_location
        
        # Fallback: try regex patterns
        try:
            page_text = self.driver.page_source[:5000]  # Only check first 5000 chars
            location_patterns = [
                r'Location[:\s]+([^,\n<;]+)',
                r'Duty Station[:\s]+([^,\n<;]+)',
                r'based in ([^,\n<.;]+)'
            ]
            for pattern in location_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    location = match.group(1).strip()
                    single_location = self.extract_single_location(location)
                    if single_location:
                        return single_location
        except Exception as e:
            logger.debug(f"Error in regex location extraction: {e}")
        
        return ""
    
    def extract_job_type(self):
        type_element = self.find_element_with_selectors(SELECTORS['job_type'])
        if type_element:
            job_type = self.get_text(type_element)
            if job_type:
                return self.clean_text(job_type)
        try:
            page_text = self.driver.page_source.lower()
            type_patterns = {
                'National': ['national position', 'national only', 'nationals only'],
                'International': ['international position', 'international consultant'],
                'Consultant': ['consultant'],
                'Full-time': ['full-time', 'full time'],
                'Part-time': ['part-time', 'part time']
            }
            for type_name, keywords in type_patterns.items():
                if any(keyword in page_text for keyword in keywords):
                    return type_name
        except:
            pass
        return ""
    
    def extract_deadline(self):
        deadline_element = self.find_element_with_selectors(SELECTORS['deadline'])
        if deadline_element:
            deadline = self.get_text(deadline_element)
            if deadline:
                date_pattern = r'(\d{1,2}\s+[A-Z][a-z]+\s+\d{4}|[A-Z][a-z]+\s+\d{1,2},\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})'
                match = re.search(date_pattern, deadline, re.IGNORECASE)
                if match:
                    return match.group(1)
                return self.clean_text(deadline)
        return ""
    
    def extract_summary(self):
        try:
            summary_element = self.driver.find_element(By.CSS_SELECTOR, 
                ".summary .ip-typography[type='bodyEmphasis']:contains('Summary') + .ip-typography[type='body']")
            summary = self.get_text(summary_element)
            if summary and len(summary) > 50:
                return self.clean_text(self.remove_summary_prefix(summary))
        except:
            pass
        
        summary_element = self.find_element_with_selectors(SELECTORS['summary'])
        if summary_element:
            summary = self.get_text(summary_element)
            if summary and len(summary) > 50:
                return self.clean_text(self.remove_summary_prefix(summary))
        return ""
    
    def extract_full_description(self):
        description_parts = []
        for selector in SELECTORS['description_sections']:
            try:
                sections = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for section in sections:
                    text = self.get_text(section)
                    if text and len(text) > 100:
                        description_parts.append(self.format_description(text))
            except:
                continue
        
        if not description_parts:
            main_content = self.find_element_with_selectors(SELECTORS['main_content'])
            if main_content:
                full_text = self.get_text(main_content)
                if full_text:
                    description_parts.append(self.format_description(full_text))
        
        if description_parts:
            full_description = "\n\n".join(description_parts)
            sentences = re.split(r'(?<=[.!?])\s+', full_description)
            seen = set()
            unique_sentences = []
            for sentence in sentences:
                normalized = sentence[:100].lower()
                if normalized not in seen:
                    seen.add(normalized)
                    unique_sentences.append(sentence)
            full_description = " ".join(unique_sentences)
            full_description = re.sub(r'\s+', ' ', full_description)
            return self.format_description(full_description)
        return ""
    
    def format_description(self, text):
        if not text:
            return ""
        text = re.sub(r'^#{1,3}\s+', '', text, flags=re.MULTILINE)
        sentences = re.split(r'(?<=[.!?])\s+', text)
        paragraphs = []
        current_paragraph = []
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) > 300:
                if current_paragraph:
                    paragraphs.append(' '.join(current_paragraph))
                    current_paragraph = []
                paragraphs.append(sentence)
            else:
                current_paragraph.append(sentence)
                if len(current_paragraph) >= 4:
                    paragraphs.append(' '.join(current_paragraph))
                    current_paragraph = []
        if current_paragraph:
            paragraphs.append(' '.join(current_paragraph))
        cleaned_paragraphs = []
        for para in paragraphs:
            if para and para[0].islower():
                para = para[0].upper() + para[1:]
            if para and not para[-1] in ['.', '!', '?', ':', ';']:
                para += '.'
            cleaned_paragraphs.append(para)
        return '\n\n'.join(cleaned_paragraphs)
    
    def extract_requirements(self):
        requirements = []
        try:
            req_title = self.driver.find_element(By.CSS_SELECTOR, 
                ".summary .ip-typography[type='bodyEmphasis']:contains('Candidate Requirements')")
            parent = req_title.find_element(By.XPATH, "..")
            lists = parent.find_elements(By.TAG_NAME, "ul")
            if not lists:
                lists = parent.find_elements(By.TAG_NAME, "ol")
            for lst in lists:
                items = lst.find_elements(By.TAG_NAME, "li")
                for item in items:
                    text = self.clean_text(self.get_text(item))
                    if text and len(text) > 10:
                        requirements.append(text)
            if requirements:
                return requirements
        except:
            pass
        
        heading_elements = self.find_elements_with_selectors(SELECTORS['requirements_headings'])
        for heading in heading_elements:
            try:
                parent = heading.find_element(By.XPATH, "..")
                lists = parent.find_elements(By.TAG_NAME, "ul")
                if not lists:
                    lists = parent.find_elements(By.TAG_NAME, "ol")
                for lst in lists:
                    items = lst.find_elements(By.TAG_NAME, "li")
                    for item in items:
                        text = self.clean_text(self.get_text(item))
                        if text and len(text) > 10:
                            requirements.append(text)
                if not requirements:
                    current = heading
                    for _ in range(5):
                        try:
                            current = current.find_element(By.XPATH, "following-sibling::*[1]")
                            if current.tag_name == 'p':
                                text = self.clean_text(self.get_text(current))
                                if text and len(text) > 20:
                                    sentences = re.split(r'[.;]\s+', text)
                                    for sentence in sentences:
                                        if len(sentence) > 15:
                                            requirements.append(sentence)
                            elif current.tag_name in ['h2', 'h3', 'h4']:
                                break
                        except:
                            break
            except:
                continue
        
        if not requirements:
            all_lists = self.find_elements_with_selectors(SELECTORS['lists'])
            for lst in all_lists:
                try:
                    list_text = self.get_text(lst).lower()
                    if any(keyword in list_text for keyword in 
                          ['experience', 'degree', 'qualification', 'skill', 'required', 
                           'ability', 'knowledge', 'proficiency', 'background']):
                        items = lst.find_elements(By.TAG_NAME, "li")
                        for item in items:
                            text = self.clean_text(self.get_text(item))
                            if text and len(text) > 10:
                                requirements.append(text)
                except:
                    continue
        
        cleaned_requirements = []
        seen = set()
        for req in requirements:
            req = req.rstrip('.;,')
            if req and req[0].islower():
                req = req[0].upper() + req[1:]
            normalized = re.sub(r'\s+', ' ', req.lower())
            normalized = re.sub(r'[^\w\s]', '', normalized)
            if normalized not in seen and len(req) > 10:
                seen.add(normalized)
                cleaned_requirements.append(req)
        return cleaned_requirements
    
    def extract_responsibilities(self):
        responsibilities = []
        try:
            responsibility_xpaths = [
                "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'responsibilities')]",
                "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'duties')]",
                "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'key activities')]"
            ]
            for xpath in responsibility_xpaths:
                headings = self.driver.find_elements(By.XPATH, xpath)
                for heading in headings:
                    try:
                        next_ul = heading.find_element(By.XPATH, "following-sibling::ul[1]")
                        items = next_ul.find_elements(By.TAG_NAME, "li")
                        for item in items:
                            text = self.clean_text(self.get_text(item))
                            if text and len(text) > 10:
                                responsibilities.append(text)
                        break
                    except:
                        continue
        except:
            pass
        return responsibilities
    
    def extract_application_info(self):
        app_info = {'url': '', 'email': ''}
        apply_element = self.find_element_with_selectors(SELECTORS['apply_button'])
        if apply_element:
            url = self.get_attribute(apply_element, 'href')
            if url:
                if 'signin' in url.lower() or 'login' in url.lower():
                    return None
                app_info['url'] = url
        if not app_info['url']:
            return None
        try:
            page_text = self.driver.page_source
            email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
            emails = re.findall(email_pattern, page_text)
            for email in emails:
                if 'example.com' not in email.lower() and 'noreply' not in email.lower():
                    app_info['email'] = email
                    break
        except:
            pass
        return app_info
    
    def create_slug(self, title):
        if not title:
            return f"job-{uuid.uuid4().hex[:8]}"
        slug = title.lower()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'\s+', '-', slug)
        slug = slug[:100].strip('-')
        return slug
    
    def determine_category(self, title):
        if not title:
            return "General"
        title_lower = title.lower()
        categories = {
            'Healthcare': ['health', 'medical', 'nurse', 'doctor', 'gbv', 'malaria', 'nutrition', 'wash', 'psychosocial', 'mhpss'],
            'Technology': ['tech', 'software', 'it', 'data', 'analyst', 'digital', 'system', 'information', 'innovation'],
            'Management': ['manager', 'director', 'coordinator', 'supervisor', 'lead', 'head', 'chief'],
            'Administration': ['admin', 'assistant', 'officer', 'programme', 'hr', 'human resources', 'fleet', 'driver'],
            'Finance': ['finance', 'accountant', 'auditor', 'financial', 'banker', 'investment'],
            'Consultancy': ['consultant', 'advisor', 'specialist', 'expert'],
            'Research': ['research', 'analyst', 'evaluation', 'monitoring', 'meal', 'evidence'],
            'Environment': ['environment', 'climate', 'energy', 'renewable', 'sustainable', 'biodiversity'],
            'Development': ['development', 'program', 'project', 'humanitarian', 'relief', 'ngo']
        }
        for category, keywords in categories.items():
            for keyword in keywords:
                if keyword in title_lower:
                    return category
        return "General"
    
    def format_requirements_as_bullets(self, requirements_list):
        if not requirements_list:
            return ""
        seen = set()
        unique_reqs = []
        for req in requirements_list:
            normalized = re.sub(r'\s+', ' ', req.lower().strip())
            if normalized not in seen and len(req) > 10:
                seen.add(normalized)
                unique_reqs.append(req)
        formatted = []
        for req in unique_reqs:
            req = req.strip()
            if req and not req.endswith(('.', '!', '?')):
                req += '.'
            formatted.append(f"•   {req}")
        return "\n\n".join(formatted)
    
    def create_post_content(self, job_data):
        sections = []
        sections.append("## 📋 Job Overview")
        if job_data.get('company'):
            sections.append(f"**Organization:** {job_data['company']}")
        if job_data.get('job_location'):
            sections.append(f"**Location:** {job_data['job_location']}")
        if job_data.get('job_type'):
            sections.append(f"**Job Type:** {job_data['job_type']}")
        sections.append(f"**Category:** {job_data.get('job_category', 'General')}")
        
        if job_data.get('company_tagline'):
            sections.append(f"\n## 📖 Full Job Description")
            sections.append(job_data['company_tagline'])
        
        if job_data.get('full_description'):
            sections.append(f"\n## 📝 Detailed Job Description")
            sections.append(job_data['full_description'])
        
        if job_data.get('requirements_list'):
            sections.append(f"\n## 🎓 Qualifications & Requirements")
            sections.append(self.format_requirements_as_bullets(job_data['requirements_list']))
        
        if job_data.get('job_expires'):
            sections.append(f"\n## ⏰ Application Deadline")
            sections.append(job_data['job_expires'])
        
        return "\n\n".join(sections)
    
    def scrape_job_page(self, url, index=None, total=None):
        try:
            self.driver.get(url)
            time.sleep(5)
            time.sleep(2)
            
            if not self.is_valid_job():
                logger.debug(f"Invalid job page (not a job): {url}")
                return None
            
            job_data = {}
            raw_title = self.extract_job_title()
            if not raw_title:
                logger.debug(f"No job title found: {url}")
                return None
            
            company_info = self.extract_company_info()
            job_data['company'] = company_info['name']
            job_data['company_logo'] = company_info['logo']
            
            if job_data['company'] and job_data['company'] not in raw_title:
                job_data['post_title'] = f"{raw_title} at {job_data['company']}"
            else:
                job_data['post_title'] = raw_title
            
            job_data['job_location'] = self.extract_location()
            job_data['job_type'] = self.extract_job_type()
            job_data['job_expires'] = self.extract_deadline()
            job_data['company_tagline'] = self.extract_summary()
            job_data['job_category'] = self.determine_category(job_data['post_title'])
            job_data['post_tag'] = job_data['job_category']
            
            requirements = self.extract_requirements()
            job_data['requirements_list'] = requirements
            job_data['required_qualifications'] = self.format_requirements_as_bullets(requirements)
            
            app_info = self.extract_application_info()
            if app_info is None:
                logger.debug(f"No valid application URL found (requires login): {url}")
                return None
            
            job_data['application_url'] = app_info.get('url', f"{url}/apply")
            job_data['application_email'] = app_info.get('email', '')
            job_data['slug'] = self.create_slug(job_data['post_title'])
            job_data['post_category'] = 'job'
            job_data['full_description'] = self.extract_full_description()
            job_data['responsibilities'] = self.extract_responsibilities()
            job_data['post_content'] = self.create_post_content(job_data)
            
            return job_data
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
            return None
    
    def find_jobs_from_search(self, search_url):
        job_urls = []
        try:
            logger.info(f"Loading search page: {search_url}")
            self.driver.get(search_url)
            time.sleep(8)
            
            logger.info("Scrolling to load more jobs...")
            last_height = self.driver.execute_script("return document.body.scrollHeight")
            scroll_attempts = 0
            max_scrolls = 20
            while scroll_attempts < max_scrolls:
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(3)
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
                scroll_attempts += 1
                logger.debug(f"Scrolled to height: {new_height}")
            
            all_links = self.driver.find_elements(By.TAG_NAME, "a")
            for link in all_links:
                try:
                    href = link.get_attribute('href')
                    if href and '/jobs/' in href and '/apply' not in href:
                        if '?' in href:
                            href = href.split('?')[0]
                        if href not in job_urls:
                            job_urls.append(href)
                except:
                    continue
            
            page_source = self.driver.page_source
            job_ids = re.findall(r'/jobs/(\d+)', page_source)
            for job_id in set(job_ids):
                url = f"https://www.impactpool.org/jobs/{job_id}"
                if url not in job_urls:
                    job_urls.append(url)
            
            job_urls = list(set(job_urls))
            logger.info(f"Found {len(job_urls)} total job URLs")
            return job_urls
        except Exception as e:
            logger.error(f"Error finding jobs: {e}")
            return []
    
    def close(self):
        if self.driver:
            self.driver.quit()

def save_to_csv(jobs_data, filename=None):
    if not jobs_data:
        return None
    if not filename:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'impactpool_jobs_{timestamp}.csv'
    try:
        columns = [
            'post_title', 'company', 'company_logo', 'company_tagline',
            'job_location', 'job_type', 'job_expires',
            'job_category', 'required_qualifications', 'application_url',
            'application_email', 'slug', 'post_category', 'post_tag', 'post_content'
        ]
        df_data = []
        for job in jobs_data:
            row = {col: job.get(col, '') for col in columns}
            df_data.append(row)
        df = pd.DataFrame(df_data, columns=columns)
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        return filename
    except Exception as e:
        logger.error(f"Error saving CSV: {e}")
        return None

def main():
    print("\n" + "=" * 70)
    print("                    IMPACTPOOL JOB SCRAPER")
    print("=" * 70)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    SEARCH_URL = "https://www.impactpool.org/search?q=&wl%5B%5D=162"
    scraper = None
    
    try:
        print("\n[STEP 1/5] Initializing Web Scraper...")
        print("   - Launching Chrome browser (headless mode)")
        print("   - Setting up user agents and anti-detection measures")
        scraper = ImpactpoolScraper(headless=True)
        print("   ✓ Web scraper initialized successfully")
        
        print("\n[STEP 2/5] Scanning for Job Listings...")
        print(f"   - Search URL: {SEARCH_URL}")
        job_urls = scraper.find_jobs_from_search(SEARCH_URL)
        
        if not job_urls:
            print("   ✗ ERROR: No job URLs found!")
            logger.error("No job URLs found in search results")
            return
        
        print(f"   ✓ Found {len(job_urls)} total job listings")
        
        # Check history for previously scraped jobs
        print("\n[STEP 3/5] Checking for Previously Scraped Jobs...")
        history_summary = scraper.history.get_history_summary()
        print(f"   - Previously scraped jobs (total): {history_summary['total_scraped']}")
        print(f"   - Scraped today: {history_summary['today_scraped']}")
        if history_summary['last_scraped']:
            print(f"   - Last scrape: {history_summary['last_scraped']}")
        
        new_job_urls = []
        for url in job_urls:
            if not scraper.history.is_job_scraped(url, ""):
                new_job_urls.append(url)
        
        print(f"   - New jobs to scrape: {len(new_job_urls)}")
        
        if not new_job_urls:
            print("\n" + "=" * 70)
            print("✓ ALL DONE - No new jobs to scrape!")
            print(f"  All {len(job_urls)} jobs have been scraped previously.")
            print("=" * 70)
            return
        
        print("\n[STEP 4/5] Scraping Job Details...")
        print("   " + "-" * 66)
        
        jobs_data = []
        skipped_count = 0
        error_count = 0
        
        for i, url in enumerate(new_job_urls, 1):
            # Progress indicator
            progress_pct = (i / len(new_job_urls)) * 100
            progress_bar_len = 30
            filled_len = int(progress_bar_len * i // len(new_job_urls))
            bar = '█' * filled_len + '░' * (progress_bar_len - filled_len)
            
            print(f"\n   [{i}/{len(new_job_urls)}] {bar} {progress_pct:.1f}%")
            print(f"   📍 URL: {url}")
            
            if i > 1:
                delay = random.uniform(2, 4)
                print(f"   ⏳ Waiting {delay:.1f}s before next request...")
                time.sleep(delay)
            
            print("   🔍 Extracting job information...", end=" ", flush=True)
            
            job_data = scraper.scrape_job_page(url, i, len(new_job_urls))
            
            if job_data:
                jobs_data.append(job_data)
                scraper.history.add_job(url, job_data.get('post_title', ''), job_data)
                
                # Display summary of scraped job
                title_short = job_data.get('post_title', 'Unknown')[:60]
                if len(job_data.get('post_title', '')) > 60:
                    title_short += "..."
                
                print("✓ SUCCESS")
                print(f"   📝 Title: {title_short}")
                print(f"   🏢 Company: {job_data.get('company', 'N/A')}")
                print(f"   📍 Location: {job_data.get('job_location', 'N/A')}")
                print(f"   📅 Deadline: {job_data.get('job_expires', 'N/A')}")
                print(f"   📂 Category: {job_data.get('job_category', 'General')}")
                if job_data.get('job_type'):
                    print(f"   🔖 Type: {job_data.get('job_type')}")
            else:
                if "requires login" in str(error_count):
                    skipped_count += 1
                    print("✗ SKIPPED (requires login)")
                else:
                    error_count += 1
                    print("✗ ERROR (failed to extract)")
        
        print("\n   " + "-" * 66)
        print(f"\n   📊 Scraping Summary:")
        print(f"      ✅ Successfully scraped: {len(jobs_data)}")
        print(f"      ⏭️  Skipped (requires login): {skipped_count}")
        print(f"      ❌ Errors: {error_count}")
        print(f"      📋 Total processed: {len(jobs_data) + skipped_count + error_count}")
        
        print("\n[STEP 5/5] Saving Results to CSV...")
        if jobs_data:
            csv_file = save_to_csv(jobs_data)
            if csv_file:
                file_size = os.path.getsize(csv_file) if os.path.exists(csv_file) else 0
                file_size_kb = file_size / 1024
                
                print("\n" + "=" * 70)
                print("                    ✅ SCRAPING COMPLETED SUCCESSFULLY!")
                print("=" * 70)
                print(f"\n   📁 Output File: {csv_file}")
                print(f"   📊 File Size: {file_size_kb:.2f} KB")
                print(f"   📝 Total Jobs Scraped: {len(jobs_data)}")
                print(f"\n   📋 Jobs by Category:")
                
                # Count jobs by category
                category_counts = {}
                for job in jobs_data:
                    cat = job.get('job_category', 'Uncategorized')
                    category_counts[cat] = category_counts.get(cat, 0) + 1
                
                for cat, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True):
                    print(f"      - {cat}: {count}")
                
                print(f"\n   📍 Jobs by Location (Primary):")
                location_counts = {}
                for job in jobs_data:
                    loc = job.get('job_location', 'Unknown')
                    if loc:
                        location_counts[loc] = location_counts.get(loc, 0) + 1
                
                for loc, count in list(location_counts.items())[:10]:  # Show top 10 locations
                    print(f"      - {loc}: {count}")
                if len(location_counts) > 10:
                    print(f"      ... and {len(location_counts) - 10} more locations")
                
                print("\n" + "=" * 70)
                print(f"🏁 Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print("=" * 70 + "\n")
            else:
                print("   ✗ ERROR: Failed to save CSV file!")
        else:
            print("\n" + "=" * 70)
            print("                    ⚠️ SCRAPING COMPLETED WITH WARNINGS")
            print("=" * 70)
            print("\n   No jobs were successfully scraped.")
            print("   Possible issues:")
            print("   - Jobs may require login to view")
            print("   - Website structure may have changed")
            print("   - Network or connection issues")
            print("=" * 70 + "\n")
        
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        logger.error(f"Fatal error in main: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        if scraper:
            print("   Closing browser...")
            scraper.close()
            print("   ✓ Browser closed")
        
        print("\n" + "=" * 70)
        print("                    SCRIPT EXECUTION COMPLETE")
        print("=" * 70 + "\n")

if __name__ == "__main__":
    try:
        import selenium
        import pandas
    except ImportError as e:
        print("\n" + "=" * 70)
        print("                    ❌ MISSING DEPENDENCIES")
        print("=" * 70)
        print("\nPlease install required packages:")
        print("   pip install selenium pandas webdriver-manager")
        print("\n" + "=" * 70 + "\n")
        sys.exit(1)
    
    main()
