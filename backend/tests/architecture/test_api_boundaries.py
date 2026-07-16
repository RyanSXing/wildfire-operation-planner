import ast
from pathlib import Path


_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE_ROOT = _BACKEND_ROOT / "src" / "wildfireops"
_API_ROOT = _PACKAGE_ROOT / "api"


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
    return tuple(imported)


def test_api_dependency_direction_is_transport_inward_only() -> None:
    violations: list[str] = []
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        relative = path.relative_to(_PACKAGE_ROOT)
        imports = _imports(path)
        if not path.is_relative_to(_API_ROOT) and relative != Path("main.py"):
            forbidden = sorted(
                module for module in imports if module.startswith("wildfireops.api")
            )
        else:
            forbidden = sorted(
                module
                for module in imports
                if module == "sqlalchemy"
                or module.startswith("sqlalchemy.")
                or module.startswith("wildfireops.persistence")
            )
        if forbidden:
            violations.append(f"{relative}: {', '.join(forbidden)}")

    assert violations == [], "forbidden dependency direction:\n" + "\n".join(violations)
