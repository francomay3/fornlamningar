#!/usr/bin/env python3
"""
Ollama API utilities for processing archaeological site descriptions.
"""

import json
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class OllamaConfig:
    """Configuration for Ollama API requests."""
    base_url: str = "http://localhost:11434"
    model: str = "phi3"
    format: str = ""
    stream: bool = False
    timeout: int = 30


class OllamaAPI:
    """A class for making Ollama API calls to process archaeological site descriptions."""
    
    def __init__(self, config: Optional[OllamaConfig] = None):
        self.config = config or OllamaConfig()
        self.session = requests.Session()
    
    def _make_request(self, prompt: str, custom_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make a request to the Ollama API."""
        # Merge custom config with default config
        request_config = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": self.config.stream
        }
        
        # Only add format if it's specified
        if self.config.format:
            request_config["format"] = self.config.format
        
        if custom_config:
            request_config.update(custom_config)
        
        url = f"{self.config.base_url}/api/generate"
        
        try:
            response = self.session.post(
                url,
                json=request_config,
                timeout=self.config.timeout
            )
            response.raise_for_status()
            return response.json()
            
        except requests.RequestException as e:
            logger.error(f"Ollama API request failed: {e}")
            raise
    
    def generate_description(self, site_description: str, 
                           custom_instruction: Optional[str] = None) -> str:
        """
        Generate a description for an archaeological site.
        
        Args:
            site_description: The description of the archaeological site
            custom_instruction: Optional custom instruction to override the default template
            
        Returns:
            A generated description as plain text
        """
        # Default instruction template
        default_instruction = """
Write a brief, engaging description (1-3 sentences) of this archaeological site in a neutral, non-technical tone. Focus on the most interesting and accessible aspects that would appeal to visitors. avoid technical jargon.
"""
        
        instruction = custom_instruction or default_instruction
        
        # Construct the full prompt
        prompt = f"{instruction}\n\nSite description: {site_description}"
        
        try:
            response = self._make_request(prompt)
            
            # Extract the response text
            if 'response' in response:
                return response['response'].strip()
            else:
                raise ValueError("No 'response' field in Ollama API response")
            
        except Exception as e:
            logger.error(f"Failed to generate description: {e}")
            raise
    
    def make_custom_request(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Make a custom request to the Ollama API with any parameters.
        
        Args:
            prompt: The prompt to send to the model
            **kwargs: Any additional parameters to pass to the API
            
        Returns:
            The raw API response
        """
        return self._make_request(prompt, kwargs)


# Convenience function for quick usage
def generate_site_description(site_description: str, 
                            model: str = "phi3",
                            base_url: str = "http://localhost:11434",
                            custom_instruction: Optional[str] = None) -> str:
    """
    Convenience function to quickly generate a description for an archaeological site.
    
    Args:
        site_description: The description of the archaeological site
        model: The Ollama model to use
        base_url: The Ollama API base URL
        custom_instruction: Optional custom instruction
        
    Returns:
        Generated description as plain text
    """
    config = OllamaConfig(model=model, base_url=base_url)
    api = OllamaAPI(config)
    return api.generate_description(site_description, custom_instruction)


if __name__ == "__main__":
    # Example usage
    example_description = "A large stone circle located on a hilltop overlooking the sea. The site contains 12 standing stones arranged in a perfect circle with a diameter of approximately 20 meters. Archaeological excavations revealed pottery fragments and evidence of ritual activities."
    
    try:
        result = generate_site_description(example_description)
        print("Generated Description:")
        print(result)
    except Exception as e:
        print(f"Error: {e}")
