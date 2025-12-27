"""
Saw Language Module Resolver

Resolves module imports and builds dependency graphs for multi-file compilation.
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Set
from pathlib import Path


@dataclass
class ModuleInfo:
    """Information about a module discovered by the resolver."""
    path: List[str]           # Fully qualified module path: ["std", "io"]
    source_path: str          # Absolute file path to the .saw file
    source: str = ""          # Source code (loaded lazily)
    ast: Optional['Program'] = None  # Parsed AST (filled after parsing)
    dependencies: List['ModuleInfo'] = field(default_factory=list)


class ModuleResolver:
    """
    Resolves module imports to source files and builds dependency graphs.

    Search order for `import foo.bar`:
    1. Current file's directory (for sibling modules)
    2. Package root (directory containing Saw.toml, if any)
    3. Standard library (sawc/std/)
    4. Additional configured search paths

    File lookup for `import foo.bar`:
    - Try `foo/bar.saw`
    - Try `foo/bar/module.saw`
    """

    def __init__(self, search_paths: Optional[List[str]] = None):
        """
        Initialize the module resolver.

        Args:
            search_paths: Additional directories to search for modules.
                         The standard library path is automatically included.
        """
        self.search_paths: List[str] = []

        # Add standard library path (sawc/std/)
        sawc_dir = os.path.dirname(os.path.abspath(__file__))
        std_path = os.path.join(sawc_dir, "std")
        if os.path.isdir(std_path):
            self.search_paths.append(std_path)

        # Add user-provided search paths
        if search_paths:
            self.search_paths.extend(search_paths)

        # Cache of resolved modules: path tuple -> ModuleInfo
        self._cache: Dict[tuple, ModuleInfo] = {}

    def resolve_module(self, path: List[str], from_file: Optional[str] = None) -> Optional[ModuleInfo]:
        """
        Resolve a module path to its source file.

        Args:
            path: Module path components (e.g., ["std", "io"])
            from_file: The file containing the import (for relative resolution)

        Returns:
            ModuleInfo if found, None otherwise
        """
        path_key = tuple(path)

        # Check cache first
        if path_key in self._cache:
            return self._cache[path_key]

        # Build search path list
        search_dirs = list(self.search_paths)

        # Add current file's directory first
        if from_file:
            file_dir = os.path.dirname(os.path.abspath(from_file))
            search_dirs.insert(0, file_dir)

            # Also look for package root (directory with Saw.toml)
            package_root = self._find_package_root(file_dir)
            if package_root and package_root not in search_dirs:
                search_dirs.insert(1, package_root)

        # Try to find the module file
        source_path = self._find_module_file(path, search_dirs)
        if source_path is None:
            return None

        # Create and cache module info
        info = ModuleInfo(
            path=path,
            source_path=source_path
        )
        self._cache[path_key] = info

        return info

    def _find_module_file(self, path: List[str], search_dirs: List[str]) -> Optional[str]:
        """
        Find the source file for a module path.

        Tries:
        1. <search_dir>/path/to/module.saw
        2. <search_dir>/path/to/module/module.saw (for directory modules)
        """
        for search_dir in search_dirs:
            # Handle 'std' prefix specially - look in std/ subdirectory
            if path and path[0] == 'std':
                remaining = path[1:] if len(path) > 1 else []
                base = os.path.join(search_dir)
            else:
                remaining = path
                base = search_dir

            # Build file path from module path
            if remaining:
                module_dir = os.path.join(base, *remaining[:-1]) if len(remaining) > 1 else base
                module_name = remaining[-1]
            else:
                module_dir = base
                module_name = path[-1] if path else ""

            # Try direct file: foo/bar.saw
            direct_path = os.path.join(module_dir, f"{module_name}.saw")
            if os.path.isfile(direct_path):
                return os.path.abspath(direct_path)

            # Try directory module: foo/bar/module.saw
            dir_module_path = os.path.join(module_dir, module_name, "module.saw")
            if os.path.isfile(dir_module_path):
                return os.path.abspath(dir_module_path)

        return None

    def _find_package_root(self, start_dir: str) -> Optional[str]:
        """
        Find the package root by looking for Saw.toml.

        Walks up the directory tree from start_dir until finding Saw.toml
        or reaching the filesystem root.
        """
        current = os.path.abspath(start_dir)

        while True:
            manifest = os.path.join(current, "Saw.toml")
            if os.path.isfile(manifest):
                return current

            parent = os.path.dirname(current)
            if parent == current:
                # Reached filesystem root
                return None
            current = parent

    def load_module_source(self, info: ModuleInfo) -> str:
        """Load the source code for a module."""
        if not info.source:
            with open(info.source_path, 'r') as f:
                info.source = f.read()
        return info.source

    def build_dependency_graph(self, entry: ModuleInfo) -> List[ModuleInfo]:
        """
        Build a topologically sorted list of modules starting from entry.

        This discovers all imported modules and returns them in dependency order
        (dependencies before dependents).

        Args:
            entry: The entry point module

        Returns:
            List of ModuleInfo in topological order (dependencies first)
        """
        # This requires parsing to discover imports, so we need the parser
        # For now, return just the entry module
        # Full implementation will be added when integrating with the compiler
        return [entry]

    def resolve_import_path(self, import_path: List[str],
                           current_module: Optional[List[str]] = None) -> List[str]:
        """
        Resolve a potentially relative import path to an absolute module path.

        Handles:
        - 'package.foo' -> Resolve from package root
        - 'parent.foo' -> Resolve relative to parent module
        - 'foo.bar' -> Absolute path

        Args:
            import_path: The import path components
            current_module: The module path of the importing file

        Returns:
            Resolved absolute module path
        """
        if not import_path:
            return []

        if import_path[0] == 'package':
            # Package-relative import: package.foo.bar -> foo.bar
            # (Package root is found via Saw.toml)
            return import_path[1:]

        if import_path[0] == 'parent':
            # Parent-relative import
            if current_module and len(current_module) > 1:
                # parent.foo -> parent_module_path.foo
                return current_module[:-1] + import_path[1:]
            else:
                # No parent, just use the rest of the path
                return import_path[1:]

        # Absolute import path
        return import_path
