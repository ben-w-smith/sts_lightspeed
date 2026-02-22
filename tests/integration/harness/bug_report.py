"""Structured bug report generation for test failures.

This module provides a structured format for bug reports that can be
generated when discrepancies are detected between the simulator and
the real game.
"""
import json
import os
import subprocess
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional


@dataclass
class CodeReference:
    """A reference to a code location relevant to a bug."""
    file: str
    line: Optional[int] = None
    function: Optional[str] = None
    description: str = ""

    def to_dict(self) -> dict:
        return {
            'file': self.file,
            'line': self.line,
            'function': self.function,
            'description': self.description,
        }


@dataclass
class FixSuggestion:
    """A suggestion for fixing the bug."""
    issue_type: str
    description: str
    files: List[str] = field(default_factory=list)
    search_terms: List[str] = field(default_factory=list)
    likely_functions: List[str] = field(default_factory=list)
    code_references: List[CodeReference] = field(default_factory=list)
    priority: str = "normal"

    def to_dict(self) -> dict:
        return {
            'issue_type': self.issue_type,
            'description': self.description,
            'files': self.files,
            'search_terms': self.search_terms,
            'likely_functions': self.likely_functions,
            'code_references': [r.to_dict() for r in self.code_references],
            'priority': self.priority,
        }


@dataclass
class BugReport:
    """Structured bug report for simulator-game discrepancies.

    This captures all information needed to reproduce and investigate
    a discrepancy between the simulator and real game.
    """
    # Identification
    report_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # Reproduction info
    seed: int = 0
    seed_string: str = ""
    character: str = "IRONCLAD"
    ascension: int = 0
    test_name: str = ""

    # Failure details
    failing_step: int = 0
    action_history: List[Dict[str, Any]] = field(default_factory=list)

    # State comparison
    expected_state: Dict[str, Any] = field(default_factory=dict)
    actual_state: Dict[str, Any] = field(default_factory=dict)
    discrepancies: List[Dict[str, Any]] = field(default_factory=list)

    # Categorization
    severity: str = "major"  # critical, major, minor
    category: str = "unknown"  # combat, card, monster, relic, event

    # Environment
    game_version: str = "unknown"
    simulator_commit: str = "unknown"
    platform: str = ""

    # Additional context
    notes: str = ""
    tags: List[str] = field(default_factory=list)

    # Fix suggestions (new fields)
    fix_suggestions: List[FixSuggestion] = field(default_factory=list)
    related_code_paths: List[CodeReference] = field(default_factory=list)

    def __post_init__(self):
        """Set platform if not provided."""
        if not self.platform:
            import platform
            self.platform = platform.system()

    def to_json(self) -> dict:
        """Convert to JSON-serializable dictionary.

        Returns:
            Dictionary representation.
        """
        data = asdict(self)
        # Handle FixSuggestion and CodeReference serialization
        data['fix_suggestions'] = [s.to_dict() if hasattr(s, 'to_dict') else s for s in self.fix_suggestions]
        data['related_code_paths'] = [r.to_dict() if hasattr(r, 'to_dict') else r for r in self.related_code_paths]
        return data

    def to_markdown(self) -> str:
        """Convert to Markdown format for human reading.

        Returns:
            Markdown string.
        """
        lines = []

        # Header
        lines.append(f"# Bug Report: {self.report_id}")
        lines.append("")
        lines.append(f"**Created**: {self.created_at}")
        lines.append(f"**Severity**: {self.severity.upper()}")
        lines.append(f"**Category**: {self.category}")
        lines.append("")

        # Reproduction
        lines.append("## Reproduction")
        lines.append("")
        lines.append(f"- **Character**: {self.character}")
        lines.append(f"- **Ascension**: {self.ascension}")
        lines.append(f"- **Seed**: {self.seed_string} ({self.seed})")
        lines.append(f"- **Test**: {self.test_name}")
        lines.append(f"- **Failing Step**: {self.failing_step}")
        lines.append("")

        # Environment
        lines.append("## Environment")
        lines.append("")
        lines.append(f"- **Game Version**: {self.game_version}")
        lines.append(f"- **Simulator Commit**: {self.simulator_commit}")
        lines.append(f"- **Platform**: {self.platform}")
        lines.append("")

        # Discrepancies
        lines.append("## Discrepancies")
        lines.append("")
        if self.discrepancies:
            lines.append("| Field | Expected | Actual | Severity |")
            lines.append("|-------|----------|--------|----------|")
            for disc in self.discrepancies:
                field = disc.get('field', 'unknown')
                expected = disc.get('expected', 'N/A')
                actual = disc.get('actual', 'N/A')
                sev = disc.get('severity', 'unknown')
                lines.append(f"| {field} | {expected} | {actual} | {sev} |")
        else:
            lines.append("No specific discrepancies recorded.")
        lines.append("")

        # Action History
        if self.action_history:
            lines.append("## Action History")
            lines.append("")
            lines.append("| Step | Game Command | Sim Command |")
            lines.append("|------|--------------|-------------|")
            for action in self.action_history[-20:]:  # Last 20 actions
                step = action.get('step', '?')
                game_cmd = action.get('game_command', '')
                sim_cmd = action.get('sim_command', '')
                lines.append(f"| {step} | `{game_cmd}` | `{sim_cmd}` |")
            lines.append("")

        # State Comparison
        lines.append("## State Comparison")
        lines.append("")
        lines.append("### Expected State")
        lines.append("```json")
        lines.append(json.dumps(self.expected_state, indent=2, default=str)[:1000])
        lines.append("```")
        lines.append("")
        lines.append("### Actual State")
        lines.append("```json")
        lines.append(json.dumps(self.actual_state, indent=2, default=str)[:1000])
        lines.append("```")
        lines.append("")

        # Fix Suggestions (new section)
        if self.fix_suggestions:
            lines.append("## Fix Suggestions")
            lines.append("")
            for i, suggestion in enumerate(self.fix_suggestions, 1):
                lines.append(f"### Suggestion {i}: {suggestion.issue_type}")
                lines.append("")
                lines.append(f"**Priority**: {suggestion.priority}")
                lines.append("")
                lines.append(f"**Description**: {suggestion.description}")
                lines.append("")

                if suggestion.files:
                    lines.append("**Files to investigate**:")
                    lines.append("")
                    for f in suggestion.files:
                        lines.append(f"- `{f}`")
                    lines.append("")

                if suggestion.search_terms:
                    lines.append("**Search terms**: " + ", ".join(f"`{t}`" for t in suggestion.search_terms))
                    lines.append("")

                if suggestion.likely_functions:
                    lines.append("**Likely functions**: " + ", ".join(f"`{f}()`" for f in suggestion.likely_functions))
                    lines.append("")

                if suggestion.code_references:
                    lines.append("**Code references**:")
                    lines.append("")
                    for ref in suggestion.code_references:
                        location = f"{ref.file}"
                        if ref.line:
                            location += f":{ref.line}"
                        lines.append(f"- `{location}` - {ref.description}")
                    lines.append("")

        # Related Code Paths (new section)
        if self.related_code_paths:
            lines.append("## Related Code Paths")
            lines.append("")
            for ref in self.related_code_paths:
                location = f"{ref.file}"
                if ref.line:
                    location += f":{ref.line}"
                if ref.function:
                    location += f" in `{ref.function}()`"
                lines.append(f"- `{location}` - {ref.description}")
            lines.append("")

        # Notes
        if self.notes:
            lines.append("## Notes")
            lines.append("")
            lines.append(self.notes)
            lines.append("")

        # Tags
        if self.tags:
            lines.append("## Tags")
            lines.append("")
            lines.append(", ".join(f"`{t}`" for t in self.tags))
            lines.append("")

        return "\n".join(lines)

    def save(self, output_dir: str) -> Path:
        """Save bug report to files.

        Args:
            output_dir: Directory to save reports.

        Returns:
            Path to the saved report file.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Save JSON
        json_path = output_path / f"bug_report_{self.report_id}.json"
        with open(json_path, 'w') as f:
            json.dump(self.to_json(), f, indent=2, default=str)

        # Save Markdown
        md_path = output_path / f"bug_report_{self.report_id}.md"
        with open(md_path, 'w') as f:
            f.write(self.to_markdown())

        return md_path


class BugReportGenerator:
    """Generates bug reports from test failures."""

    def __init__(self, output_dir: str = "./test_results/bug_reports"):
        """Initialize the bug report generator.

        Args:
            output_dir: Directory to save bug reports.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._reports: List[BugReport] = []

    def create_report(
        self,
        test_name: str,
        seed: int,
        character: str,
        ascension: int,
        failing_step: int,
        action_history: List[Dict[str, Any]],
        expected_state: Dict[str, Any],
        actual_state: Dict[str, Any],
        discrepancies: List[Dict[str, Any]],
        severity: str = "major",
        category: str = "unknown",
        notes: str = "",
        generate_fix_suggestions: bool = True
    ) -> BugReport:
        """Create a new bug report.

        Args:
            test_name: Name of the failing test.
            seed: Game seed.
            character: Character class.
            ascension: Ascension level.
            failing_step: Step where failure occurred.
            action_history: List of actions taken.
            expected_state: Expected game state.
            actual_state: Actual game state.
            discrepancies: List of discrepancy details.
            severity: Bug severity (critical, major, minor).
            category: Bug category (combat, card, monster, relic, event).
            notes: Additional notes.
            generate_fix_suggestions: Whether to auto-generate fix suggestions.

        Returns:
            Created BugReport.
        """
        report = BugReport(
            test_name=test_name,
            seed=seed,
            seed_string=f"{seed:X}" if seed else "",
            character=character,
            ascension=ascension,
            failing_step=failing_step,
            action_history=action_history,
            expected_state=expected_state,
            actual_state=actual_state,
            discrepancies=discrepancies,
            severity=severity,
            category=category,
            notes=notes,
            game_version=self._get_game_version(),
            simulator_commit=self._get_simulator_commit()
        )

        # Generate fix suggestions if requested
        if generate_fix_suggestions and discrepancies:
            self._populate_fix_suggestions(report)

        self._reports.append(report)
        return report

    def _populate_fix_suggestions(self, report: BugReport):
        """Populate fix suggestions for a bug report.

        Args:
            report: The bug report to populate.
        """
        try:
            # Import fix analyzer
            import sys
            from pathlib import Path
            integration_path = Path(__file__).parent.parent.parent / 'integration' / 'harness'
            if str(integration_path) not in sys.path:
                sys.path.insert(0, str(integration_path))

            from fix_analyzer import FixAnalyzer

            analyzer = FixAnalyzer()
            suggestions = analyzer.analyze_discrepancies(report.discrepancies)

            report.fix_suggestions = [
                FixSuggestion(
                    issue_type=s.issue_type,
                    description=s.description,
                    files=s.files,
                    search_terms=s.search_terms,
                    likely_functions=s.likely_functions,
                    priority=s.priority,
                )
                for s in suggestions
            ]

            # Generate code references for the first suggestion
            if suggestions and suggestions[0].search_terms:
                refs = analyzer.find_code_references(
                    suggestions[0].search_terms[0],
                    suggestions[0].files
                )
                report.related_code_paths = [
                    CodeReference(
                        file=r.file,
                        line=r.line,
                        function=r.function,
                        description=r.description,
                    )
                    for r in refs[:10]
                ]

        except Exception:
            # If fix analyzer isn't available, just skip
            pass

    def save_report(self, report: BugReport) -> Path:
        """Save a bug report.

        Args:
            report: BugReport to save.

        Returns:
            Path to saved report.
        """
        return report.save(str(self.output_dir))

    def save_all_reports(self) -> List[Path]:
        """Save all pending bug reports.

        Returns:
            List of paths to saved reports.
        """
        paths = []
        for report in self._reports:
            paths.append(self.save_report(report))
        return paths

    def get_reports(self) -> List[BugReport]:
        """Get all generated reports.

        Returns:
            List of BugReports.
        """
        return self._reports.copy()

    def clear_reports(self):
        """Clear all stored reports."""
        self._reports.clear()

    def _get_game_version(self) -> str:
        """Get the installed game version.

        Returns:
            Version string or 'unknown'.
        """
        # This would need to be implemented based on how version is stored
        return "unknown"

    def _get_simulator_commit(self) -> str:
        """Get the current git commit of the simulator.

        Returns:
            Commit hash or 'unknown'.
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()[:8]
        except Exception:
            pass
        return "unknown"

    def categorize_discrepancy(self, field: str) -> str:
        """Categorize a discrepancy based on the field.

        Args:
            field: Field name from discrepancy.

        Returns:
            Category string.
        """
        field_lower = field.lower()

        if 'monster' in field_lower:
            return 'monster'
        elif 'card' in field_lower or 'hand' in field_lower:
            return 'card'
        elif 'relic' in field_lower:
            return 'relic'
        elif 'combat' in field_lower or 'hp' in field_lower or 'block' in field_lower:
            return 'combat'
        elif 'event' in field_lower:
            return 'event'
        elif 'potion' in field_lower:
            return 'potion'
        elif 'energy' in field_lower:
            return 'energy'
        else:
            return 'unknown'

    def determine_severity(self, discrepancies: List[Dict[str, Any]]) -> str:
        """Determine severity based on discrepancies.

        Args:
            discrepancies: List of discrepancy dictionaries.

        Returns:
            Severity string (critical, major, minor).
        """
        if not discrepancies:
            return "minor"

        # Check for critical fields
        critical_fields = {'hp', 'energy', 'seed', 'floor', 'act'}

        for disc in discrepancies:
            field = disc.get('field', '').lower()
            sev = disc.get('severity', '').lower()

            if sev == 'critical':
                return 'critical'

            for cf in critical_fields:
                if cf in field:
                    return 'critical'

        return 'major'

    def generate_summary_report(self) -> str:
        """Generate a summary of all bug reports.

        Returns:
            Markdown summary string.
        """
        lines = []
        lines.append("# Bug Report Summary")
        lines.append("")
        lines.append(f"**Generated**: {datetime.now().isoformat()}")
        lines.append(f"**Total Reports**: {len(self._reports)}")
        lines.append("")

        if not self._reports:
            lines.append("No bug reports generated.")
            return "\n".join(lines)

        # Group by category
        by_category: Dict[str, List[BugReport]] = {}
        for report in self._reports:
            cat = report.category
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(report)

        # Summary by category
        lines.append("## By Category")
        lines.append("")
        lines.append("| Category | Count | Critical | Major | Minor |")
        lines.append("|----------|-------|----------|-------|-------|")

        for cat, reports in sorted(by_category.items()):
            critical = sum(1 for r in reports if r.severity == 'critical')
            major = sum(1 for r in reports if r.severity == 'major')
            minor = sum(1 for r in reports if r.severity == 'minor')
            lines.append(f"| {cat} | {len(reports)} | {critical} | {major} | {minor} |")

        lines.append("")

        # Individual reports
        lines.append("## Reports")
        lines.append("")

        for report in self._reports:
            status_emoji = {
                'critical': ':x:',
                'major': ':warning:',
                'minor': ':information_source:'
            }.get(report.severity, ':question:')

            lines.append(f"### {status_emoji} {report.report_id}")
            lines.append("")
            lines.append(f"- **Test**: {report.test_name}")
            lines.append(f"- **Seed**: {report.seed_string}")
            lines.append(f"- **Step**: {report.failing_step}")
            lines.append(f"- **Discrepancies**: {len(report.discrepancies)}")
            lines.append("")

        return "\n".join(lines)
