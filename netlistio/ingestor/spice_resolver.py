"""
SPICE-specific model resolver for parsing library content.

Handles .model and .subckt definitions from SPICE library files,
creating appropriate Primitive and Macro instances for dynamic resolution.
"""

import re
from typing import Iterator

from netlistio.models import Port, Primitive, Macro, SpicePrimitiveTypes
from netlistio.ingestor.registry import ModelResolver

__all__ = ["SpiceModelResolver"]


class SpiceModelResolver(ModelResolver):
    """
    SPICE-specific model resolver that parses library content.
    
    Extracts .model and .subckt definitions from library content,
    focusing only on the first line to determine model names and types.
    """
    
    # Regex patterns for model extraction
    MODEL_PATTERN = re.compile(
        rb"^\s*\.model\s+(?P<name>\S+)\s+(?P<type>\S+)",
        re.IGNORECASE | re.MULTILINE
    )
    
    SUBCKT_PATTERN = re.compile(
        rb"^\s*\.subckt\s+(?P<name>\S+)(?:\s+(?P<ports>.*))?",
        re.IGNORECASE | re.MULTILINE
    )
    
    ENDS_PATTERN = re.compile(
        rb"^\s*\.ends\b",
        re.IGNORECASE | re.MULTILINE
    )

    def resolve_model(self, model_name: str, library_content: bytes) -> Macro | Primitive | None:
        """
        Attempt to resolve a model from library content.
        
        :param model_name: Name of model to resolve.
        :param library_content: Raw library file content.
        :return: Resolved model or None if not found.
        """
        # Try to find as a subcircuit first (most common for device models)
        if subckt := self._find_subckt(model_name, library_content):
            return subckt
            
        # Try to find as a primitive model
        if primitive := self._find_model(model_name, library_content):
            return primitive
            
        return None

    def _find_subckt(self, model_name: str, content: bytes) -> Macro | None:
        """Find and create a subcircuit definition from library content."""
        for match in self.SUBCKT_PATTERN.finditer(content):
            subckt_name = match.group("name").decode("utf-8", errors="ignore")
            if subckt_name.lower() == model_name.lower():
                ports_str = match.group("ports")
                if ports_str:
                    port_names = ports_str.decode("utf-8", errors="ignore").split()
                    ports = tuple(Port(name=p) for p in port_names)
                else:
                    ports = tuple()
                
                # Extract subcircuit body and parse instances
                subckt_start = match.end()
                subckt_body = self._extract_subckt_body(content, subckt_start)
                children = self._parse_subckt_instances(subckt_body)
                
                from netlistio.models import Subckt
                return Subckt(name=subckt_name, ports=ports, children=children)
        
        return None
    
    def _extract_subckt_body(self, content: bytes, start_pos: int) -> bytes:
        """Extract the body of a subcircuit from start position to .ends."""
        # Find the next .ends marker
        ends_match = self.ENDS_PATTERN.search(content, start_pos)
        if ends_match:
            return content[start_pos:ends_match.start()]
        # If no .ends found, take rest of content
        return content[start_pos:]
    
    def _parse_subckt_instances(self, body: bytes) -> list:
        """Parse instances from subcircuit body content."""
        from netlistio.models import Instance
        
        instances = []
        lines = body.decode("utf-8", errors="ignore").split("\n")
        
        for line in lines:
            line = line.strip()
            # Skip comments and directives
            if not line or line[0] in ("*", "$", "."):
                continue
            
            # Handle continuation lines (start with +)
            if line[0] == "+":
                continue
            
            # Parse instance line
            tokens = line.split()
            if len(tokens) < 2:
                continue
                
            inst_name = tokens[0]
            
            # For MOSFET instances (m...), format is:
            # mNAME drain gate source bulk MODEL param=value ...
            # Note: params can be "key = value" (with spaces)
            if inst_name[0].lower() == 'm' and len(tokens) >= 6:
                nets = {
                    tokens[1]: None,  # drain
                    tokens[2]: None,  # gate
                    tokens[3]: None,  # source
                    tokens[4]: None,  # bulk
                }
                model_name = tokens[5]
                
                # Parse parameters (handle "key = value" format with spaces)
                params = {}
                i = 6
                while i < len(tokens):
                    token = tokens[i]
                    if "=" in token:
                        # Format: key=value (no spaces)
                        parts = token.split("=", 1)
                        if len(parts) == 2:
                            params[parts[0]] = parts[1]
                        i += 1
                    elif i + 2 < len(tokens) and tokens[i + 1] == "=":
                        # Format: key = value (with spaces)
                        params[tokens[i]] = tokens[i + 2]
                        i += 3
                    else:
                        i += 1
                
                instances.append(Instance(
                    name=inst_name,
                    nets=nets,
                    params=params,
                    model=None,
                    model_name=model_name,
                    parent=None
                ))
        
        return instances

    def _find_model(self, model_name: str, content: bytes) -> Primitive | None:
        """Find and create a primitive model from library content."""
        for match in self.MODEL_PATTERN.finditer(content):
            model_def_name = match.group("name").decode("utf-8", errors="ignore")
            model_type = match.group("type").decode("utf-8", errors="ignore").lower()
            
            if model_def_name.lower() == model_name.lower():
                # Map SPICE model types to our primitives
                if model_type in ("nmos", "nmos4", "nmos3"):
                    return SpicePrimitiveTypes.get_instance("nmos")
                elif model_type in ("pmos", "pmos4", "pmos3"):
                    return SpicePrimitiveTypes.get_instance("pmos")
                elif model_type in ("res", "resistor"):
                    return SpicePrimitiveTypes.get_instance("resistor")
                elif model_type in ("cap", "capacitor"):
                    return SpicePrimitiveTypes.get_instance("capacitor")
                elif model_type in ("ind", "inductor"):
                    return SpicePrimitiveTypes.get_instance("inductor")
                elif model_type in ("diode", "d"):
                    return SpicePrimitiveTypes.get_instance("diode")
        
        return None