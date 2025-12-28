"""
Saw Language Module Resolver

Resolves module imports and builds dependency graphs for multi-file compilation.
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Set, Any
from pathlib import Path


@dataclass
class PackageManifest:
    """Parsed Saw.toml package manifest."""
    name: str = ""
    version: str = ""
    root_dir: str = ""           # Directory containing Saw.toml
    dependencies: Dict[str, str] = field(default_factory=dict)  # Future: package deps


@dataclass
class ExportInfo:
    """Information about an exported symbol in init.saw."""
    source_path: List[str]  # Internal path to the symbol (e.g., ["internal", "foobar", "FooImpl"])
    export_name: str        # Name it's exported as (e.g., "Foo")
    is_glob: bool = False   # True for export foo.*


@dataclass
class FacadeInfo:
    """Parsed init.saw facade for a module/package."""
    exports: List[ExportInfo] = field(default_factory=list)
    has_init_saw: bool = False  # True if init.saw exists (even if empty)


@dataclass
class ModuleInfo:
    """Information about a module discovered by the resolver."""
    path: List[str]           # Fully qualified module path: ["std", "io"]
    source_path: str          # Absolute file path to the .saw file
    source: str = ""          # Source code (loaded lazily)
    ast: Optional['Program'] = None  # Parsed AST (filled after parsing)
    dependencies: List['ModuleInfo'] = field(default_factory=list)
    namespace: Optional['Namespace'] = None  # Module's namespace after type checking


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

        # Cache of parsed package manifests: directory -> PackageManifest
        self._package_cache: Dict[str, PackageManifest] = {}

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

    def get_package_manifest(self, from_file: str) -> Optional[PackageManifest]:
        """
        Get the PackageManifest for the package containing the given file.

        Args:
            from_file: Path to a file in the package

        Returns:
            PackageManifest if Saw.toml found, None otherwise
        """
        file_dir = os.path.dirname(os.path.abspath(from_file))
        package_root = self._find_package_root(file_dir)

        if package_root is None:
            return None

        # Check cache
        if package_root in self._package_cache:
            return self._package_cache[package_root]

        # Parse the manifest
        manifest_path = os.path.join(package_root, "Saw.toml")
        manifest = self._parse_saw_toml(manifest_path)
        if manifest:
            manifest.root_dir = package_root
            self._package_cache[package_root] = manifest

        return manifest

    def _parse_saw_toml(self, path: str) -> Optional[PackageManifest]:
        """
        Parse a Saw.toml file.

        Supports a minimal TOML subset:
        - [section] headers
        - key = "value" string assignments
        - key = value bare values
        - # comments

        Args:
            path: Path to the Saw.toml file

        Returns:
            PackageManifest with parsed values
        """
        try:
            with open(path, 'r') as f:
                content = f.read()
        except IOError:
            return None

        manifest = PackageManifest()
        current_section = None

        for line in content.split('\n'):
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue

            # Section header: [package], [dependencies]
            if line.startswith('[') and line.endswith(']'):
                current_section = line[1:-1].strip()
                continue

            # Key = value
            if '=' in line:
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip()

                # Remove quotes from string values
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]

                # Store based on section
                if current_section == 'package':
                    if key == 'name':
                        manifest.name = value
                    elif key == 'version':
                        manifest.version = value
                elif current_section == 'dependencies':
                    manifest.dependencies[key] = value

        return manifest

    def get_facade_info(self, module_dir: str) -> FacadeInfo:
        """
        Get the facade info for a module directory.

        Checks for init.saw and parses its export statements.

        Args:
            module_dir: Directory to check for init.saw

        Returns:
            FacadeInfo with export information
        """
        init_path = os.path.join(module_dir, "init.saw")

        if not os.path.isfile(init_path):
            return FacadeInfo(has_init_saw=False)

        # Parse init.saw to extract exports
        return self._parse_init_saw(init_path)

    def _parse_init_saw(self, path: str) -> FacadeInfo:
        """
        Parse an init.saw file to extract export declarations.

        Uses the full parser to parse the file, then extracts ExportDecl nodes.

        Args:
            path: Path to init.saw

        Returns:
            FacadeInfo with parsed exports
        """
        try:
            with open(path, 'r') as f:
                source = f.read()
        except IOError:
            return FacadeInfo(has_init_saw=False)

        # Import parser components
        from lexer import Lexer
        from parser import Parser

        try:
            lexer = Lexer(source)
            tokens = lexer.tokenize()
            parser = Parser(tokens)
            ast = parser.parse()
        except SyntaxError:
            # If parsing fails, treat as no facade
            return FacadeInfo(has_init_saw=True)

        # Extract exports from the AST
        exports = []
        for export_decl in getattr(ast, 'exports', []):
            export_name = export_decl.alias or (export_decl.path[-1] if export_decl.path else "")
            exports.append(ExportInfo(
                source_path=export_decl.path,
                export_name=export_name,
                is_glob=export_decl.is_glob
            ))

        return FacadeInfo(exports=exports, has_init_saw=True)

    def has_init_saw(self, module_dir: str) -> bool:
        """Check if a module directory has an init.saw file."""
        return os.path.isfile(os.path.join(module_dir, "init.saw"))

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
