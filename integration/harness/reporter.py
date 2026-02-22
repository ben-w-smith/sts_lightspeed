"""Test result reporting for integration tests."""
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from .state_comparator import ComparisonResult, DiscrepancySeverity


@dataclass
class ActionRecord:
    """Record of a single action taken during testing."""
    step: int
    game_command: str
    sim_command: str
    action_type: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class StepResult:
    """Result of a single test step."""
    step: int
    action: ActionRecord
    comparison: Optional[ComparisonResult] = None
    error: Optional[str] = None


@dataclass
class TestResult:
    """Result of a complete test run."""
    test_name: str
    seed: int
    character: str
    ascension: int
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    end_time: Optional[str] = None
    total_steps: int = 0
    passed: bool = True
    critical_failures: int = 0
    major_failures: int = 0
    minor_failures: int = 0
    step_results: List[StepResult] = field(default_factory=list)
    final_game_state: Optional[Dict[str, Any]] = None
    final_sim_state: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

    def add_step(self, step_result: StepResult):
        """Add a step result to the test."""
        self.step_results.append(step_result)
        self.total_steps = len(self.step_results)

        if step_result.comparison:
            self.critical_failures += step_result.comparison.critical_count
            self.major_failures += step_result.comparison.major_count
            self.minor_failures += step_result.comparison.minor_count

            if step_result.comparison.critical_count > 0:
                self.passed = False

        if step_result.error:
            self.passed = False

    def finalize(self):
        """Mark the test as complete."""
        self.end_time = datetime.now().isoformat()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TestResult':
        """Create a TestResult from a dictionary.

        Args:
            data: Dictionary containing test result data.

        Returns:
            TestResult instance.
        """
        # Handle step_results separately to reconstruct properly
        step_results = []
        for step_data in data.get('step_results', []):
            action_data = step_data.get('action', {})
            action = ActionRecord(
                step=action_data.get('step', 0),
                game_command=action_data.get('game_command', ''),
                sim_command=action_data.get('sim_command', ''),
                action_type=action_data.get('action_type', ''),
                timestamp=action_data.get('timestamp', '')
            )
            step_results.append(StepResult(
                step=step_data.get('step', 0),
                action=action,
                comparison=None,  # Comparison results are not fully reconstructed
                error=step_data.get('error')
            ))

        return cls(
            test_name=data.get('test_name', ''),
            seed=data.get('seed', 0),
            character=data.get('character', 'IRONCLAD'),
            ascension=data.get('ascension', 0),
            start_time=data.get('start_time', ''),
            end_time=data.get('end_time'),
            total_steps=data.get('total_steps', 0),
            passed=data.get('passed', True),
            critical_failures=data.get('critical_failures', 0),
            major_failures=data.get('major_failures', 0),
            minor_failures=data.get('minor_failures', 0),
            step_results=step_results,
            final_game_state=data.get('final_game_state'),
            final_sim_state=data.get('final_sim_state'),
            error_message=data.get('error_message')
        )

    def get_summary(self) -> str:
        """Get a summary of the test result."""
        status = "PASSED" if self.passed else "FAILED"
        summary = f"Test: {self.test_name}\n"
        summary += f"Status: {status}\n"
        summary += f"Seed: {self.seed}\n"
        summary += f"Character: {self.character} (A{self.ascension})\n"
        summary += f"Steps: {self.total_steps}\n"
        summary += f"Critical: {self.critical_failures}, Major: {self.major_failures}, Minor: {self.minor_failures}\n"
        return summary


class Reporter:
    """Generate test reports in various formats."""

    def __init__(self, output_dir: str = "./test_results"):
        """Initialize the reporter.

        Args:
            output_dir: Directory to write report files.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results: List[TestResult] = []

    def add_result(self, result: TestResult):
        """Add a test result to the report.

        Args:
            result: TestResult to add.
        """
        self.results.append(result)

    def generate_json_report(self, filename: str = "results.json") -> Path:
        """Generate a JSON report of all test results.

        Args:
            filename: Output filename.

        Returns:
            Path to the generated report file.
        """
        filepath = self.output_dir / filename

        # Calculate summary statistics
        total_critical = sum(r.critical_failures for r in self.results)
        total_major = sum(r.major_failures for r in self.results)
        total_minor = sum(r.minor_failures for r in self.results)
        total_steps = sum(r.total_steps for r in self.results)

        data = {
            'generated_at': datetime.now().isoformat(),
            'summary': {
                'total_tests': len(self.results),
                'passed': sum(1 for r in self.results if r.passed),
                'failed': sum(1 for r in self.results if not r.passed),
                'total_steps': total_steps,
                'total_critical': total_critical,
                'total_major': total_major,
                'total_minor': total_minor,
            },
            'results': [asdict(r) for r in self.results]
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)

        return filepath

    def generate_detailed_json_report(self, filename: str = "detailed_results.json") -> Path:
        """Generate a detailed JSON report with full action history.

        This report includes complete action history for bug reproduction.

        Args:
            filename: Output filename.

        Returns:
            Path to the generated report file.
        """
        filepath = self.output_dir / filename

        detailed_results = []
        for result in self.results:
            result_data = {
                'test_name': result.test_name,
                'seed': result.seed,
                'character': result.character,
                'ascension': result.ascension,
                'passed': result.passed,
                'total_steps': result.total_steps,
                'critical_failures': result.critical_failures,
                'major_failures': result.major_failures,
                'minor_failures': result.minor_failures,
                'start_time': result.start_time,
                'end_time': result.end_time,
                'error_message': result.error_message,
                'action_history': [],
                'failed_steps': [],
                'final_states': {
                    'game': result.final_game_state,
                    'sim': result.final_sim_state,
                }
            }

            # Build complete action history
            for step in result.step_results:
                action_entry = {
                    'step': step.step,
                    'action': {
                        'game_command': step.action.game_command,
                        'sim_command': step.action.sim_command,
                        'type': step.action.action_type,
                        'timestamp': step.action.timestamp,
                    },
                    'result': {
                        'error': step.error,
                        'match': step.comparison.match if step.comparison else None,
                        'discrepancies': []
                    }
                }

                if step.comparison:
                    for disc in step.comparison.discrepancies:
                        action_entry['result']['discrepancies'].append({
                            'field': disc.field,
                            'game_value': disc.game_value,
                            'sim_value': disc.sim_value,
                            'severity': disc.severity.value,
                            'message': disc.message,
                        })

                    # Track failed steps
                    if not step.comparison.match:
                        result_data['failed_steps'].append({
                            'step': step.step,
                            'discrepancies': action_entry['result']['discrepancies']
                        })

                result_data['action_history'].append(action_entry)

            detailed_results.append(result_data)

        data = {
            'generated_at': datetime.now().isoformat(),
            'version': '2.0',
            'results': detailed_results
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)

        return filepath

    def generate_markdown_report(self, filename: str = "results.md") -> Path:
        """Generate a Markdown summary report.

        Args:
            filename: Output filename.

        Returns:
            Path to the generated report file.
        """
        filepath = self.output_dir / filename

        lines = []
        lines.append("# Slay the Spire Integration Test Results\n")
        lines.append(f"Generated: {datetime.now().isoformat()}\n")

        # Summary
        passed = sum(1 for r in self.results if r.passed)
        failed = len(self.results) - passed
        lines.append("## Summary\n")
        lines.append(f"- **Total Tests**: {len(self.results)}\n")
        lines.append(f"- **Passed**: {passed}\n")
        lines.append(f"- **Failed**: {failed}\n")

        if self.results:
            total_critical = sum(r.critical_failures for r in self.results)
            total_major = sum(r.major_failures for r in self.results)
            total_minor = sum(r.minor_failures for r in self.results)
            lines.append(f"- **Critical Issues**: {total_critical}\n")
            lines.append(f"- **Major Issues**: {total_major}\n")
            lines.append(f"- **Minor Issues**: {total_minor}\n")

        # Individual test results
        lines.append("\n## Test Results\n")

        for result in self.results:
            status = ":white_check_mark:" if result.passed else ":x:"
            lines.append(f"### {status} {result.test_name}\n")
            lines.append(f"- **Seed**: {result.seed}\n")
            lines.append(f"- **Character**: {result.character} (Ascension {result.ascension})\n")
            lines.append(f"- **Steps**: {result.total_steps}\n")

            if not result.passed:
                lines.append(f"- **Critical**: {result.critical_failures}\n")
                lines.append(f"- **Major**: {result.major_failures}\n")
                lines.append(f"- **Minor**: {result.minor_failures}\n")

                # Show failed steps
                failed_steps = [
                    s for s in result.step_results
                    if s.comparison and not s.comparison.match
                ]
                if failed_steps:
                    lines.append("\n**Failed Steps**:\n")
                    for step in failed_steps[:10]:  # Limit to first 10
                        lines.append(f"- Step {step.step}: ")
                        for disc in step.comparison.discrepancies:
                            lines.append(f"  - {disc.field}: {disc.message}\n")

            lines.append("\n")

        with open(filepath, 'w') as f:
            f.writelines(lines)

        return filepath

    def print_console_report(self, verbose: bool = False):
        """Print a console report of test results.

        Args:
            verbose: If True, print detailed information for each test.
        """
        print("\n" + "=" * 60)
        print("SLAY THE SPIRE INTEGRATION TEST RESULTS")
        print("=" * 60)

        passed = sum(1 for r in self.results if r.passed)
        failed = len(self.results) - passed

        print(f"\nTotal: {len(self.results)} | Passed: {passed} | Failed: {failed}")

        for result in self.results:
            status = "PASS" if result.passed else "FAIL"
            symbol = "[+]" if result.passed else "[-]"

            print(f"\n{symbol} {result.test_name}: {status}")
            print(f"    Seed: {result.seed}, Character: {result.character}")
            print(f"    Steps: {result.total_steps}")

            if not result.passed or verbose:
                print(f"    Critical: {result.critical_failures}, "
                      f"Major: {result.major_failures}, "
                      f"Minor: {result.minor_failures}")

                if verbose and result.step_results:
                    print("    Discrepancies:")
                    for step in result.step_results:
                        if step.comparison and step.comparison.discrepancies:
                            print(f"      Step {step.step}:")
                            for disc in step.comparison.discrepancies[:3]:
                                severity = disc.severity.value
                                print(f"        [{severity}] {disc.field}: {disc.message}")

        print("\n" + "=" * 60)

    def generate_all_reports(self) -> List[Path]:
        """Generate all report types.

        Returns:
            List of paths to generated report files.
        """
        paths = []
        paths.append(self.generate_json_report())
        paths.append(self.generate_detailed_json_report())
        paths.append(self.generate_markdown_report())
        return paths

    def generate_bug_reports(self, output_subdir: str = "bug_reports") -> List[Path]:
        """Generate structured bug reports from failed test results.

        Args:
            output_subdir: Subdirectory within output_dir for bug reports.

        Returns:
            List of paths to generated bug report files.
        """
        # Import here to avoid circular imports
        import sys
        from pathlib import Path
        tests_path = Path(__file__).parent.parent.parent / 'tests' / 'integration' / 'harness'
        if str(tests_path) not in sys.path:
            sys.path.insert(0, str(tests_path))
        from bug_report import BugReportGenerator, BugReport

        bug_dir = self.output_dir / output_subdir
        bug_dir.mkdir(parents=True, exist_ok=True)

        generator = BugReportGenerator()
        report_paths = []

        for result in self.results:
            if result.passed:
                continue

            # Build action history from step results
            action_history = []
            for sr in result.step_results:
                action_history.append({
                    'step': sr.step,
                    'game_command': sr.action.game_command,
                    'sim_command': sr.action.sim_command,
                    'action_type': sr.action.action_type
                })

            # Build discrepancies from comparison
            discrepancies = []
            if result.step_results:
                # Get last failed step for discrepancies
                for sr in reversed(result.step_results):
                    if sr.comparison and sr.comparison.discrepancies:
                        for disc in sr.comparison.discrepancies:
                            discrepancies.append({
                                'field': disc.field,
                                'expected': disc.game_value,
                                'actual': disc.sim_value,
                                'severity': disc.severity.value,
                                'message': disc.message
                            })
                        break

            # Determine severity and category
            severity = 'critical' if result.critical_failures > 0 else ('major' if result.major_failures > 0 else 'minor')
            category = 'unknown'
            if discrepancies:
                field = discrepancies[0].get('field', '').lower()
                if 'monster' in field:
                    category = 'monster'
                elif 'card' in field or 'hand' in field:
                    category = 'card'
                elif 'relic' in field:
                    category = 'relic'
                elif 'combat' in field or 'hp' in field or 'block' in field:
                    category = 'combat'

            # Create bug report
            report = generator.create_report(
                test_name=result.test_name,
                seed=result.seed,
                character=result.character,
                ascension=result.ascension,
                failing_step=result.total_steps,
                action_history=action_history,
                expected_state=result.final_sim_state or {},
                actual_state=result.final_game_state or {},
                discrepancies=discrepancies,
                severity=severity,
                category=category,
                notes=result.error_message or ""
            )

            # Save in both formats
            json_path = bug_dir / f"bug_{report.report_id}.json"
            md_path = bug_dir / f"bug_{report.report_id}.md"

            generator.save_report(report)
            report_paths.append(json_path)
            report_paths.append(md_path)

        return report_paths

    def clear(self):
        """Clear all stored results."""
        self.results = []


def format_discrepancy_report(discrepancies: list, indent: str = "  ") -> str:
    """Format a list of discrepancies for display.

    Args:
        discrepancies: List of Discrepancy objects.
        indent: Indentation string.

    Returns:
        Formatted string.
    """
    lines = []
    for disc in discrepancies:
        severity = disc.severity.value.upper()
        lines.append(f"{indent}[{severity}] {disc.field}")
        lines.append(f"{indent}  Game: {disc.game_value}")
        lines.append(f"{indent}  Sim:  {disc.sim_value}")
        if disc.message:
            lines.append(f"{indent}  {disc.message}")
    return '\n'.join(lines)
