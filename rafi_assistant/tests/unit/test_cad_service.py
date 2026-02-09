import pytest
import os
import sys
from unittest.mock import MagicMock, patch

# Mock build123d before importing CadService
sys.modules["build123d"] = MagicMock()

from src.services.cad_service import CadService

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
def cad_service():
    return CadService(db=MagicMock())

@pytest.mark.anyio
async def test_generate_stl_success(cad_service):
    # Mock subprocess.run to simulate successful execution
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        
        # Mock os.path.exists to simulate STL being created
        with patch("os.path.exists", return_value=True):
            # Mock open to avoid actually writing files
            with patch("builtins.open", MagicMock()):
                # Mock os.remove
                with patch("os.remove", MagicMock()):
                    result = await cad_service.generate_stl(
                        prompt="Make a box",
                        script_code="result_part = Box(10, 10, 10)"
                    )
                    
                    assert result["status"] == "success"
                    assert "stl_path" in result
                    assert result["prompt"] == "Make a box"

@pytest.mark.anyio
async def test_generate_stl_failure(cad_service):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="Syntax Error")
        
        with patch("builtins.open", MagicMock()):
            with patch("os.remove", MagicMock()):
                result = await cad_service.generate_stl(
                    prompt="Make a box",
                    script_code="invalid code"
                )
                
                assert result["status"] == "failed"
                assert "error" in result
                assert "Syntax Error" in result["error"]
