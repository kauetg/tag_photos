"""Pick the compute device: cuda, then mps, then cpu."""
from __future__ import annotations


def pick_device() -> str:
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def onnx_providers() -> list[str]:
    """Execution providers for onnxruntime (InsightFace): CUDA when available, else CPU."""
    try:
        import onnxruntime
    except ImportError:
        return ["CPUExecutionProvider"]
    available = onnxruntime.get_available_providers()
    if "CUDAExecutionProvider" in available:
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]
