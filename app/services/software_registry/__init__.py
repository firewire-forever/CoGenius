"""
Software Registry Module
Provides software installation knowledge base and LLM fallback for VSDL compiler.
"""

from .registry import SoftwareRegistry
from .llm_generator import LLMInstallGenerator

__all__ = ['SoftwareRegistry', 'LLMInstallGenerator']