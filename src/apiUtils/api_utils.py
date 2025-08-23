#!/usr/bin/env python3
"""
API utilities for making HTTP requests with rate limiting, retry logic, and error handling.
"""

import asyncio
import time
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
import aiohttp
from asyncio_throttle import Throttler
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from ratelimit import limits, sleep_and_retry
from backoff import on_exception, expo
import urllib3

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Disable SSL warnings for development (remove in production)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


@dataclass
class APIConfig:
    """Configuration for API requests."""
    base_url: str
    rate_limit: int = 10  # requests per second
    max_retries: int = 3
    timeout: int = 30
    headers: Optional[Dict[str, str]] = None
    api_key: Optional[str] = None


class RateLimitedAPI:
    """A class for making rate-limited API calls with retry logic."""
    
    def __init__(self, config: APIConfig):
        self.config = config
        self.throttler = Throttler(rate_limit=config.rate_limit)
        self.session = requests.Session()
        
        # Set default headers
        if config.headers:
            self.session.headers.update(config.headers)
        
        if config.api_key:
            self.session.headers.update({'Authorization': f'Bearer {config.api_key}'})
    
    @sleep_and_retry
    @limits(calls=10, period=1)  # 10 calls per second
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((requests.RequestException, ConnectionError))
    )
    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        """Make a GET request with rate limiting and retry logic."""
        url = urljoin(self.config.base_url, endpoint)
        
        try:
            response = self.session.get(
                url, 
                params=params, 
                timeout=self.config.timeout,
                verify=False  # For development - remove in production
            )
            response.raise_for_status()
            return response
            
        except requests.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            raise
    
    @sleep_and_retry
    @limits(calls=10, period=1)
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((requests.RequestException, ConnectionError))
    )
    def post(self, endpoint: str, data: Optional[Dict[str, Any]] = None, 
             json: Optional[Dict[str, Any]] = None) -> requests.Response:
        """Make a POST request with rate limiting and retry logic."""
        url = urljoin(self.config.base_url, endpoint)
        
        try:
            response = self.session.post(
                url, 
                data=data,
                json=json,
                timeout=self.config.timeout,
                verify=False
            )
            response.raise_for_status()
            return response
            
        except requests.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            raise


class AsyncRateLimitedAPI:
    """An async class for making rate-limited API calls."""
    
    def __init__(self, config: APIConfig):
        self.config = config
        self.throttler = Throttler(rate_limit=config.rate_limit)
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        """Async context manager entry."""
        headers = self.config.headers or {}
        if self.config.api_key:
            headers['Authorization'] = f'Bearer {self.config.api_key}'
        
        self.session = aiohttp.ClientSession(
            base_url=self.config.base_url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=self.config.timeout)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, ConnectionError))
    )
    async def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make an async GET request with rate limiting and retry logic."""
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")
        
        async with self.throttler:
            try:
                async with self.session.get(endpoint, params=params) as response:
                    response.raise_for_status()
                    return await response.json()
                    
            except aiohttp.ClientError as e:
                logger.error(f"Async request failed for {endpoint}: {e}")
                raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, ConnectionError))
    )
    async def post(self, endpoint: str, data: Optional[Dict[str, Any]] = None, 
                   json: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make an async POST request with rate limiting and retry logic."""
        if not self.session:
            raise RuntimeError("Session not initialized. Use async context manager.")
        
        async with self.throttler:
            try:
                async with self.session.post(endpoint, data=data, json=json) as response:
                    response.raise_for_status()
                    return await response.json()
                    
            except aiohttp.ClientError as e:
                logger.error(f"Async request failed for {endpoint}: {e}")
                raise


def batch_requests(api: RateLimitedAPI, endpoints: List[str], 
                  params_list: Optional[List[Dict[str, Any]]] = None) -> List[requests.Response]:
    """Make batch requests with rate limiting."""
    responses = []
    params_list = params_list or [{}] * len(endpoints)
    
    for endpoint, params in zip(endpoints, params_list):
        try:
            response = api.get(endpoint, params)
            responses.append(response)
            logger.info(f"Successfully fetched {endpoint}")
            
        except Exception as e:
            logger.error(f"Failed to fetch {endpoint}: {e}")
            responses.append(None)
    
    return responses


async def batch_async_requests(api: AsyncRateLimitedAPI, endpoints: List[str],
                              params_list: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Make batch async requests with rate limiting."""
    tasks = []
    params_list = params_list or [{}] * len(endpoints)
    
    for endpoint, params in zip(endpoints, params_list):
        task = api.get(endpoint, params)
        tasks.append(task)
    
    try:
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        return responses
        
    except Exception as e:
        logger.error(f"Batch async requests failed: {e}")
        return []


# Example usage functions
def example_sync_api():
    """Example of using the synchronous API client."""
    config = APIConfig(
        base_url="https://api.example.com",
        rate_limit=5,  # 5 requests per second
        headers={'User-Agent': 'Fornlamningar-API-Client/1.0'}
    )
    
    api = RateLimitedAPI(config)
    
    try:
        response = api.get("/endpoint", params={"param": "value"})
        return response.json()
    except Exception as e:
        logger.error(f"API call failed: {e}")
        return None


async def example_async_api():
    """Example of using the async API client."""
    config = APIConfig(
        base_url="https://api.example.com",
        rate_limit=10,  # 10 requests per second
        headers={'User-Agent': 'Fornlamningar-API-Client/1.0'}
    )
    
    async with AsyncRateLimitedAPI(config) as api:
        try:
            response = await api.get("/endpoint", params={"param": "value"})
            return response
        except Exception as e:
            logger.error(f"Async API call failed: {e}")
            return None
