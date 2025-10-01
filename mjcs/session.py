from .config import config
import logging
import requests
import time
import os
from bs4 import BeautifulSoup
# from pypasser import reCaptchaV3

logger = logging.getLogger('mjcs')

class RequestTimeout(Exception):
    pass

class Forbidden(Exception):
    pass

class MjcsSession:
    def __init__(self):
        self.new_session()
        self.requests = 0
        self.scrapingbee_api_key = os.getenv('SCRAPINGBEE_API_KEY')
        self.scrapingbee_session_id = None  # For maintaining cookies across ScrapingBee requests
        if self.scrapingbee_api_key:
            import random
            self.scrapingbee_session_id = random.randint(100000, 999999)
            logger.info(f'ScrapingBee API key detected - using proxy with session {self.scrapingbee_session_id}')
        else:
            logger.warning('No ScrapingBee API key - using direct requests (may be blocked)')

    def new_session(self):
        self.session = requests.Session()
        # Because all it takes to bypass DataDome is a few headers...
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'en-US,en;q=0.9'
        })

    def request(self, method, url, *args, i=1, **kwargs):
        if i > 2:
            raise Exception('Too many recursed requests')
        self.requests += 1

        # Route through ScrapingBee if API key is available
        if self.scrapingbee_api_key:
            params = kwargs.pop('params', {})
            scrapingbee_params = {
                'api_key': self.scrapingbee_api_key,
                'url': url,
                'render_js': 'true',  # Maryland courts use DataDome - need JS
                'stealth_proxy': 'true',  # Maryland courts aggressively block - use stealth (75 credits)
                'block_resources': 'false',  # Load all resources to avoid detection
                'session_id': self.scrapingbee_session_id,  # Maintain cookies across requests
            }
            # Merge any existing params into the target URL
            if params:
                from urllib.parse import urlencode
                url_with_params = f"{url}?{urlencode(params)}"
                scrapingbee_params['url'] = url_with_params

            # POST data needs to be handled specially
            if method.upper() == 'POST' and 'data' in kwargs:
                scrapingbee_params['forward_data'] = 'true'

            response = self.session.request(
                method,
                'https://app.scrapingbee.com/api/v1/',
                params=scrapingbee_params,
                *args,
                **kwargs,
                timeout=kwargs.get('timeout', config.QUERY_TIMEOUT)
            )
        else:
            # Direct request without proxy
            response = self.session.request(
                method,
                url,
                *args,
                **kwargs,
                timeout=kwargs.get('timeout', config.QUERY_TIMEOUT)
            )

        if ((response.history and response.history[0].status_code == 302 and
                    response.history[0].headers['location'] == f'{config.MJCS_BASE_URL}/inquiry-index.jsp')
                or "Acceptance of the following agreement is" in response.text):
            logger.debug("Renewing session...")
            self.renew()
            return self.request(method, url, *args, i=i+1, **kwargs)
        return response

    def renew(self):
        """Accept disclaimer using JavaScript automation to bypass POST blocking"""
        if not self.scrapingbee_api_key:
            raise Exception("Disclaimer acceptance requires ScrapingBee - direct connections are blocked")

        # Use JavaScript scenario to click checkbox and submit like a real browser
        import json
        js_scenario = {
            "instructions": [
                {"wait": 3000},  # Wait for page load
                {"click": "input[name=disclaimer]"},  # Click disclaimer checkbox
                {"wait": 1000},
                {"click": "button[type=submit]"},  # Click submit button
                {"wait": 3000},  # Wait for form submission and redirect
            ]
        }

        self.requests += 1
        params = {
            'api_key': self.scrapingbee_api_key,
            'url': f'{config.MJCS_BASE_URL}/inquiry-index.jsp',
            'render_js': 'true',  # Need JS to click buttons
            'session_id': self.scrapingbee_session_id,
            'js_scenario': json.dumps(js_scenario),
        }

        response = self.session.request(
            'GET',
            'https://app.scrapingbee.com/api/v1/',
            params=params,
            timeout=30
        )

        if response.status_code != 200:
            err = f"Failed to authenticate with MJCS: code = {response.status_code}, body = {response.text}"
            logger.error(err)
            raise Exception(err)

        logger.info("Disclaimer accepted via JavaScript automation")
        return response