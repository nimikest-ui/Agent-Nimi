"""Tests for the AutoEvaluator task classifier."""
import pytest

from core.evaluator import AutoEvaluator


@pytest.fixture
def evaluator():
    return AutoEvaluator()


class TestClassifyTask:
    """Tests for AutoEvaluator.classify_task."""

    def test_recon_keywords(self, evaluator):
        assert evaluator.classify_task("run nmap recon on 10.0.0.1") == "recon"

    def test_scan_keywords(self, evaluator):
        assert evaluator.classify_task("scan ports on the target") == "scan"

    def test_exploit_keywords(self, evaluator):
        assert evaluator.classify_task("exploit the buffer overflow vulnerability") == "exploit"

    def test_password_keywords(self, evaluator):
        assert evaluator.classify_task("brute force the SSH password with hydra") == "password"

    def test_web_keywords(self, evaluator):
        assert evaluator.classify_task("test the web app for IDOR and auth bypass") == "web"

    def test_code_keywords(self, evaluator):
        assert evaluator.classify_task("write a Python script to automate this") == "code"

    def test_general_fallback(self, evaluator):
        assert evaluator.classify_task("hello how are you") == "general"

    def test_empty_string(self, evaluator):
        assert evaluator.classify_task("") == "general"

    def test_analysis_deprioritized(self, evaluator):
        """When 'analysis' and a more specific type both match, prefer the specific one."""
        result = evaluator.classify_task("analyze the nmap scan results for vulnerabilities")
        assert result != "analysis"  # should match scan or recon, not generic analysis

    def test_cve_classification(self, evaluator):
        assert evaluator.classify_task("explain CVE-2024-1234 severity") == "cve_summar"

    def test_phishing_classification(self, evaluator):
        assert evaluator.classify_task("classify this suspicious email header") == "phishing"

    def test_yara_sigma_classification(self, evaluator):
        assert evaluator.classify_task("write a YARA rule for this IOC") == "yara_sigma"
