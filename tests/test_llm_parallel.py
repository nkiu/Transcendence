"""Tests for parallel LLM execution with llama.cpp backend."""

import json
import os
import threading
import time
from collections import defaultdict
from typing import Dict, List
from unittest.mock import MagicMock, patch

import pytest

from lib.llm import LLMClient, LlamaCppBackend, OllamaBackend


class TestBackendSelection:
    """Test backend selection based on environment variables."""

    def test_default_backend_is_ollama(self):
        """Default backend should be Ollama."""
        with patch.dict(os.environ, {}, clear=True):
            # Clear LLM_BACKEND if set
            os.environ.pop("LLM_BACKEND", None)
            client = LLMClient(mode="stub")
            assert client.backend_type == "ollama"
            assert isinstance(client._backend, OllamaBackend)

    def test_llamacpp_backend_selection(self):
        """LLM_BACKEND=llamacpp should select llama.cpp backend."""
        with patch.dict(os.environ, {"LLM_BACKEND": "llamacpp"}):
            client = LLMClient(mode="stub")
            assert client.backend_type == "llamacpp"
            assert isinstance(client._backend, LlamaCppBackend)

    def test_llamacpp_url_configuration(self):
        """LLAMACPP_URL should configure the llama.cpp server URL."""
        custom_url = "http://custom-server:9999"
        with patch.dict(os.environ, {
            "LLM_BACKEND": "llamacpp",
            "LLAMACPP_URL": custom_url,
        }):
            client = LLMClient(mode="stub")
            assert client.base_url == custom_url

    def test_parallel_slots_configuration(self):
        """LLAMACPP_PARALLEL should configure parallel slots."""
        with patch.dict(os.environ, {
            "LLM_BACKEND": "llamacpp",
            "LLAMACPP_PARALLEL": "8",
        }):
            client = LLMClient(mode="stub")
            # Parallel is disabled in stub mode
            assert client._parallel_slots == 8


class TestParallelProperties:
    """Test parallel execution properties."""

    def test_parallel_disabled_in_stub_mode(self):
        """Parallel should be disabled when mode is stub."""
        with patch.dict(os.environ, {"LLM_BACKEND": "llamacpp"}):
            client = LLMClient(mode="stub")
            assert client.parallel_enabled is False
            assert client.parallel_slots == 1

    def test_parallel_enabled_with_llamacpp(self):
        """Parallel should be enabled with llama.cpp backend and ollama mode."""
        with patch.dict(os.environ, {"LLM_BACKEND": "llamacpp"}):
            client = LLMClient(mode="ollama")
            assert client.parallel_enabled is True
            assert client.parallel_slots == 4  # default

    def test_parallel_disabled_with_ollama_backend(self):
        """Parallel should be disabled with Ollama backend."""
        with patch.dict(os.environ, {"LLM_BACKEND": "ollama"}):
            client = LLMClient(mode="ollama")
            assert client.parallel_enabled is False
            assert client.parallel_slots == 1


class TestSSEParsing:
    """Test SSE format parsing for llama.cpp backend."""

    def test_parse_sse_chunks(self):
        """Test parsing SSE-formatted chunks from llama.cpp."""
        backend = LlamaCppBackend("http://localhost:8080")

        # Simulate SSE response
        sse_lines = [
            b'data: {"choices": [{"text": "Hello"}]}\n',
            b'\n',
            b'data: {"choices": [{"text": " world"}]}\n',
            b'\n',
            b'data: [DONE]\n',
        ]

        collected_chunks = []

        def collect_chunk(chunk: str):
            collected_chunks.append(chunk)

        # Mock urlopen to return our SSE lines
        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.__iter__ = MagicMock(return_value=iter(sse_lines))

        with patch("urllib.request.urlopen", return_value=mock_response):
            result, latency = backend.generate_stream(
                prompt="Test prompt",
                model="test-model",
                on_chunk=collect_chunk,
                timeout=5,
                max_duration=60,
            )

        assert result == "Hello world"
        assert collected_chunks == ["Hello", " world"]

    def test_parse_sse_with_empty_text(self):
        """Test handling of SSE chunks with empty text."""
        backend = LlamaCppBackend("http://localhost:8080")

        sse_lines = [
            b'data: {"choices": [{"text": "Start"}]}\n',
            b'data: {"choices": [{"text": ""}]}\n',  # Empty text
            b'data: {"choices": [{"text": "End"}]}\n',
            b'data: [DONE]\n',
        ]

        collected_chunks = []

        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.__iter__ = MagicMock(return_value=iter(sse_lines))

        with patch("urllib.request.urlopen", return_value=mock_response):
            result, latency = backend.generate_stream(
                prompt="Test",
                model="test",
                on_chunk=lambda c: collected_chunks.append(c),
                timeout=5,
                max_duration=60,
            )

        # Empty chunks should not be collected
        assert collected_chunks == ["Start", "End"]
        assert result == "StartEnd"


class TestThreadSafeCallback:
    """Test thread-safe callback isolation for parallel execution."""

    def test_callbacks_are_isolated_by_civ_id(self):
        """Callbacks from different threads should be correctly tagged by civ_id."""
        # Simulate what happens in NarrationService._make_civ_chunk_callback
        collected: Dict[str, List[str]] = defaultdict(list)
        lock = threading.Lock()

        def make_callback(civ_id: str):
            def callback(chunk: str):
                with lock:
                    collected[civ_id].append(chunk)
            return callback

        # Simulate parallel execution
        def simulate_civ_generation(civ_id: str, chunks: List[str]):
            cb = make_callback(civ_id)
            for chunk in chunks:
                time.sleep(0.001)  # Simulate network delay
                cb(chunk)

        threads = [
            threading.Thread(
                target=simulate_civ_generation,
                args=("civ1", ["A1", "A2", "A3"])
            ),
            threading.Thread(
                target=simulate_civ_generation,
                args=("civ2", ["B1", "B2", "B3"])
            ),
            threading.Thread(
                target=simulate_civ_generation,
                args=("civ3", ["C1", "C2", "C3"])
            ),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each civ should have received only its own chunks
        assert collected["civ1"] == ["A1", "A2", "A3"]
        assert collected["civ2"] == ["B1", "B2", "B3"]
        assert collected["civ3"] == ["C1", "C2", "C3"]

    def test_stream_callback_receives_correct_civ_id(self):
        """Stream callback should receive events tagged with correct civ_id."""
        events = []
        lock = threading.Lock()

        def stream_callback(event: Dict):
            with lock:
                events.append(event)

        def make_chunk_callback(civ_id: str, cycle_id: int):
            def handler(chunk: str):
                stream_callback({
                    "type": "log_chunk",
                    "scope": "civ",
                    "civ_id": civ_id,
                    "cycle": cycle_id,
                    "chunk": chunk,
                })
            return handler

        # Simulate parallel chunk generation
        def generate_chunks(civ_id: str, cycle_id: int, chunks: List[str]):
            cb = make_chunk_callback(civ_id, cycle_id)
            for chunk in chunks:
                cb(chunk)

        threads = [
            threading.Thread(target=generate_chunks, args=("1", 10, ["X", "Y"])),
            threading.Thread(target=generate_chunks, args=("2", 10, ["P", "Q"])),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify events are correctly tagged
        civ1_events = [e for e in events if e["civ_id"] == "1"]
        civ2_events = [e for e in events if e["civ_id"] == "2"]

        assert len(civ1_events) == 2
        assert [e["chunk"] for e in civ1_events] == ["X", "Y"]

        assert len(civ2_events) == 2
        assert [e["chunk"] for e in civ2_events] == ["P", "Q"]


class TestOllamaBackwardCompatibility:
    """Test backward compatibility with Ollama backend."""

    def test_ollama_backend_uses_ndjson(self):
        """Ollama backend should parse NDJSON format."""
        backend = OllamaBackend("http://localhost:11434")

        ndjson_lines = [
            b'{"response": "Hello", "done": false}\n',
            b'{"response": " world", "done": false}\n',
            b'{"response": "!", "done": true}\n',
        ]

        collected = []

        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.__iter__ = MagicMock(return_value=iter(ndjson_lines))

        with patch("urllib.request.urlopen", return_value=mock_response):
            result, latency = backend.generate_stream(
                prompt="Test",
                model="mistral:7b",
                on_chunk=lambda c: collected.append(c),
                timeout=45,
                max_duration=240,
            )

        assert result == "Hello world!"
        assert collected == ["Hello", " world", "!"]

    def test_client_routes_through_backend(self):
        """LLMClient should route calls through the selected backend."""
        with patch.dict(os.environ, {"LLM_BACKEND": "ollama"}):
            client = LLMClient(mode="ollama")

            # Mock the backend's generate_stream
            with patch.object(
                client._backend,
                "generate_stream",
                return_value=("test response", 100)
            ) as mock_gen:
                result = client.generate_civ_thought(
                    civ_name="Test Civ",
                    cycle=1,
                    context="Test context",
                    on_chunk=None,
                    prompt_seed="",
                    template="Cycle {cycle}: {civ_name}\n{context}",
                )

                assert mock_gen.called
                assert result is not None
                assert result.response == "test response"
                assert result.latency_ms == 100


class TestHealthcheck:
    """Test healthcheck for different backends."""

    def test_ollama_healthcheck(self):
        """Ollama healthcheck should check /api/tags endpoint."""
        backend = OllamaBackend("http://localhost:11434")

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            assert backend.healthcheck("http://localhost:11434") is True

    def test_llamacpp_healthcheck_primary(self):
        """llama.cpp healthcheck should check /health endpoint first."""
        backend = LlamaCppBackend("http://localhost:8080")

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            assert backend.healthcheck("http://localhost:8080") is True

    def test_llamacpp_healthcheck_fallback(self):
        """llama.cpp healthcheck should fallback to /v1/models."""
        import urllib.error
        backend = LlamaCppBackend("http://localhost:8080")

        call_count = 0

        def mock_urlopen(url, timeout=None):
            nonlocal call_count
            call_count += 1
            if "/health" in url:
                raise urllib.error.URLError("Connection refused")
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            result = backend.healthcheck("http://localhost:8080")

        assert result is True
        assert call_count == 2  # /health failed, /v1/models succeeded


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
