"""Errors the pipelines report as a clear message instead of a traceback."""


class DataPipelineError(Exception):
    """The input data or its configuration does not meet the pipeline's expectations."""
