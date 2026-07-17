import ast
from pathlib import Path


_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE_ROOT = _BACKEND_ROOT / "src" / "wildfireops"
_API_ROOT = _PACKAGE_ROOT / "api"
_DECISION_ROOT = _PACKAGE_ROOT / "decision"


def _imports(
    path: Path,
    *,
    package_root: Path = _BACKEND_ROOT / "src",
) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = path.parent.relative_to(package_root).parts
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module is not None:
                    imported.append(node.module)
                continue
            parent_count = node.level - 1
            if parent_count > len(package):
                continue
            base = package[: len(package) - parent_count]
            if node.module is not None:
                imported.append(".".join((*base, *node.module.split("."))))
            else:
                imported.extend(".".join((*base, alias.name)) for alias in node.names)
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


def test_decision_layer_has_no_transport_or_persistence_dependencies() -> None:
    violations: list[str] = []
    for path in sorted(_DECISION_ROOT.rglob("*.py")):
        forbidden = sorted(
            module
            for module in _imports(path)
            if module == "sqlalchemy"
            or module.startswith("sqlalchemy.")
            or module == "wildfireops.persistence"
            or module.startswith("wildfireops.persistence.")
            or module == "wildfireops.api"
            or module.startswith("wildfireops.api.")
        )
        if forbidden:
            violations.append(
                f"{path.relative_to(_PACKAGE_ROOT)}: {', '.join(forbidden)}"
            )

    assert violations == [], "forbidden decision dependency:\n" + "\n".join(violations)


def test_import_scanner_resolves_relative_modules(tmp_path: Path) -> None:
    decision = tmp_path / "wildfireops" / "decision"
    decision.mkdir(parents=True)
    decision_module = decision / "example.py"
    decision_module.write_text(
        "from ..persistence.scenarios import ScenarioRepository\n",
        encoding="utf-8",
    )
    package_module = tmp_path / "wildfireops" / "example.py"
    package_module.write_text("from .api import routes\n", encoding="utf-8")

    assert _imports(decision_module, package_root=tmp_path) == (
        "wildfireops.persistence.scenarios",
    )
    assert _imports(package_module, package_root=tmp_path) == ("wildfireops.api",)
